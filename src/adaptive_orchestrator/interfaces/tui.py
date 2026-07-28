"""Full-screen curses client over the existing CLI, report, and lifecycle contracts.

The module is split so that everything worth testing stays free of a terminal:
row projection, filtering, scroll math, line editing, width-aware truncation, and
task admission are plain functions or small classes. Only :class:`OrchestratorTui`
touches ``curses``.
"""

from __future__ import annotations

import argparse
import curses
import os
import signal
import subprocess
import sys
import threading
import time
import unicodedata
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from adaptive_orchestrator.infrastructure.events import EventLogError, JsonlEventStore
from adaptive_orchestrator.infrastructure.state_paths import resolve_control_state_directory
from adaptive_orchestrator.operations.reporting import (
    ExecutionBundle,
    ExecutionReportStore,
    render_markdown_report,
    render_text_summary,
)
from adaptive_orchestrator.routing.state import EventProjector, RoutingState

POLL_INTERVAL_MS = 200
ESCAPE_DELAY_MS = 25
AUTO_REFRESH_SECONDS = 2.0
MAX_TASK_OUTPUT_LINES = 5000
DEFAULT_TASK_LIMIT = 3

VIEW_DASHBOARD = "dashboard"
VIEW_DETAIL = "detail"
VIEW_TASKS = "tasks"
VIEW_LOGS = "logs"

EDITOR_SUBMIT = "submit"
EDITOR_CANCEL = "cancel"
EDITOR_EDIT = "edit"
EDITOR_IGNORED = "ignored"

_OK_STATUS = {"completed", "complete", "passed", "success", "succeeded", "verified", "ok"}
_FAIL_STATUS = {
    "failed", "failure", "error", "errored", "abandoned", "cancelled", "canceled",
    "timeout", "timed-out", "timed_out", "spawn_error", "rejected", "blocked",
}
_ACTIVE_STATUS = {"selected", "started", "running", "terminal", "reconciled", "evaluated", "in-progress"}

_STATUS_GLYPH = {"ok": "✓", "fail": "✗", "active": "●", "idle": "·"}
_SPINNER_FRAMES = "|/-\\"
_DASHBOARD_ROW_FORMAT = "{marker}{glyph} {status:<10} {agent:<16} {description}"
_TASK_ROW_FORMAT = "{marker}{spinner} #{index:<3} {status:<11} {elapsed:>7}  {request}"


# --------------------------------------------------------------------------- rows


@dataclass(frozen=True, slots=True)
class DashboardRow:
    execution_id: str
    status: str
    agent: str
    verification: str
    description: str
    attempts: tuple[dict, ...]
    task_id: str = ""
    attempt_count: int = 0


def dashboard_rows(
    records: Sequence[dict],
    lifecycle_state: RoutingState | None = None,
    lifecycle_order: Sequence[str] = (),
) -> tuple[DashboardRow, ...]:
    grouped: dict[str, list[dict]] = {}
    order: list[str] = []
    for index, record in enumerate(records, start=1):
        raw_id = record.get("execution_id")
        execution_id = raw_id if isinstance(raw_id, str) and raw_id else f"legacy-{index}"
        if execution_id not in grouped:
            grouped[execution_id] = []
            order.append(execution_id)
        grouped[execution_id].append(record)

    display_order = list(order)
    for execution_id in lifecycle_order:
        if execution_id not in display_order:
            display_order.append(execution_id)

    rows: list[DashboardRow] = []
    for execution_id in reversed(display_order):
        attempts = tuple(grouped.get(execution_id, ()))
        primary = next((item for item in attempts if not item.get("parent_attempt_id")), attempts[0]) if attempts else {}
        task = primary.get("task") if isinstance(primary.get("task"), dict) else {}
        verification = primary.get("verification") if isinstance(primary.get("verification"), dict) else {}
        description = task.get("description") if isinstance(task.get("description"), str) else ""
        lifecycle = lifecycle_state.executions.get(execution_id) if lifecycle_state is not None else None
        latest_attempt = None
        if lifecycle is not None and lifecycle.attempts:
            latest_attempt = max(lifecycle.attempts.values(), key=lambda item: item.selection_sequence)
        status = _text(primary.get("status"), "unknown")
        agent = _text(primary.get("agent_id"), "unknown")
        record_task_id = _text(task.get("task_id") or primary.get("task_id"), "")
        task_id = _text(lifecycle.task_id, record_task_id) if lifecycle is not None else record_task_id
        attempt_count = len(lifecycle.attempts) if lifecycle is not None else len(attempts)
        if latest_attempt is not None:
            status = _lifecycle_status(latest_attempt.status, latest_attempt.outcome, latest_attempt.terminal)
            agent = _text(latest_attempt.selection.get("selected_agent") or latest_attempt.started.get("agent_id"), agent)
            if not description:
                description = f"task {latest_attempt.task_id}"
        rows.append(DashboardRow(
            execution_id=execution_id,
            status=status,
            agent=agent,
            verification=_text(verification.get("status"), "not-run"),
            description=" ".join(description.split()),
            attempts=attempts,
            task_id=task_id,
            attempt_count=max(attempt_count, len(attempts)),
        ))
    return tuple(rows)


def filter_rows(rows: Sequence[DashboardRow], query: str) -> tuple[DashboardRow, ...]:
    """Case-insensitive AND-match of whitespace-separated terms over row text."""
    terms = query.lower().split()
    if not terms:
        return tuple(rows)
    matched: list[DashboardRow] = []
    for row in rows:
        haystack = " ".join((
            row.execution_id, row.status, row.agent, row.verification, row.description, row.task_id,
        )).lower()
        if all(term in haystack for term in terms):
            matched.append(row)
    return tuple(matched)


def status_category(status: str) -> str:
    value = status.strip().lower()
    if value in _OK_STATUS:
        return "ok"
    if value in _FAIL_STATUS:
        return "fail"
    if value in _ACTIVE_STATUS:
        return "active"
    return "idle"


# ------------------------------------------------------------------- layout math


def scroll_offset(offset: int, selected: int, total: int, height: int) -> int:
    """Smallest scroll adjustment that keeps ``selected`` inside the window."""
    if height <= 0 or total <= 0:
        return 0
    highest = max(total - height, 0)
    offset = max(0, min(offset, highest))
    if selected < offset:
        return max(min(selected, highest), 0)
    if selected >= offset + height:
        return max(min(selected - height + 1, highest), 0)
    return offset


def clamp_offset(offset: int, total: int, height: int) -> int:
    if height <= 0 or total <= 0:
        return 0
    return max(0, min(offset, max(total - height, 0)))


def character_width(character: str) -> int:
    if unicodedata.combining(character):
        return 0
    return 2 if unicodedata.east_asian_width(character) in ("W", "F") else 1


def display_width(text: str) -> int:
    return sum(character_width(character) for character in text)


def fit_to_width(text: str, columns: int, ellipsis: bool = False) -> str:
    """Truncate on display columns so CJK text cannot overflow its pane.

    ``ellipsis`` marks real truncation with a trailing "…" so cut text is never
    mistaken for the whole value.
    """
    if columns <= 0:
        return ""
    if display_width(text) <= columns:
        return text
    budget = columns - 1 if ellipsis and columns > 1 else columns
    kept: list[str] = []
    used = 0
    for character in text:
        width = character_width(character)
        if used + width > budget:
            break
        kept.append(character)
        used += width
    truncated = "".join(kept)
    if ellipsis and columns > 1:
        truncated += "…"
    return truncated


def pad_to_width(text: str, columns: int, ellipsis: bool = False) -> str:
    trimmed = fit_to_width(text, columns, ellipsis=ellipsis)
    return trimmed + " " * max(columns - display_width(trimmed), 0)


def elapsed_text(seconds: float) -> str:
    total = int(max(seconds, 0))
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m{total % 60:02d}s"
    return f"{total // 3600}h{(total % 3600) // 60:02d}m"


def condense_path(path: str, columns: int) -> str:
    """Right-anchor an overlong filesystem path: keep trailing segments, since the tail
    (repo/workspace name) usually matters more than the shared prefix a user already knows.
    """
    if display_width(path) <= columns:
        return path
    if columns <= 2:
        return fit_to_width(path, columns)
    parts = [segment for segment in path.split("/") if segment]
    budget = columns - 2  # room for the leading "…/"
    kept: list[str] = []
    used = 0
    for segment in reversed(parts):
        width = display_width(segment) + (1 if kept else 0)
        if used + width > budget:
            break
        kept.insert(0, segment)
        used += width
    if not kept:
        return "…" + _tail_to_width(path, max(columns - 1, 0))
    return "…/" + "/".join(kept)


def wrap_text(text: str, columns: int) -> list[str]:
    """Word-wrap ``text`` on display columns; blank lines are preserved as-is.

    A single "word" wider than the whole budget (a long path, a hash) is hard-broken
    rather than left to overflow, so nothing ever gets silently cut off.
    """
    if columns <= 0 or display_width(text) <= columns:
        return [text]
    wrapped: list[str] = []
    current = ""
    current_width = 0
    for word in text.split(" "):
        word_width = display_width(word)
        if word_width > columns:
            if current:
                wrapped.append(current)
                current, current_width = "", 0
            remainder = word
            while display_width(remainder) > columns:
                piece = fit_to_width(remainder, columns)
                wrapped.append(piece)
                remainder = remainder[len(piece):]
            current, current_width = remainder, display_width(remainder)
            continue
        candidate_width = current_width + (1 if current else 0) + word_width
        if candidate_width > columns:
            wrapped.append(current)
            current, current_width = word, word_width
        else:
            current = f"{current} {word}" if current else word
            current_width = candidate_width
    if current or not wrapped:
        wrapped.append(current)
    return wrapped


def markdown_heading(line: str) -> tuple[str, int]:
    """Split a ``#``-prefixed markdown line into (text, level); level 0 is body text."""
    stripped = line.lstrip("#")
    level = len(line) - len(stripped)
    if level == 0 or (stripped and not stripped.startswith(" ")):
        return line, 0
    return stripped.strip(), level


# -------------------------------------------------------------------- line editor


class LineEditor:
    """Terminal-free editable input line driven by ``get_wch`` values."""

    def __init__(self, text: str = "") -> None:
        self.text = text
        self.cursor = len(text)

    def handle(self, key: int | str | None) -> str:
        if key is None:
            return EDITOR_IGNORED
        if isinstance(key, str):
            return self._handle_character(key)
        return self._handle_code(key)

    def _handle_character(self, key: str) -> str:
        if key in ("\n", "\r"):
            return EDITOR_SUBMIT
        if key == "\x1b":
            return EDITOR_CANCEL
        if key in ("\x7f", "\b"):
            return self._backspace()
        if key == "\x15":  # Ctrl-U
            self.text = self.text[self.cursor:]
            self.cursor = 0
            return EDITOR_EDIT
        if key == "\x17":  # Ctrl-W
            return self._delete_word()
        if key == "\x01":  # Ctrl-A
            self.cursor = 0
            return EDITOR_EDIT
        if key == "\x05":  # Ctrl-E
            self.cursor = len(self.text)
            return EDITOR_EDIT
        if key.isprintable():
            self.text = self.text[:self.cursor] + key + self.text[self.cursor:]
            self.cursor += len(key)
            return EDITOR_EDIT
        return EDITOR_IGNORED

    def _handle_code(self, key: int) -> str:
        if key in (curses.KEY_ENTER, 10, 13):
            return EDITOR_SUBMIT
        if key in (curses.KEY_BACKSPACE, 127, 8):
            return self._backspace()
        if key == curses.KEY_DC:
            if self.cursor < len(self.text):
                self.text = self.text[:self.cursor] + self.text[self.cursor + 1:]
            return EDITOR_EDIT
        if key == curses.KEY_LEFT:
            self.cursor = max(self.cursor - 1, 0)
            return EDITOR_EDIT
        if key == curses.KEY_RIGHT:
            self.cursor = min(self.cursor + 1, len(self.text))
            return EDITOR_EDIT
        if key == curses.KEY_HOME:
            self.cursor = 0
            return EDITOR_EDIT
        if key == curses.KEY_END:
            self.cursor = len(self.text)
            return EDITOR_EDIT
        return EDITOR_IGNORED

    def _backspace(self) -> str:
        if self.cursor > 0:
            self.text = self.text[:self.cursor - 1] + self.text[self.cursor:]
            self.cursor -= 1
        return EDITOR_EDIT

    def _delete_word(self) -> str:
        head = self.text[:self.cursor].rstrip()
        cut = head.rfind(" ") + 1
        self.text = self.text[:cut] + self.text[self.cursor:]
        self.cursor = cut
        return EDITOR_EDIT


# ------------------------------------------------------------------ child process


class TaskAdmissionError(RuntimeError):
    pass


def build_task_command(workspace: Path, request: str) -> tuple[str, ...]:
    if not request.strip():
        raise ValueError("Task request cannot be empty.")
    return (
        sys.executable,
        "-m",
        "adaptive_orchestrator.cli",
        "run",
        "--workspace",
        str(workspace.resolve()),
        "--verbose",
        "--description",
        request,
        "--objective",
        request,
    )


class BackgroundTask:
    """One shell-free CLI child whose combined output is safe to poll from curses."""

    def __init__(self, workspace: Path, request: str, index: int = 1) -> None:
        self.request = request
        self.index = index
        self.command = build_task_command(workspace, request)
        self.started_at = time.monotonic()
        self.finished_at: float | None = None
        self._cancel_requested = False
        self._lines: deque[str] = deque(maxlen=MAX_TASK_OUTPUT_LINES)
        self._lock = threading.Lock()
        self._process = subprocess.Popen(
            self.command,
            cwd=workspace,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=os.environ.copy(),
            start_new_session=True,
        )
        self._reader = threading.Thread(target=self._read_output, daemon=True)
        self._reader.start()

    def _read_output(self) -> None:
        assert self._process.stdout is not None
        try:
            for line in self._process.stdout:
                with self._lock:
                    self._lines.append(line.rstrip())
        except (OSError, ValueError):  # stream closed while the child was torn down
            pass

    @property
    def running(self) -> bool:
        alive = self._process.poll() is None
        if not alive and self.finished_at is None:
            self.finished_at = time.monotonic()
        return alive

    @property
    def return_code(self) -> int | None:
        return self._process.poll()

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_requested

    @property
    def elapsed(self) -> float:
        end = self.finished_at if self.finished_at is not None else time.monotonic()
        return end - self.started_at

    @property
    def status_text(self) -> str:
        if self.running:
            return "cancelling" if self._cancel_requested else "running"
        code = self.return_code
        if code is None:
            return "unknown"
        if code < 0:
            return f"signal {-code}"
        return f"exit {code}"

    @property
    def label(self) -> str:
        return f"#{self.index} {self.request}"

    def output_lines(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._lines)

    def cancel(self, force: bool = False) -> bool:
        """SIGTERM the child's own process group; escalate to SIGKILL on repeat."""
        if not self.running:
            return False
        escalate = force or self._cancel_requested
        number = signal.SIGKILL if escalate else signal.SIGTERM
        self._cancel_requested = True
        try:
            os.killpg(os.getpgid(self._process.pid), number)
            return True
        except (ProcessLookupError, PermissionError, OSError):
            try:
                self._process.send_signal(number)
                return True
            except OSError:
                return False


class TaskManager:
    """Bounded pool of concurrent CLI children, newest last."""

    def __init__(
        self,
        limit: int = DEFAULT_TASK_LIMIT,
        factory: Callable[[Path, str, int], BackgroundTask] | None = None,
    ) -> None:
        if limit < 1:
            raise ValueError("Task limit must be at least 1.")
        self.limit = limit
        self._factory = factory or BackgroundTask
        self._tasks: list[BackgroundTask] = []
        self._counter = 0

    @property
    def tasks(self) -> tuple[BackgroundTask, ...]:
        return tuple(self._tasks)

    @property
    def running_count(self) -> int:
        return sum(1 for task in self._tasks if task.running)

    def can_start(self) -> bool:
        return self.running_count < self.limit

    def start(self, workspace: Path, request: str) -> BackgroundTask:
        if not self.can_start():
            raise TaskAdmissionError(f"{self.limit} tasks already running; cancel one first.")
        self._counter += 1
        task = self._factory(workspace, request, self._counter)
        self._tasks.append(task)
        return task

    def cancel_all(self, force: bool = False) -> int:
        return sum(1 for task in self._tasks if task.cancel(force))

    def clear_finished(self) -> int:
        keep = [task for task in self._tasks if task.running]
        removed = len(self._tasks) - len(keep)
        self._tasks = keep
        return removed


# -------------------------------------------------------------------------- theme


@dataclass
class Theme:
    """Status-to-attribute lookup that degrades to monochrome without color."""

    enabled: bool = False
    pairs: dict[str, int] = field(default_factory=dict)

    @classmethod
    def create(cls) -> "Theme":
        try:
            curses.start_color()
            curses.use_default_colors()
        except curses.error:
            return cls()
        if not curses.has_colors():
            return cls()
        definitions = (
            ("ok", curses.COLOR_GREEN),
            ("fail", curses.COLOR_RED),
            ("active", curses.COLOR_CYAN),
            ("idle", curses.COLOR_YELLOW),
            ("accent", curses.COLOR_MAGENTA),
        )
        pairs: dict[str, int] = {}
        for index, (name, color) in enumerate(definitions, start=1):
            try:
                curses.init_pair(index, color, -1)
            except curses.error:
                continue
            pairs[name] = curses.color_pair(index)
        return cls(enabled=bool(pairs), pairs=pairs)

    def attribute(self, name: str, fallback: int = 0) -> int:
        if not self.enabled:
            return fallback
        return self.pairs.get(name, fallback)

    def status(self, status: str) -> int:
        return self.attribute(status_category(status))


_MESSAGE_FALLBACK_ATTRIBUTE = {
    "info": curses.A_DIM,
    "ok": curses.A_BOLD,
    "warn": curses.A_BOLD,
    "error": curses.A_BOLD,
}
_MESSAGE_COLOR = {"ok": "ok", "warn": "idle", "error": "fail"}


# ---------------------------------------------------------------------- the screen


class OrchestratorTui:
    def __init__(
        self,
        workspace: Path,
        control_state_dir: Path | None = None,
        task_limit: int = DEFAULT_TASK_LIMIT,
    ) -> None:
        self.workspace = workspace.resolve()
        self.control_state_dir = resolve_control_state_directory(self.workspace, control_state_dir)
        self.executions_path = self.workspace / ".orchestrator" / "executions.jsonl"
        self.events_path = self.control_state_dir / "events.jsonl"
        self.store = ExecutionReportStore(self.executions_path)
        self.tasks = TaskManager(task_limit)
        self.theme = Theme()

        self.rows: tuple[DashboardRow, ...] = ()
        self.visible_rows: tuple[DashboardRow, ...] = ()
        self.filter_text = ""
        self.view = VIEW_DASHBOARD
        self.help_visible = False
        self.auto_refresh = True

        self.selected = 0
        self.list_offset = 0
        self.detail_offset = 0
        self.task_selected = 0
        self.task_offset = 0
        self.log_offset = 0
        self.log_follow = True

        self.message = "?:help  n:new task  /:filter  Tab:tasks  Enter:detail  q:quit"
        self._message_kind = "info"
        self.load_error = ""
        self._announced: set[int] = set()
        self._detail_key = ""
        self._signature: tuple = ()
        self._last_poll = 0.0

    def _set_message(self, text: str, kind: str = "info") -> None:
        self.message = text
        self._message_kind = kind

    # -- lifecycle ---------------------------------------------------------

    def run(self, screen: "curses.window") -> None:
        curses.curs_set(0)
        screen.keypad(True)
        screen.timeout(POLL_INTERVAL_MS)
        if hasattr(curses, "set_escdelay"):
            # Default is a full second, which makes Esc feel broken.
            curses.set_escdelay(ESCAPE_DELAY_MS)
        self.theme = Theme.create()
        self._refresh()
        while True:
            self._draw(screen)
            key = _read_key(screen)
            if key is not None and not self._handle_key(screen, key):
                return
            self._poll_tasks()
            self._maybe_auto_refresh()

    def _poll_tasks(self) -> None:
        for task in self.tasks.tasks:
            if task.running or task.index in self._announced:
                continue
            self._announced.add(task.index)
            kind = "ok" if task.status_text == "exit 0" else "error"
            self._set_message(f"Task #{task.index} finished ({task.status_text}).", kind)
            self._refresh()

    def _maybe_auto_refresh(self) -> None:
        if not self.auto_refresh:
            return
        now = time.monotonic()
        if now - self._last_poll < AUTO_REFRESH_SECONDS:
            return
        self._last_poll = now
        if self._source_signature() != self._signature:
            self._refresh()

    def _source_signature(self) -> tuple:
        signature: list[tuple] = []
        for path in (self.events_path, self.executions_path):
            try:
                stat = path.stat()
                signature.append((str(path), stat.st_mtime_ns, stat.st_size))
            except OSError:
                signature.append((str(path), 0, -1))
        return tuple(signature)

    def _refresh(self) -> None:
        self._signature = self._source_signature()
        self._last_poll = time.monotonic()
        try:
            events = JsonlEventStore(self.events_path).read()
            lifecycle_state = EventProjector().replay(events)
            event_order = tuple(dict.fromkeys(event.execution_id for event in events))
            self.rows = dashboard_rows(self.store.records(), lifecycle_state, event_order)
            self.load_error = ""
        except (EventLogError, LookupError, OSError, UnicodeError, ValueError) as exc:
            self.rows = ()
            self.load_error = f"Could not read execution history: {exc}"
            self._set_message(self.load_error, "error")
        self._apply_filter()

    def _apply_filter(self) -> None:
        self.visible_rows = filter_rows(self.rows, self.filter_text)
        self.selected = min(self.selected, max(len(self.visible_rows) - 1, 0))
        current = self.current_row
        key = current.execution_id if current is not None else ""
        if key != self._detail_key:
            self._detail_key = key
            self.detail_offset = 0

    @property
    def current_row(self) -> DashboardRow | None:
        if not self.visible_rows:
            return None
        index = min(self.selected, len(self.visible_rows) - 1)
        return self.visible_rows[index]

    @property
    def current_task(self) -> BackgroundTask | None:
        pool = self.tasks.tasks
        if not pool:
            return None
        return pool[min(self.task_selected, len(pool) - 1)]

    # -- input -------------------------------------------------------------

    def _handle_key(self, screen: "curses.window", key: int | str) -> bool:
        character = key if isinstance(key, str) else ""
        code = key if isinstance(key, int) else -1

        if code == curses.KEY_RESIZE:
            return True
        if self.help_visible:
            self.help_visible = False
            return True
        if character == "?":
            self.help_visible = True
            return True
        if character == "\x1b":
            return self._handle_escape()
        if character in ("q", "Q"):
            return self._handle_quit()
        if character == "\t" or code == 9:
            self.view = VIEW_TASKS if self.view in (VIEW_DASHBOARD, VIEW_DETAIL) else VIEW_DASHBOARD
            return True
        if character in ("r", "R"):
            self._refresh()
            self._set_message(f"Refreshed: {len(self.rows)} executions.")
            return True
        if character in ("n", "N"):
            self._compose(screen)
            return True
        if character == "/":
            self._prompt_filter(screen)
            return True
        if character in ("a", "A"):
            self.auto_refresh = not self.auto_refresh
            self._set_message(f"Auto-refresh {'on' if self.auto_refresh else 'off'}.")
            return True
        if character == "C":
            cancelled = self.tasks.cancel_all()
            self._set_message(f"Cancellation requested for {cancelled} task(s).", "warn" if cancelled else "info")
            return True
        if character == "x":
            removed = self.tasks.clear_finished()
            self.task_selected = min(self.task_selected, max(len(self.tasks.tasks) - 1, 0))
            self._set_message(f"Cleared {removed} finished task(s).")
            return True

        if self.view == VIEW_DASHBOARD:
            self._keys_dashboard(character, code)
        elif self.view == VIEW_DETAIL:
            self._keys_scroll(character, code, "detail_offset")
        elif self.view == VIEW_TASKS:
            self._keys_tasks(character, code)
        elif self.view == VIEW_LOGS:
            self._keys_logs(character, code)
        return True

    def _handle_escape(self) -> bool:
        if self.filter_text:
            self.filter_text = ""
            self._apply_filter()
            self._set_message("Filter cleared.")
        elif self.view == VIEW_DETAIL:
            self.view = VIEW_DASHBOARD
        elif self.view == VIEW_LOGS:
            self.view = VIEW_TASKS
        return True

    def _handle_quit(self) -> bool:
        if self.view == VIEW_DETAIL:
            self.view = VIEW_DASHBOARD
            return True
        if self.view == VIEW_LOGS:
            self.view = VIEW_TASKS
            return True
        if self.view == VIEW_TASKS:
            self.view = VIEW_DASHBOARD
            return True
        running = self.tasks.running_count
        if running:
            self._set_message(f"{running} task(s) still running; press C to cancel them first.", "warn")
            return True
        return False

    def _keys_dashboard(self, character: str, code: int) -> None:
        total = len(self.visible_rows)
        moved = _movement(character, code, self.selected, total)
        if moved is not None:
            self.selected = moved
            self._apply_filter()
            return
        if character in ("\n", "\r") or code in (curses.KEY_ENTER, 10, 13):
            if self.current_row is not None:
                self.view = VIEW_DETAIL
                self.detail_offset = 0

    def _keys_tasks(self, character: str, code: int) -> None:
        pool = self.tasks.tasks
        moved = _movement(character, code, self.task_selected, len(pool))
        if moved is not None:
            self.task_selected = moved
            return
        if character in ("\n", "\r", "l") or code in (curses.KEY_ENTER, 10, 13):
            if self.current_task is not None:
                self.view = VIEW_LOGS
                self.log_follow = True
                self.log_offset = 0
            return
        if character == "c":
            task = self.current_task
            if task is None or not task.running:
                self._set_message("No running task is selected.", "error")
                return
            escalated = task.cancel_requested
            task.cancel()
            self._set_message(
                f"SIGKILL sent to task #{task.index}." if escalated
                else f"SIGTERM sent to task #{task.index}; press c again to force.",
                "warn",
            )

    def _keys_logs(self, character: str, code: int) -> None:
        if character == "f":
            self.log_follow = not self.log_follow
            self._set_message(f"Log follow {'on' if self.log_follow else 'off'}.")
            return
        before = self.log_offset
        self._keys_scroll(character, code, "log_offset")
        if self.log_offset != before:
            self.log_follow = False

    def _keys_scroll(self, character: str, code: int, attribute: str) -> None:
        offset = getattr(self, attribute)
        if character == "j" or code == curses.KEY_DOWN:
            offset += 1
        elif character == "k" or code == curses.KEY_UP:
            offset -= 1
        elif code == curses.KEY_NPAGE or character == "\x04":
            offset += 10
        elif code == curses.KEY_PPAGE or character == "\x15":
            offset -= 10
        elif character == "g" or code == curses.KEY_HOME:
            offset = 0
        elif character == "G" or code == curses.KEY_END:
            offset = 1 << 30
        else:
            return
        setattr(self, attribute, max(offset, 0))

    # -- prompts -----------------------------------------------------------

    def _compose(self, screen: "curses.window") -> None:
        if not self.tasks.can_start():
            self._set_message(f"{self.tasks.limit} tasks already running; cancel one first.", "error")
            return
        request = self._prompt(screen, "Task request: ")
        if request is None:
            self._set_message("New task cancelled.")
            return
        request = request.strip()
        if not request:
            self._set_message("New task cancelled.")
            return
        try:
            task = self.tasks.start(self.workspace, request)
        except (OSError, ValueError, TaskAdmissionError) as exc:
            self._set_message(f"Could not start task: {exc}", "error")
            return
        self.view = VIEW_TASKS
        self.task_selected = len(self.tasks.tasks) - 1
        self._set_message(f"Task #{task.index} started. Enter opens its live log.", "ok")

    def _prompt_filter(self, screen: "curses.window") -> None:
        value = self._prompt(screen, "Filter: ", self.filter_text)
        if value is None:
            self._set_message("Filter unchanged.")
            return
        self.filter_text = value.strip()
        self.selected = 0
        self.list_offset = 0
        self._apply_filter()
        self._set_message(
            f"Filter '{self.filter_text}': {len(self.visible_rows)}/{len(self.rows)} executions."
            if self.filter_text else "Filter cleared."
        )

    def _prompt(self, screen: "curses.window", label: str, initial: str = "") -> str | None:
        """Own the input loop so the poll timeout cannot truncate typing."""
        editor = LineEditor(initial)
        curses.curs_set(1)
        try:
            while True:
                height, width = screen.getmaxyx()
                row = max(height - 1, 0)
                prefix = fit_to_width(label, max(width - 1, 1))
                budget = max(width - display_width(prefix) - 1, 1)
                shown = _tail_to_width(editor.text[:editor.cursor], budget)
                _safe_addstr(screen, row, 0, pad_to_width(prefix + shown, max(width - 1, 0)), width)
                cursor_x = min(display_width(prefix) + display_width(shown), max(width - 1, 0))
                try:
                    screen.move(row, cursor_x)
                except curses.error:
                    pass
                screen.refresh()
                key = _read_key(screen)
                if key is None:
                    self._poll_tasks()
                    continue
                if isinstance(key, int) and key == curses.KEY_RESIZE:
                    continue
                outcome = editor.handle(key)
                if outcome == EDITOR_SUBMIT:
                    return editor.text
                if outcome == EDITOR_CANCEL:
                    return None
        finally:
            curses.curs_set(0)

    # -- drawing -----------------------------------------------------------

    def _draw(self, screen: "curses.window") -> None:
        screen.erase()
        height, width = screen.getmaxyx()
        if height < 3 or width < 20:
            _safe_addstr(screen, 0, 0, "Terminal too small", width)
            screen.refresh()
            return
        self._draw_header(screen, height, width)
        body_top = 2
        body_height = max(height - body_top - 1, 1)
        if self.view == VIEW_DASHBOARD:
            self._draw_dashboard(screen, body_top, body_height, width)
        elif self.view == VIEW_DETAIL:
            self._draw_detail(screen, body_top, body_height, width)
        elif self.view == VIEW_TASKS:
            self._draw_tasks(screen, body_top, body_height, width)
        elif self.view == VIEW_LOGS:
            self._draw_logs(screen, body_top, body_height, width)
        if self.help_visible:
            self._draw_help(screen, height, width)
        fallback = _MESSAGE_FALLBACK_ATTRIBUTE.get(self._message_kind, curses.A_DIM)
        color_name = _MESSAGE_COLOR.get(self._message_kind)
        message_attribute = self.theme.attribute(color_name, fallback) if color_name else fallback
        _safe_addstr(screen, height - 1, 0, self.message, width, message_attribute)
        screen.refresh()

    def _draw_header(self, screen: "curses.window", height: int, width: int) -> None:
        prefix = "Adaptive Orchestrator — "
        indicators = (
            f"{self.view}  tasks {self.tasks.running_count}/{self.tasks.limit}"
            f"  auto {'on' if self.auto_refresh else 'off'}"
        )
        title_budget = max(width - display_width(indicators) - 2, 1)
        path_budget = max(title_budget - display_width(prefix), 1)
        title = prefix + condense_path(str(self.workspace), path_budget)
        _safe_addstr(screen, 0, 0, title, title_budget, curses.A_BOLD, ellipsis=False)
        _safe_addstr(
            screen, 0, max(width - display_width(indicators) - 1, 0), indicators, width,
            self.theme.attribute("accent"),
        )
        shown = len(self.visible_rows)
        meta = f"{shown}/{len(self.rows)} executions"
        if self.filter_text:
            meta += f"  filter:'{self.filter_text}'"
        if self.load_error:
            meta += "  [history unreadable]"
        _safe_addstr(screen, 1, 0, meta, width, curses.A_DIM)

    def _draw_dashboard(self, screen: "curses.window", top: int, body_height: int, width: int) -> None:
        list_width = max(min(width // 2, 72), 24)
        divider_x = min(list_width, max(width - 1, 0))
        for offset in range(body_height):
            _safe_addstr(screen, top + offset, divider_x, "│", 2, curses.A_DIM, ellipsis=False)

        header = _DASHBOARD_ROW_FORMAT.format(
            marker=" ", glyph=" ", status="STATUS", agent="AGENT", description="DESCRIPTION",
        )
        _safe_addstr(screen, top, 0, pad_to_width(header, list_width - 1), list_width, curses.A_BOLD)
        list_top = top + 1
        list_height = max(body_height - 1, 0)
        self.list_offset = scroll_offset(self.list_offset, self.selected, len(self.visible_rows), list_height)
        window = self.visible_rows[self.list_offset:self.list_offset + list_height]
        for index, row in enumerate(window):
            absolute = self.list_offset + index
            chosen = absolute == self.selected
            marker = ">" if chosen else " "
            glyph = _STATUS_GLYPH.get(status_category(row.status), " ")
            text = _DASHBOARD_ROW_FORMAT.format(
                marker=marker,
                glyph=glyph,
                status=fit_to_width(row.status, 10),
                agent=fit_to_width(row.agent, 16),
                description=row.description,
            )
            attribute = self.theme.status(row.status)
            if chosen:
                attribute |= curses.A_REVERSE
            _safe_addstr(
                screen, list_top + index, 0, pad_to_width(text, list_width - 1, ellipsis=True), list_width, attribute,
            )

        detail_x = min(divider_x + 2, max(width - 1, 0))
        detail_width = max(width - detail_x, 1)
        wrap_budget = max(detail_width - 1, 1)
        wrapped: list[str] = []
        for line in self._summary_lines():
            wrapped.extend(wrap_text(line, wrap_budget))
        for offset, line in enumerate(wrapped[:body_height]):
            _safe_addstr(screen, top + offset, detail_x, line, detail_width)

    def _summary_lines(self) -> list[str]:
        row = self.current_row
        if row is None:
            if self.load_error:
                return [self.load_error]
            if self.rows:
                return ["No execution matches the current filter.", "Press Esc to clear it."]
            return ["No execution records yet.", "Press n to start a task."]
        lines: list[str] = []
        if row.attempts:
            lines.extend(render_text_summary(ExecutionBundle(row.execution_id, row.attempts)).splitlines())
        else:
            lines.extend([
                f"Execution: {row.execution_id}",
                f"Task: {row.description or '(missing description)'}",
                f"Status: {row.status}",
                f"Agent: {row.agent}",
                "(in flight; no terminal record yet)",
            ])
        lines.extend(["", f"Attempts tracked: {row.attempt_count}", "Enter: full report"])
        return lines

    def _draw_detail(self, screen: "curses.window", top: int, body_height: int, width: int) -> None:
        row = self.current_row
        if row is None:
            self.view = VIEW_DASHBOARD
            return
        wrap_budget = max(width - 1, 1)
        rendered: list[tuple[str, int]] = []
        for line in self._report_lines(row):
            text, level = markdown_heading(line)
            if level == 1:
                attribute = curses.A_BOLD | curses.A_UNDERLINE
            elif level >= 2:
                attribute = curses.A_BOLD | self.theme.attribute("accent")
            else:
                attribute = 0
            rendered.extend((piece, attribute) for piece in wrap_text(text, wrap_budget))
        self.detail_offset = clamp_offset(self.detail_offset, len(rendered), body_height)
        for index, (text, attribute) in enumerate(rendered[self.detail_offset:self.detail_offset + body_height]):
            _safe_addstr(screen, top + index, 0, text, width, attribute)

    def _report_lines(self, row: DashboardRow) -> list[str]:
        if not row.attempts:
            return self._summary_lines()
        try:
            return render_markdown_report(ExecutionBundle(row.execution_id, row.attempts)).splitlines()
        except (LookupError, TypeError, ValueError) as exc:
            return [f"Could not render report: {exc}", *self._summary_lines()]

    def _draw_tasks(self, screen: "curses.window", top: int, body_height: int, width: int) -> None:
        pool = self.tasks.tasks
        if not pool:
            _safe_addstr(screen, top, 0, "No tasks launched in this session. Press n to start one.", width)
            if self.rows:
                hint = f"{len(self.rows)} execution(s) on the dashboard — press Tab to view them."
                _safe_addstr(screen, top + 1, 0, hint, width, curses.A_DIM)
            return
        header = _TASK_ROW_FORMAT.format(
            marker=" ", spinner=" ", index="", status="STATUS", elapsed="ELAPSED", request="REQUEST",
        )
        _safe_addstr(screen, top, 0, pad_to_width(header, width - 1), width, curses.A_BOLD)
        list_top = top + 1
        list_height = max(min(len(pool), (body_height - 1) // 2), 1)
        self.task_offset = scroll_offset(self.task_offset, self.task_selected, len(pool), list_height)
        for index, task in enumerate(pool[self.task_offset:self.task_offset + list_height]):
            absolute = self.task_offset + index
            chosen = absolute == self.task_selected
            marker = ">" if chosen else " "
            spinner = _SPINNER_FRAMES[int(task.elapsed * 4) % len(_SPINNER_FRAMES)] if task.running else " "
            text = _TASK_ROW_FORMAT.format(
                marker=marker,
                spinner=spinner,
                index=task.index,
                status=task.status_text,
                elapsed=elapsed_text(task.elapsed),
                request=task.request,
            )
            attribute = self.theme.status("running" if task.running else _exit_status(task.return_code))
            if chosen:
                attribute |= curses.A_REVERSE
            _safe_addstr(screen, list_top + index, 0, pad_to_width(text, width - 1, ellipsis=True), width, attribute)

        preview_top = list_top + list_height + 1
        preview_height = max(top + body_height - preview_top, 0)
        task = self.current_task
        if task is None or preview_height <= 0:
            return
        _safe_addstr(screen, preview_top - 1, 0, f"— output of #{task.index} (Enter for full log) —", width, curses.A_DIM)
        for index, line in enumerate(task.output_lines()[-preview_height:]):
            _safe_addstr(screen, preview_top + index, 0, line, width)

    def _draw_logs(self, screen: "curses.window", top: int, body_height: int, width: int) -> None:
        task = self.current_task
        if task is None:
            self.view = VIEW_TASKS
            return
        lines = task.output_lines()
        header = (
            f"#{task.index} {task.status_text} {elapsed_text(task.elapsed)}"
            f"  {len(lines)} lines  follow:{'on' if self.log_follow else 'off'}  {task.request}"
        )
        _safe_addstr(screen, top, 0, header, width, curses.A_BOLD)
        window_top = top + 1
        window_height = max(top + body_height - window_top, 1)
        if self.log_follow:
            self.log_offset = max(len(lines) - window_height, 0)
        else:
            self.log_offset = clamp_offset(self.log_offset, len(lines), window_height)
        for index, line in enumerate(lines[self.log_offset:self.log_offset + window_height]):
            _safe_addstr(screen, window_top + index, 0, line, width)

    def _draw_help(self, screen: "curses.window", height: int, width: int) -> None:
        entries = (
            "Adaptive Orchestrator TUI",
            "",
            "n          compose and launch a new task (Esc cancels)",
            "/          filter executions; Esc clears the filter",
            "Tab        switch dashboard / tasks",
            "Enter      open execution report, or a task's live log",
            "j k ↑ ↓    move; PgUp PgDn g G scroll",
            "c          cancel selected task (again to SIGKILL)",
            "C          cancel every running task",
            "x          drop finished tasks from the list",
            "r          refresh now      a  toggle auto-refresh",
            "f          toggle log follow (log view)",
            "q / Esc    step back; q on the dashboard quits",
            "",
            "press any key to close",
        )
        box_height = min(len(entries) + 2, height)
        box_width = min(max(display_width(item) for item in entries) + 4, width)
        top = max((height - box_height) // 2, 0)
        left = max((width - box_width) // 2, 0)
        for index in range(box_height):
            _safe_addstr(screen, top + index, left, " " * box_width, box_width + 1, curses.A_REVERSE)
        for index, item in enumerate(entries[:max(box_height - 2, 0)]):
            _safe_addstr(screen, top + 1 + index, left + 2, item, box_width - 3, curses.A_REVERSE)


# ------------------------------------------------------------------------ helpers


def _read_key(screen: "curses.window") -> int | str | None:
    """``None`` means the poll timeout expired with no input."""
    try:
        value = screen.get_wch()
    except curses.error:
        return None
    if isinstance(value, (int, str)):
        return value
    return None


def _movement(character: str, code: int, current: int, total: int) -> int | None:
    if total <= 0:
        return None
    last = total - 1
    if character == "j" or code == curses.KEY_DOWN:
        return min(current + 1, last)
    if character == "k" or code == curses.KEY_UP:
        return max(current - 1, 0)
    if code == curses.KEY_NPAGE or character == "\x04":
        return min(current + 10, last)
    if code == curses.KEY_PPAGE or character == "\x15":
        return max(current - 10, 0)
    if character == "g" or code == curses.KEY_HOME:
        return 0
    if character == "G" or code == curses.KEY_END:
        return last
    return None


def _tail_to_width(text: str, columns: int) -> str:
    """Keep the end of ``text`` visible when it is wider than the prompt."""
    if display_width(text) <= columns:
        return text
    kept: list[str] = []
    used = 0
    for character in reversed(text):
        width = character_width(character)
        if used + width > columns:
            break
        kept.append(character)
        used += width
    return "".join(reversed(kept))


def _safe_addstr(
    screen: "curses.window", y: int, x: int, value: str, width: int, attributes: int = 0, ellipsis: bool = True,
) -> None:
    if y < 0 or x < 0 or width <= 0:
        return
    text = fit_to_width(value, max(width - 1, 0), ellipsis=ellipsis)
    if not text:
        return
    try:
        screen.addstr(y, x, text, attributes)
    except curses.error:
        pass


def _exit_status(code: int | None) -> str:
    if code == 0:
        return "completed"
    return "failed"


def _text(value: object, default: str) -> str:
    return value if isinstance(value, str) and value else default


def _lifecycle_status(status: str, outcome: object, terminal: object) -> str:
    outcome_map = outcome if isinstance(outcome, dict) else {}
    terminal_map = terminal if isinstance(terminal, dict) else {}
    if status == "finalized":
        return _text(outcome_map.get("execution_status") or outcome_map.get("status"), status)
    if status in {"terminal", "reconciled", "evaluated"}:
        return _text(terminal_map.get("status"), status)
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Full-screen local UI for Adaptive Orchestrator.")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--control-state-dir", type=Path, help="Protected lifecycle event directory.")
    parser.add_argument(
        "--max-tasks",
        type=int,
        default=DEFAULT_TASK_LIMIT,
        help=f"Concurrent CLI children the UI admits (default {DEFAULT_TASK_LIMIT}).",
    )
    args = parser.parse_args(argv)
    workspace = args.workspace.expanduser().resolve()
    if not workspace.is_dir():
        parser.error(f"workspace is not a directory: {workspace}")
    if args.max_tasks < 1:
        parser.error("--max-tasks must be at least 1")
    try:
        application = OrchestratorTui(workspace, args.control_state_dir, args.max_tasks)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        curses.wrapper(application.run)
    finally:
        # A normal quit already refuses to exit with tasks running; this covers
        # Ctrl-C and any unhandled exception in the draw/input loop, so a crash
        # can't leave a coding-agent child orphaned.
        application.tasks.cancel_all(force=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
