from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import curses

from adaptive_orchestrator.interfaces.tui import (
    EDITOR_CANCEL,
    EDITOR_EDIT,
    EDITOR_IGNORED,
    EDITOR_SUBMIT,
    LineEditor,
    TaskAdmissionError,
    TaskManager,
    build_task_command,
    clamp_offset,
    dashboard_rows,
    display_width,
    elapsed_text,
    filter_rows,
    fit_to_width,
    scroll_offset,
    status_category,
)
from adaptive_orchestrator.infrastructure.events import LifecycleEvent, LifecycleEventType
from adaptive_orchestrator.routing.state import EventProjector


class DashboardRowsTests(unittest.TestCase):
    def test_groups_attempts_and_shows_newest_execution_first(self) -> None:
        records = [
            {
                "execution_id": "exec-1",
                "attempt_id": "attempt-1",
                "agent_id": "codex",
                "status": "failed",
                "task": {"description": "First task"},
            },
            {
                "execution_id": "exec-1",
                "attempt_id": "attempt-2",
                "parent_attempt_id": "attempt-1",
                "agent_id": "claude-code",
                "status": "completed",
                "task": {"description": "First task"},
            },
            {
                "execution_id": "exec-2",
                "attempt_id": "attempt-3",
                "agent_id": "codex",
                "status": "completed",
                "verification": {"status": "passed"},
                "task": {"description": "Second task"},
            },
        ]
        rows = dashboard_rows(records)
        self.assertEqual([row.execution_id for row in rows], ["exec-2", "exec-1"])
        self.assertEqual(len(rows[1].attempts), 2)
        self.assertEqual(rows[0].verification, "passed")

    def test_task_id_comes_from_the_record_when_no_lifecycle_exists(self) -> None:
        rows = dashboard_rows([{
            "execution_id": "exec-1",
            "task_id": "task-7",
            "status": "completed",
            "task": {"task_id": "task-7", "description": "Fix the parser"},
        }])
        self.assertEqual(rows[0].task_id, "task-7")
        self.assertEqual([row.execution_id for row in filter_rows(rows, "task-7")], ["exec-1"])

    def test_legacy_rows_remain_individually_addressable(self) -> None:
        rows = dashboard_rows([{"status": "completed"}, {"status": "failed"}])
        self.assertEqual([row.execution_id for row in rows], ["legacy-2", "legacy-1"])

    def test_includes_started_lifecycle_execution_before_terminal_record_exists(self) -> None:
        selection = LifecycleEvent(
            LifecycleEventType.SELECTION_MADE,
            "exec-live",
            1,
            "task-live",
            "attempt-live",
            payload={
                "selected_agent": "codex",
                "eligible_candidates": ["codex"],
                "ineligible_reasons": {},
                "candidate_probabilities": {"codex": 1.0},
                "selected_probability": 1.0,
            },
        )
        started = LifecycleEvent(
            LifecycleEventType.EXECUTION_STARTED,
            "exec-live",
            2,
            "task-live",
            "attempt-live",
            payload={"agent_id": "codex"},
        )
        state = EventProjector().replay((selection, started))
        rows = dashboard_rows((), state, ("exec-live",))
        self.assertEqual(rows[0].status, "started")
        self.assertEqual(rows[0].agent, "codex")
        self.assertIn("task-live", rows[0].description)


class BuildTaskCommandTests(unittest.TestCase):
    def test_builds_shell_free_verbose_cli_command(self) -> None:
        command = build_task_command(Path("/workspace"), "Run the tests")
        self.assertEqual(command[0], sys.executable)
        self.assertIn("adaptive_orchestrator.cli", command)
        self.assertIn("--verbose", command)
        self.assertEqual(command.count("Run the tests"), 2)

    def test_rejects_empty_request(self) -> None:
        with self.assertRaises(ValueError):
            build_task_command(Path("/workspace"), "  ")


def _row(execution_id: str, status: str, agent: str, description: str) -> object:
    return dashboard_rows([{
        "execution_id": execution_id,
        "agent_id": agent,
        "status": status,
        "task": {"description": description},
    }])[0]


class FilterRowsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = (
            _row("exec-1", "completed", "codex", "Fix the parser"),
            _row("exec-2", "failed", "claude-code", "Add regression tests"),
        )

    def test_blank_query_keeps_every_row(self) -> None:
        self.assertEqual(filter_rows(self.rows, "   "), self.rows)

    def test_terms_match_case_insensitively_across_fields(self) -> None:
        self.assertEqual([row.execution_id for row in filter_rows(self.rows, "CODEX")], ["exec-1"])
        self.assertEqual([row.execution_id for row in filter_rows(self.rows, "failed")], ["exec-2"])

    def test_multiple_terms_are_conjunctive(self) -> None:
        self.assertEqual([row.execution_id for row in filter_rows(self.rows, "codex parser")], ["exec-1"])
        self.assertEqual(filter_rows(self.rows, "codex tests"), ())


class ScrollTests(unittest.TestCase):
    def test_offset_follows_selection_below_the_window(self) -> None:
        self.assertEqual(scroll_offset(0, 12, 40, 10), 3)

    def test_offset_follows_selection_above_the_window(self) -> None:
        self.assertEqual(scroll_offset(20, 4, 40, 10), 4)

    def test_visible_selection_does_not_move_the_window(self) -> None:
        self.assertEqual(scroll_offset(5, 9, 40, 10), 5)

    def test_offset_never_scrolls_past_the_final_page(self) -> None:
        self.assertEqual(scroll_offset(35, 39, 40, 10), 30)
        self.assertEqual(clamp_offset(999, 40, 10), 30)

    def test_degenerate_sizes_collapse_to_zero(self) -> None:
        self.assertEqual(scroll_offset(4, 0, 0, 10), 0)
        self.assertEqual(scroll_offset(4, 2, 40, 0), 0)
        self.assertEqual(clamp_offset(4, 3, 10), 0)


class WidthTests(unittest.TestCase):
    def test_wide_characters_count_two_columns(self) -> None:
        self.assertEqual(display_width("한글"), 4)
        self.assertEqual(display_width("ab"), 2)

    def test_truncation_never_exceeds_the_column_budget(self) -> None:
        self.assertEqual(fit_to_width("한글abc", 5), "한글a")
        self.assertEqual(display_width(fit_to_width("한글abc", 3)), 2)
        self.assertEqual(fit_to_width("anything", 0), "")

    def test_short_text_is_returned_unchanged(self) -> None:
        self.assertEqual(fit_to_width("abc", 10), "abc")


class LineEditorTests(unittest.TestCase):
    def test_types_unicode_and_submits(self) -> None:
        editor = LineEditor()
        for character in "한글 fix":
            self.assertEqual(editor.handle(character), EDITOR_EDIT)
        self.assertEqual(editor.text, "한글 fix")
        self.assertEqual(editor.handle("\n"), EDITOR_SUBMIT)

    def test_poll_timeout_is_ignored_rather_than_ending_input(self) -> None:
        editor = LineEditor("keep")
        self.assertEqual(editor.handle(None), EDITOR_IGNORED)
        self.assertEqual(editor.text, "keep")

    def test_escape_cancels(self) -> None:
        self.assertEqual(LineEditor("draft").handle("\x1b"), EDITOR_CANCEL)

    def test_backspace_removes_before_the_cursor(self) -> None:
        editor = LineEditor("abc")
        editor.handle(curses.KEY_BACKSPACE)
        self.assertEqual(editor.text, "ab")
        editor.handle("\x7f")
        self.assertEqual(editor.text, "a")

    def test_cursor_movement_inserts_in_place(self) -> None:
        editor = LineEditor("ac")
        editor.handle(curses.KEY_LEFT)
        editor.handle("b")
        self.assertEqual((editor.text, editor.cursor), ("abc", 2))

    def test_kill_line_and_kill_word(self) -> None:
        editor = LineEditor("one two three")
        editor.handle("\x17")
        self.assertEqual(editor.text, "one two ")
        editor.handle("\x15")
        self.assertEqual((editor.text, editor.cursor), ("", 0))


class FakeTask:
    def __init__(self, workspace: Path, request: str, index: int) -> None:
        self.workspace = workspace
        self.request = request
        self.index = index
        self.alive = True
        self.signals: list[bool] = []

    @property
    def running(self) -> bool:
        return self.alive

    def cancel(self, force: bool = False) -> bool:
        if not self.alive:
            return False
        self.signals.append(force)
        return True


class TaskManagerTests(unittest.TestCase):
    def test_admits_up_to_the_limit_and_then_refuses(self) -> None:
        manager = TaskManager(limit=2, factory=FakeTask)
        manager.start(Path("/workspace"), "first")
        manager.start(Path("/workspace"), "second")
        self.assertFalse(manager.can_start())
        with self.assertRaises(TaskAdmissionError):
            manager.start(Path("/workspace"), "third")

    def test_finished_tasks_free_a_slot_and_indexes_keep_growing(self) -> None:
        manager = TaskManager(limit=1, factory=FakeTask)
        first = manager.start(Path("/workspace"), "first")
        first.alive = False
        second = manager.start(Path("/workspace"), "second")
        self.assertEqual((first.index, second.index), (1, 2))
        self.assertEqual(manager.running_count, 1)

    def test_cancel_all_only_touches_running_children(self) -> None:
        manager = TaskManager(limit=3, factory=FakeTask)
        done = manager.start(Path("/workspace"), "done")
        done.alive = False
        manager.start(Path("/workspace"), "live")
        self.assertEqual(manager.cancel_all(), 1)

    def test_clear_finished_keeps_running_children(self) -> None:
        manager = TaskManager(limit=3, factory=FakeTask)
        done = manager.start(Path("/workspace"), "done")
        done.alive = False
        manager.start(Path("/workspace"), "live")
        self.assertEqual(manager.clear_finished(), 1)
        self.assertEqual([task.request for task in manager.tasks], ["live"])

    def test_rejects_a_zero_limit(self) -> None:
        with self.assertRaises(ValueError):
            TaskManager(limit=0)


class PresentationTests(unittest.TestCase):
    def test_status_categories_drive_color_selection(self) -> None:
        self.assertEqual(status_category("completed"), "ok")
        self.assertEqual(status_category("FAILED"), "fail")
        self.assertEqual(status_category("started"), "active")
        self.assertEqual(status_category("something-new"), "idle")

    def test_elapsed_text_scales_units(self) -> None:
        self.assertEqual(elapsed_text(9), "9s")
        self.assertEqual(elapsed_text(75), "1m15s")
        self.assertEqual(elapsed_text(3725), "1h02m")
        self.assertEqual(elapsed_text(-5), "0s")


if __name__ == "__main__":
    unittest.main()
