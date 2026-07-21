from __future__ import annotations

import argparse
import curses
import os
import signal
import subprocess
import sys
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from adaptive_orchestrator.infrastructure.events import EventLogError, JsonlEventStore
from adaptive_orchestrator.infrastructure.state_paths import resolve_control_state_directory
from adaptive_orchestrator.operations.reporting import ExecutionBundle, ExecutionReportStore, render_text_summary
from adaptive_orchestrator.routing.state import EventProjector, RoutingState


@dataclass(frozen=True, slots=True)
class DashboardRow:
    execution_id: str
    status: str
    agent: str
    verification: str
    description: str
    attempts: tuple[dict, ...]


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
        ))
    return tuple(rows)


class BackgroundTask:
    """One shell-free CLI child whose combined output is safe to poll from curses."""

    def __init__(self, workspace: Path, request: str) -> None:
        self.command = build_task_command(workspace, request)
        self._lines: deque[str] = deque(maxlen=500)
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
        for line in self._process.stdout:
            with self._lock:
                self._lines.append(line.rstrip())

    @property
    def running(self) -> bool:
        return self._process.poll() is None

    @property
    def return_code(self) -> int | None:
        return self._process.poll()

    def output_lines(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._lines)

    def cancel(self) -> None:
        if self.running:
            os.killpg(self._process.pid, signal.SIGTERM)


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


class OrchestratorTui:
    def __init__(self, workspace: Path, control_state_dir: Path | None = None) -> None:
        self.workspace = workspace.resolve()
        self.control_state_dir = resolve_control_state_directory(self.workspace, control_state_dir)
        self.store = ExecutionReportStore(self.workspace / ".orchestrator" / "executions.jsonl")
        self.rows: tuple[DashboardRow, ...] = ()
        self.selected = 0
        self.task: BackgroundTask | None = None
        self.message = "n:new  j/k or arrows:select  r:refresh  c:cancel  q:quit"

    def run(self, screen: curses.window) -> None:
        curses.curs_set(0)
        screen.keypad(True)
        screen.timeout(250)
        self._refresh()
        while True:
            self._draw(screen)
            key = screen.getch()
            if key in (ord("q"), ord("Q")):
                if self.task is not None and self.task.running:
                    self.message = "A task is running; cancel it before quitting."
                else:
                    return
            elif key in (ord("j"), curses.KEY_DOWN):
                self.selected = min(self.selected + 1, max(len(self.rows) - 1, 0))
            elif key in (ord("k"), curses.KEY_UP):
                self.selected = max(self.selected - 1, 0)
            elif key in (ord("r"), ord("R")):
                self._refresh()
            elif key in (ord("n"), ord("N")):
                self._compose(screen)
            elif key in (ord("c"), ord("C")) and self.task is not None and self.task.running:
                self.task.cancel()
                self.message = "Cancellation requested."
            if self.task is not None and not self.task.running:
                code = self.task.return_code
                self.message = f"Task finished with exit code {code}. Press r to refresh records."

    def _refresh(self) -> None:
        try:
            event_store = JsonlEventStore(self.control_state_dir / "events.jsonl")
            events = event_store.read()
            lifecycle_state = EventProjector().replay(events)
            event_order = tuple(dict.fromkeys(event.execution_id for event in events))
            self.rows = dashboard_rows(self.store.records(), lifecycle_state, event_order)
        except (EventLogError, OSError, UnicodeError, ValueError) as exc:
            self.rows = ()
            self.message = f"Could not read execution history: {exc}"
        self.selected = min(self.selected, max(len(self.rows) - 1, 0))

    def _compose(self, screen: curses.window) -> None:
        if self.task is not None and self.task.running:
            self.message = "Only one task can run at a time."
            return
        height, width = screen.getmaxyx()
        prompt = "Task request: "
        screen.move(height - 1, 0)
        screen.clrtoeol()
        _safe_addstr(screen, height - 1, 0, prompt, width)
        curses.echo()
        curses.curs_set(1)
        try:
            raw = screen.getstr(height - 1, len(prompt), max(width - len(prompt) - 1, 1))
            request = raw.decode("utf-8", errors="replace").strip()
        finally:
            curses.noecho()
            curses.curs_set(0)
        if not request:
            self.message = "New task cancelled."
            return
        try:
            self.task = BackgroundTask(self.workspace, request)
        except (OSError, ValueError) as exc:
            self.message = f"Could not start task: {exc}"
            return
        self.message = "Task started. Live child output is shown below."

    def _draw(self, screen: curses.window) -> None:
        screen.erase()
        height, width = screen.getmaxyx()
        _safe_addstr(screen, 0, 0, f"Adaptive Orchestrator — {self.workspace}", width, curses.A_BOLD)
        list_width = max(min(width // 2, 72), 28)
        body_bottom = max(height - 2, 2)
        for index, row in enumerate(self.rows[: max(body_bottom - 2, 0)]):
            marker = ">" if index == self.selected else " "
            text = f"{marker} {row.status:<10} {row.agent:<18} {row.description}"
            _safe_addstr(screen, index + 2, 0, text, list_width, curses.A_REVERSE if index == self.selected else 0)

        detail_x = min(list_width + 1, max(width - 1, 0))
        detail_width = max(width - detail_x, 1)
        detail_lines: list[str] = []
        if self.rows:
            row = self.rows[self.selected]
            detail_lines.extend(render_text_summary(ExecutionBundle(row.execution_id, row.attempts)).splitlines())
        else:
            detail_lines.append("No terminal execution records yet.")
        if self.task is not None:
            state = "running" if self.task.running else f"exit={self.task.return_code}"
            detail_lines.extend(["", f"Child process: {state}", *self.task.output_lines()[-max(height // 2, 3):]])
        for offset, line in enumerate(detail_lines[: max(body_bottom - 1, 0)], start=1):
            _safe_addstr(screen, offset, detail_x, line, detail_width)
        _safe_addstr(screen, height - 1, 0, self.message, width, curses.A_DIM)
        screen.refresh()


def _safe_addstr(screen: curses.window, y: int, x: int, value: str, width: int, attributes: int = 0) -> None:
    if y < 0 or x < 0 or width <= 0:
        return
    try:
        screen.addnstr(y, x, value, max(width - 1, 0), attributes)
    except curses.error:
        pass


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
    args = parser.parse_args(argv)
    workspace = args.workspace.expanduser().resolve()
    if not workspace.is_dir():
        parser.error(f"workspace is not a directory: {workspace}")
    try:
        application = OrchestratorTui(workspace, args.control_state_dir)
    except ValueError as exc:
        parser.error(str(exc))
    curses.wrapper(application.run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
