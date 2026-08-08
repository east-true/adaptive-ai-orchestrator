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

from adaptive_orchestrator.infrastructure.child_environment import ensure_child_import_path
from adaptive_orchestrator.infrastructure.events import EventLogError, JsonlEventStore
from adaptive_orchestrator.infrastructure.state_paths import resolve_control_state_directory
from adaptive_orchestrator.infrastructure.version import package_version
from adaptive_orchestrator.orchestration.kernel import KERNEL_VERSION
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

#: The installed console script for this interface (see ``[project.scripts]``).
TUI_PROGRAM_NAME = "adaptive-ai-orchestrator-tui"

#: Module path behind the documented ``python3 -m ...`` entry point.
TUI_MODULE_ENTRY_POINT = "adaptive_orchestrator.tui"

#: Basenames that mean "started as a module", not as the installed script.
_MODULE_INVOCATION_NAMES = frozenset({"tui.py", "__main__.py"})
MESSAGE_TTL_SECONDS = 4.0

VIEW_DASHBOARD = "dashboard"
VIEW_DETAIL = "detail"
VIEW_TASKS = "tasks"
VIEW_LOGS = "logs"

# Each view offers a different set of actions, so the hint bar names only
# what actually works on the screen currently showing — a dashboard hint left
# up while looking at a log was itself a source of "what can I do?" confusion.
VIEW_HINTS = {
    VIEW_DASHBOARD: "?:help  n:new task  /:filter  Enter:report  Tab:tasks  q:quit",
    VIEW_DETAIL: "?:help  j k:scroll  Esc:back  q:quit",
    VIEW_TASKS: "?:help  n:new task  Enter:log  c:cancel  x:clear finished  Tab:dashboard  q:quit",
    VIEW_LOGS: "?:help  f:toggle follow  j k:scroll  Esc:back  q:quit",
}

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
_TASK_ROW_FORMAT = "{marker}{spinner} #{index:<3} {exec_id:<9} {status:<11} {elapsed:>7}  {request}"
_DASHBOARD_MARKER_WIDTH = 2  # status glyph + one column of breathing room
_DASHBOARD_GAP_WIDTH = 2
_DASHBOARD_EXEC_ID_COL = "exec_id"
_DASHBOARD_ATTEMPTS_COL = "attempts"
_DASHBOARD_AGENT_COL = "agent"
_DASHBOARD_VERIFICATION_COL = "verification"
_DASHBOARD_TASK_ID_COL = "task_id"
_DASHBOARD_TASK_COL = "task"
_DASHBOARD_EXEC_ID_LENGTH = 8  # matches the short-prefix convention `show`/`retry`/`report` accept
# No STATUS column: the marker glyph already shows ok/fail/active/idle at a
# glance (in color, once selected), so a text column repeating it would just
# say the same thing twice — the exact status string is one Enter away.
_DASHBOARD_HEADER_LABELS = {
    _DASHBOARD_EXEC_ID_COL: "ID",
    _DASHBOARD_TASK_ID_COL: "TASK ID",
    _DASHBOARD_ATTEMPTS_COL: "ATTEMPTS",
    _DASHBOARD_AGENT_COL: "AGENT",
    _DASHBOARD_VERIFICATION_COL: "VERIFICATION",
}
_DASHBOARD_FIXED_COLUMNS = (
    (_DASHBOARD_EXEC_ID_COL, _DASHBOARD_EXEC_ID_LENGTH, _DASHBOARD_EXEC_ID_LENGTH),
    (_DASHBOARD_TASK_ID_COL, 18, 10),
    (_DASHBOARD_ATTEMPTS_COL, 8, 5),
    (_DASHBOARD_AGENT_COL, 16, 10),
    (_DASHBOARD_VERIFICATION_COL, 12, 8),
)
_DASHBOARD_TASK_MIN_WIDTH = 16


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


def _box_border(width: int, left_corner: str, right_corner: str) -> str:
    """One plain border line of a bordered box."""
    return f"{left_corner}{'─' * max(width - 2, 0)}{right_corner}"


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


def _summary_field(line: str) -> tuple[str, str] | None:
    """Split a "Label: value" summary line for grid rendering.

    Returns ``None`` for blank separators and free-text hints, which are
    drawn as a single dim line instead of being forced into the grid.
    """
    label, separator, value = line.partition(": ")
    if not separator:
        return None
    return label, value


def _move_task_last(lines: list[str]) -> list[str]:
    """Put the (often long) task text after every quick-glance fact, not before them.

    Status/Agent/Model/Verification/etc. are what a glance at the summary
    panel is usually for; burying them below a multi-line task description
    meant they could scroll out of view before Task did.
    """
    task_index = next(
        (index for index, line in enumerate(lines) if (_summary_field(line) or (None, None))[0] == "Task"),
        None,
    )
    if task_index is None:
        return lines
    return lines[:task_index] + lines[task_index + 1:] + [lines[task_index]]


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
                if not piece:
                    # One character can be wider than the entire budget: a
                    # double-width CJK glyph in a one-column pane. Emitting it
                    # alone overflows by a column, which the renderer clips,
                    # whereas keeping it back would leave the remainder
                    # unchanged and loop forever.
                    piece = remainder[0]
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


def task_id_groups_rows(rows: Sequence[DashboardRow]) -> bool:
    """Whether any task id is shared by more than one row.

    That sharing is the only thing a task id says that the execution id does
    not: `workflow.run` mints one per run unless a caller supplied it, so
    outside paired experiments the two identify the same thing.
    """
    seen: set[str] = set()
    for row in rows:
        if not row.task_id:
            continue
        if row.task_id in seen:
            return True
        seen.add(row.task_id)
    return False


def _dashboard_layout(
    width: int, rows: Sequence[DashboardRow] = (),
) -> tuple[int, int, int, int, int, int]:
    """Compute column widths for the dashboard list from terminal width.

    ``exec_id`` is a fixed 8-character slice of the execution id — the value
    every follow-up CLI command (``show``/``retry``/``report``) actually
    takes — so it always gets its full width. The other fixed columns (Task
    ID, Attempts, Agent, Verification) shrink toward whatever is actually on
    screen before falling back to their preferred width. The variable-width
    ``TASK`` column receives whatever space is left over.
    """
    gaps = len(_DASHBOARD_FIXED_COLUMNS) * _DASHBOARD_GAP_WIDTH
    fixed_max = {name: pref for name, pref, _ in _DASHBOARD_FIXED_COLUMNS}
    fixed_min = {name: min_width for name, _, min_width in _DASHBOARD_FIXED_COLUMNS}
    available = width - _DASHBOARD_MARKER_WIDTH - gaps
    if available <= 0:
        return tuple([0] * len(_DASHBOARD_FIXED_COLUMNS)) + (max(available, 0),)

    if rows:
        visible_width = {
            _DASHBOARD_EXEC_ID_COL: _DASHBOARD_EXEC_ID_LENGTH,
            _DASHBOARD_TASK_ID_COL: max(display_width(row.task_id or "-") for row in rows),
            _DASHBOARD_ATTEMPTS_COL: max(len(str(row.attempt_count)) for row in rows),
            _DASHBOARD_AGENT_COL: max(display_width(row.agent) for row in rows),
            _DASHBOARD_VERIFICATION_COL: max(display_width(row.verification) for row in rows),
        }
        for name, pref, min_width in _DASHBOARD_FIXED_COLUMNS:
            header_width = display_width(_DASHBOARD_HEADER_LABELS[name])
            fixed_max[name] = max(min_width, min(max(header_width, visible_width[name]), pref))
        if not task_id_groups_rows(rows):
            # A task id the workflow generated per run is a second random
            # identifier standing 1:1 with the execution id, which is the one
            # follow-up commands take — a column of noise. It earns its width
            # only where it does something exec_id cannot: tie separate
            # executions of one task together, as paired runs do.
            fixed_max[_DASHBOARD_TASK_ID_COL] = 0

    # Keep TASK readable when possible, but still render something in very narrow
    # terminals by reserving at least one column for it.
    task_reserved = (
        _DASHBOARD_TASK_MIN_WIDTH
        if available > _DASHBOARD_TASK_MIN_WIDTH
        else available
    )
    fixed_budget = max(available - task_reserved, 0)

    # Shrink priority, least to most protected. TASK ID goes first: unlike
    # exec_id, it is only useful when a caller set one explicitly. exec_id is
    # last — it is the one column every follow-up command needs, so it gives
    # up width only once nothing else is left to give.
    order = (
        _DASHBOARD_TASK_ID_COL,
        _DASHBOARD_VERIFICATION_COL,
        _DASHBOARD_ATTEMPTS_COL,
        _DASHBOARD_AGENT_COL,
        _DASHBOARD_EXEC_ID_COL,
    )
    fixed_used = sum(fixed_max.values())
    while fixed_used > fixed_budget and any(
        fixed_max[col] > fixed_min[col] for col in fixed_max
    ):
        for name in order:
            if fixed_used <= fixed_budget:
                break
            if fixed_max[name] > fixed_min[name]:
                fixed_max[name] -= 1
                fixed_used -= 1
        if fixed_used <= fixed_budget:
            break

    while fixed_used > fixed_budget:
        for name in order:
            if fixed_used <= fixed_budget:
                break
            if fixed_max[name] > 0:
                fixed_max[name] -= 1
                fixed_used -= 1
        if fixed_used <= fixed_budget:
            break

    task_width = max(available - fixed_used, 0)
    return (
        fixed_max[_DASHBOARD_EXEC_ID_COL],
        fixed_max[_DASHBOARD_TASK_ID_COL],
        fixed_max[_DASHBOARD_ATTEMPTS_COL],
        fixed_max[_DASHBOARD_AGENT_COL],
        fixed_max[_DASHBOARD_VERIFICATION_COL],
        task_width,
    )


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
    # No ``--agent``: this screen starts a run, it does not configure one. The
    # workspace profile decides, and the CLI and interactive shell remain the
    # places that override it.
    return (
        sys.executable,
        "-m",
        "adaptive_orchestrator.cli",
        "run",
        "--workspace",
        str(workspace.resolve()),
        "--verbose",
        "--summary",
        "--description",
        request,
        "--objective",
        request,
    )


def _execution_id_from(line: str) -> str:
    """Read the execution id out of ``--summary``'s first line.

    ``run --summary`` opens with ``Execution: <id>``, so the id arrives in the
    output the task is already streaming and needs no second lookup. Anything
    that does not match leaves the id unset rather than guessing.
    """
    prefix = "Execution: "
    if not line.startswith(prefix):
        return ""
    candidate = line[len(prefix):].strip()
    return candidate if candidate and " " not in candidate else ""


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
        self._execution_id = ""
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
                text = line.rstrip()
                with self._lock:
                    self._lines.append(text)
                    if not self._execution_id:
                        self._execution_id = _execution_id_from(text)
        except (OSError, ValueError):  # stream closed while the child was torn down
            pass

    @property
    def execution_id(self) -> str:
        """The run's recorded id, once its output has named it.

        This is the value ``show``, ``retry``, and ``report`` take. Without it
        a finished task is a session-local ``#N`` with no way back to what it
        recorded, which is the whole point of the run.
        """
        with self._lock:
            return self._execution_id

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

        self.message = ""
        self._message_kind = "info"
        self._message_set_at = 0.0
        self.load_error = ""
        self._announced: set[int] = set()
        self._detail_key = ""
        self._signature: tuple = ()
        self._last_poll = 0.0

    def _set_message(self, text: str, kind: str = "info") -> None:
        self.message = text
        self._message_kind = kind
        self._message_set_at = time.monotonic()

    def _status_line(self) -> tuple[str, str]:
        """What the bottom bar shows right now: a fresh notification if there
        is one, else a standing history-read error, else the current view's
        own hint — computed live so switching views updates it immediately
        instead of waiting out a stale notification's own fade timer.
        """
        if self.message and time.monotonic() - self._message_set_at < MESSAGE_TTL_SECONDS:
            return self.message, self._message_kind
        if self.load_error:
            return self.load_error, "error"
        return VIEW_HINTS.get(self.view, VIEW_HINTS[VIEW_DASHBOARD]), "info"

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
        # Open on the dashboard: this is a monitor over recorded executions,
        # so the first screen is the record. Starting a run is one 'n' away
        # and returns here by way of the task list.
        self.view = VIEW_DASHBOARD
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
            # Watching this exact task's log is the one moment "it's done, now
            # what?" is a real question: nothing else on screen is about to
            # change, and the hint line in the log view can be off-screen too.
            hint = "  Press Esc to go back." if self.view == VIEW_LOGS and self.current_task is task else ""
            self._set_message(f"Task #{task.index} finished ({task.status_text}).{hint}", kind)
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
            self._prompt_task(screen)
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
        """Esc is the only "step back" key, so it alone owns every view's back edge."""
        if self.filter_text:
            self.filter_text = ""
            self._apply_filter()
            self._set_message("Filter cleared.")
        elif self.view == VIEW_DETAIL:
            self.view = VIEW_DASHBOARD
        elif self.view == VIEW_LOGS:
            self.view = VIEW_TASKS
        elif self.view == VIEW_TASKS:
            self.view = VIEW_DASHBOARD
        return True

    def _handle_quit(self) -> bool:
        """q always means quit, from any view, never "step back" — Esc owns that."""
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

    def _prompt_task(self, screen: "curses.window") -> None:
        """Ask for one request, start it, and go watch it in the task list.

        Starting a run is a single modal question, not a screen of its own:
        the agents are invoked non-interactively (``claude --print``, ``codex
        exec``), so there is no conversation to hold here. What follows a
        submitted request is a recorded execution, and the task list is where
        that is visible — so that is where this lands.
        """
        request = self._prompt(screen, "New task: ")
        if request is None or not request.strip():
            self._set_message("New task cancelled.")
            return
        if not self.tasks.can_start():
            self._set_message(f"{self.tasks.limit} tasks already running; cancel one first.", "error")
            return
        try:
            task = self.tasks.start(self.workspace, request.strip())
        except (OSError, ValueError, TaskAdmissionError) as exc:
            self._set_message(f"Could not start task: {exc}", "error")
            return
        self.view = VIEW_TASKS
        self.task_selected = self.tasks.tasks.index(task)
        self._set_message(f"Task #{task.index} started.", "ok")

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
        """Own the input loop so the poll timeout cannot truncate typing.

        Background tasks keep being polled while this blocks, so a run started
        earlier goes on collecting output behind the prompt.
        """
        editor = LineEditor(initial)
        curses.curs_set(1)
        try:
            while True:
                cursor = self._draw_input_line(screen, label, editor)
                try:
                    screen.move(*cursor)
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

    def _draw_input_line(self, screen: "curses.window", label: str, editor: LineEditor) -> tuple[int, int]:
        """The original one-line "Label: text" prompt, still used for the filter."""
        height, width = screen.getmaxyx()
        row = max(height - 1, 0)
        prefix = fit_to_width(label, max(width - 1, 1))
        budget = max(width - display_width(prefix) - 1, 1)
        shown, caret_offset = _cursor_window(editor.text, editor.cursor, budget)
        _safe_addstr(screen, row, 0, pad_to_width(prefix + shown, max(width - 1, 0)), width)
        cursor_x = min(display_width(prefix) + caret_offset, max(width - 1, 0))
        return row, cursor_x

    # -- drawing -----------------------------------------------------------

    def _draw(self, screen: "curses.window") -> None:
        screen.erase()
        height, width = screen.getmaxyx()
        if height < 3 or width < 20:
            _safe_addstr(screen, 0, 0, "Terminal too small", width)
            screen.refresh()
            return
        self._draw_header(screen, height, width)
        body_top = 2  # leave row 1 blank so the body doesn't crowd the header
        body_height = max(height - body_top - 1, 1)
        cursor: tuple[int, int] | None = None
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
        # "running:N/M" is how many background launches from *this session*
        # are active out of the concurrency limit — unrelated to the "X/Y
        # executions" count in the header, which is the dashboard's
        # historical row count, and unrelated to the TASK column, which
        # names one row's request. It earns a permanent spot in the footer
        # because it is the one thing not otherwise visible from every other
        # view (e.g. while composing a new task with one already running).
        # The view name and the auto-refresh toggle didn't clear that bar —
        # the screen's own content already says which view you're on, and
        # 'a' already confirms the toggle in the message bar when pressed.
        indicators = f"running:{self.tasks.running_count}/{self.tasks.limit}"
        status_text, status_kind = self._status_line()
        fallback = _MESSAGE_FALLBACK_ATTRIBUTE.get(status_kind, curses.A_DIM)
        color_name = _MESSAGE_COLOR.get(status_kind)
        message_attribute = self.theme.attribute(color_name, fallback) if color_name else fallback
        status_budget = max(width - display_width(indicators) - 2, 1)
        _safe_addstr(screen, height - 1, 0, status_text, status_budget, message_attribute)
        _safe_addstr(
            screen, height - 1, max(width - display_width(indicators) - 1, 0), indicators, width,
            self.theme.attribute("accent"),
        )
        try:
            curses.curs_set(1 if cursor is not None else 0)
        except curses.error:
            pass
        if cursor is not None:
            try:
                screen.move(*cursor)
            except curses.error:
                pass
        screen.refresh()

    def _draw_header(self, screen: "curses.window", height: int, width: int) -> None:
        prefix = "Adaptive Orchestrator — "
        shown = len(self.visible_rows)
        meta = f"{shown}/{len(self.rows)} executions"
        if self.filter_text:
            meta += f"  filter:'{self.filter_text}'"
        if self.load_error:
            meta += "  [history unreadable]"
        title_budget = max(width - display_width(meta) - 2, 1)
        path_budget = max(title_budget - display_width(prefix), 1)
        title = prefix + condense_path(str(self.workspace), path_budget)
        _safe_addstr(screen, 0, 0, title, title_budget, curses.A_BOLD, ellipsis=False)
        _safe_addstr(screen, 0, max(width - display_width(meta) - 1, 0), meta, width, curses.A_DIM)

    def _draw_dashboard(self, screen: "curses.window", top: int, body_height: int, width: int) -> None:
        list_width = max(width, 1)
        exec_id_width, task_id_width, attempts_width, agent_width, verification_width, task_width = (
            _dashboard_layout(width, self.visible_rows)
        )

        def format_cell(value: str, columns: int, align_right: bool = False) -> str:
            text = fit_to_width(value, columns, ellipsis=True)
            padding = max(columns - display_width(text), 0)
            if align_right:
                return " " * padding + text
            return text + " " * padding

        cell_gap = " " * _DASHBOARD_GAP_WIDTH

        def join_cells(values: Sequence[str]) -> str:
            # A column squeezed to zero contributes no gap either, or the row
            # would carry a double-width space where nothing is drawn.
            return cell_gap.join(value for value in values if value)

        marker = " " * _DASHBOARD_MARKER_WIDTH
        header = marker + join_cells((
            pad_to_width(_DASHBOARD_HEADER_LABELS[_DASHBOARD_EXEC_ID_COL], exec_id_width, ellipsis=False),
            pad_to_width(_DASHBOARD_HEADER_LABELS[_DASHBOARD_TASK_ID_COL], task_id_width, ellipsis=False),
            pad_to_width(_DASHBOARD_HEADER_LABELS[_DASHBOARD_ATTEMPTS_COL], attempts_width, ellipsis=False),
            pad_to_width(_DASHBOARD_HEADER_LABELS[_DASHBOARD_AGENT_COL], agent_width, ellipsis=False),
            pad_to_width(_DASHBOARD_HEADER_LABELS[_DASHBOARD_VERIFICATION_COL], verification_width, ellipsis=False),
            pad_to_width("TASK", task_width, ellipsis=False),
        ))
        _safe_addstr(screen, top, 0, pad_to_width(header, list_width), list_width, curses.A_BOLD, ellipsis=False)

        list_top = top + 1
        list_height = max(body_height - 1, 0)
        if not self.visible_rows and list_height > 0:
            # An empty table under a header reads as "broken", and a filter that
            # matches nothing looks identical to having no data at all.
            for offset, line in enumerate(self._dashboard_empty_lines()):
                if offset >= list_height:
                    break
                _safe_addstr(screen, list_top + offset, 0, line, list_width, curses.A_DIM)
        else:
            self.list_offset = scroll_offset(self.list_offset, self.selected, len(self.visible_rows), list_height)
            window = self.visible_rows[self.list_offset:self.list_offset + list_height]
            for index, row in enumerate(window):
                absolute = self.list_offset + index
                chosen = absolute == self.selected
                # No ">" marker: the whole row already goes reverse-video when
                # selected, so a leading marker glyph on top of that would
                # just say the same thing twice.
                marker = " " * _DASHBOARD_MARKER_WIDTH
                glyph = _STATUS_GLYPH.get(status_category(row.status), " ")
                row_attribute = curses.A_REVERSE if chosen else 0
                task_id = row.task_id or "-"
                exec_id = row.execution_id[:_DASHBOARD_EXEC_ID_LENGTH]
                text = marker + join_cells((
                    pad_to_width(exec_id, exec_id_width, ellipsis=False),
                    pad_to_width(task_id, task_id_width, ellipsis=False),
                    format_cell(str(row.attempt_count), attempts_width, align_right=True),
                    pad_to_width(row.agent, agent_width, ellipsis=True),
                    pad_to_width(row.verification, verification_width, ellipsis=True),
                    pad_to_width(row.description, task_width, ellipsis=True),
                ))
                full_line = pad_to_width(text, list_width, ellipsis=True)
                _safe_addstr(screen, list_top + index, 0, full_line, list_width, row_attribute)
                if list_width >= 1:
                    marker_attribute = self.theme.status(row.status) if not chosen else row_attribute
                    _safe_addstr(screen, list_top + index, 0, glyph, 1, marker_attribute)

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
                f"Status: {row.status}",
                f"Agent: {row.agent}",
                "(in flight; no terminal record yet)",
                f"Task: {row.description or '(missing description)'}",
            ])
        return _move_task_last(lines)

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

    def _dashboard_empty_lines(self) -> tuple[str, ...]:
        """Explain an empty execution list, distinguishing no data from no match."""
        if self.rows and self.filter_text:
            return (
                f"No execution matches {self.filter_text!r}.",
                f"{len(self.rows)} hidden by the filter — press / to change it, Esc to clear.",
            )
        return (
            "No executions recorded in this workspace yet.",
            "Press n to run a task, or q to quit.",
        )

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
            marker=" ", spinner=" ", index="", exec_id="ID", status="STATUS", elapsed="ELAPSED", request="REQUEST",
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
            # The same 8-character prefix the dashboard shows and the CLI
            # accepts, so a row here can be carried straight to `show`. A dash
            # until the run names it, rather than a blank that reads as a
            # rendering gap.
            execution_id = task.execution_id
            text = _TASK_ROW_FORMAT.format(
                marker=marker,
                spinner=spinner,
                index=task.index,
                exec_id=execution_id[:_DASHBOARD_EXEC_ID_LENGTH] if execution_id else "—",
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
        # The full id, not the 8-character prefix: this is the line to copy
        # when following the run into `show` or `report`.
        reference = f"#{task.index}" + (f" · {task.execution_id}" if task.execution_id else "")
        _safe_addstr(screen, preview_top - 1, 0, f"— output of {reference} (Enter for full log) —", width, curses.A_DIM)
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
        # A raw log dump doesn't look like the rest of the UI, and the bottom
        # message bar gets overwritten by later refreshes — so the way back
        # needs to stay on screen for as long as this view is up, especially
        # right after a task finishes and there is nothing left to watch.
        _safe_addstr(screen, top + 1, 0, "Esc: back to tasks   f: toggle follow", width, curses.A_DIM)
        window_top = top + 2
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
            "Navigate",
            "  j k / ↑ ↓   move selection",
            "  PgUp PgDn   scroll a page; g G jump to top/bottom",
            "  Tab         switch dashboard / tasks",
            "  Enter       open execution report, or a task's live log",
            "  Esc         step back / clear filter",
            "",
            "Act",
            "  n           start a task (one line; Esc cancels)",
            "  /           filter executions",
            "  c           cancel selected task (again to SIGKILL)",
            "  C           cancel every running task",
            "  x           drop finished tasks from the list",
            "",
            "View",
            "  r           refresh now",
            "  a           toggle auto-refresh",
            "  f           toggle log follow (log view)",
            "",
            "q             quit (from any view; asks first if a task is running)",
            "",
            "press any key to close",
        )
        box_height = min(len(entries) + 2, height)
        box_width = min(max(display_width(item) for item in entries) + 4, width)
        top = max((height - box_height) // 2, 0)
        left = max((width - box_width) // 2, 0)
        for index in range(box_height):
            _safe_addstr(screen, top + index, left, " " * box_width, box_width + 1, curses.A_REVERSE)
        visible = list(entries[:max(box_height - 2, 0)])
        if len(visible) < len(entries) and visible:
            # A short terminal used to drop the remaining bindings silently, so
            # the overlay looked like the complete list of what the UI can do.
            visible[-1] = f"… {len(entries) - len(visible) + 1} more; enlarge the terminal"
        for index, item in enumerate(visible):
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


def _cursor_window(text: str, cursor: int, columns: int) -> tuple[str, int]:
    """Slice ``text`` to a ``columns``-wide window holding the cursor, and say
    how far into that window the cursor sits.

    Only the window's left edge scrolls, so whatever follows the cursor stays
    on screen. Showing just ``text[:cursor]`` would keep the caret visible too,
    but moving back into a long request to fix a word would blank out the rest
    of it, and an editor whose contents vanish while being edited reads as
    having lost them.
    """
    if columns <= 0:
        return "", 0
    # One column is held back so the caret has a cell of its own once it is
    # pushed to the right edge; otherwise it lands on top of the border.
    limit = max(columns - 1, 0)
    used = 0
    start = cursor
    for index in range(cursor - 1, -1, -1):
        width = character_width(text[index])
        if used + width > limit:
            break
        used += width
        start = index
    return fit_to_width(text[start:], columns), used


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
    text = fit_to_width(value, width, ellipsis=ellipsis)
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


def resolve_tui_program_name() -> str:
    """Name this UI the way the caller reached it, as the CLI already does.

    argparse defaults to ``tui.py``, which is neither of the two documented
    invocations: the installed console script, and
    ``python3 -m adaptive_orchestrator.tui`` through the compatibility shim.
    """

    if Path(sys.argv[0]).name in _MODULE_INVOCATION_NAMES:
        return f"{Path(sys.executable).name} -m {TUI_MODULE_ENTRY_POINT}"
    return TUI_PROGRAM_NAME


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=resolve_tui_program_name(),
        description="Full-screen local UI for Adaptive Orchestrator.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{TUI_PROGRAM_NAME} {package_version()} (kernel {KERNEL_VERSION})",
    )
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--control-state-dir", type=Path, help="Protected lifecycle event directory.")
    parser.add_argument(
        "--max-tasks",
        type=int,
        default=DEFAULT_TASK_LIMIT,
        help=f"Concurrent CLI children the UI admits (default {DEFAULT_TASK_LIMIT}).",
    )
    args = parser.parse_args(argv)
    # Every task is a child started in the workspace; fix the import roots once,
    # here, so each of them inherits a value that does not depend on where the
    # UI happened to be launched from.
    ensure_child_import_path()
    try:
        workspace = args.workspace.expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        # A workspace that cannot be resolved is a bad option value, and saying
        # so beats a traceback from a UI that never got to draw anything.
        parser.error(f"could not resolve --workspace {args.workspace}: {exc}")
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
