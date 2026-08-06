from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import curses

from adaptive_orchestrator.interfaces.tui import (
    EDITOR_CANCEL,
    EDITOR_EDIT,
    EDITOR_IGNORED,
    EDITOR_SUBMIT,
    VIEW_COMPOSE,
    VIEW_DASHBOARD,
    LineEditor,
    DashboardRow,
    TaskAdmissionError,
    TaskManager,
    _dashboard_layout,
    build_task_command,
    clamp_offset,
    condense_path,
    dashboard_rows,
    display_width,
    elapsed_text,
    filter_rows,
    fit_to_width,
    main,
    OrchestratorTui,
    markdown_heading,
    scroll_offset,
    status_category,
    wrap_text,
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


def _dashboard_row(task_id: str = "", status: str = "completed", agent: str = "codex",
                    verification: str = "passed", attempt_count: int = 1) -> DashboardRow:
    return DashboardRow(
        execution_id="e", status=status, agent=agent, verification=verification,
        description="d", attempts=(), task_id=task_id, attempt_count=attempt_count,
    )


class DashboardLayoutTests(unittest.TestCase):
    """Columns, in order: exec id, task id, attempts, agent, verification, task."""

    def test_prefers_default_widths_when_there_are_no_rows_to_measure(self) -> None:
        self.assertEqual(_dashboard_layout(120, ()), (8, 18, 8, 16, 12, 46))

    def test_short_visible_values_shrink_fixed_columns_below_their_preferred_max(self) -> None:
        # Fixed columns should shrink toward what is actually on screen (plus
        # its header) rather than always reserving their full preferred
        # width, leaving more room for TASK.
        rows = (_dashboard_row(task_id="short"),)
        widths = _dashboard_layout(120, rows)
        self.assertEqual(widths, (8, 10, 8, 10, 12, 60))
        self.assertGreater(widths[-1], _dashboard_layout(120, ())[-1])

    def test_exec_id_column_stays_at_its_fixed_width_regardless_of_content(self) -> None:
        # exec_id is always an 8-character slice of the execution id, not
        # measured text, so nothing about row content should change it.
        rows = (_dashboard_row(task_id="a-very-long-task-identifier-1234567890"),)
        exec_id_width, task_id_width, *_ = _dashboard_layout(120, rows)
        self.assertEqual(exec_id_width, 8)
        # Unlike the old task-id-only special case, TASK ID now caps at its
        # own preferred width like every other fixed column instead of
        # growing without bound.
        self.assertEqual(task_id_width, 18)

    def test_task_keeps_its_reserved_minimum_while_every_other_column_is_squeezed(self) -> None:
        # A narrow terminal must still show *something* of the task text: the
        # fixed columns give up width, in priority order, before TASK does.
        widths = _dashboard_layout(40, ())
        self.assertEqual(widths, (2, 4, 0, 4, 2, 16))
        self.assertEqual(widths[-1], 16)

    def test_exec_id_still_gets_some_width_once_lower_priority_columns_hit_zero(self) -> None:
        # exec_id is what every follow-up show/retry/report command needs, so
        # it keeps *something* even once a lower-priority column (attempts)
        # has been squeezed away entirely.
        exec_id_width, _task_id_width, attempts_width, *_ = _dashboard_layout(40, ())
        self.assertEqual(attempts_width, 0)
        self.assertGreater(exec_id_width, 0)

    def test_a_terminal_too_narrow_for_any_column_returns_all_zero(self) -> None:
        for width in (8, 0, -5):
            with self.subTest(width=width):
                self.assertEqual(_dashboard_layout(width, ()), (0, 0, 0, 0, 0, 0))


class BuildTaskCommandTests(unittest.TestCase):
    def test_builds_shell_free_verbose_cli_command(self) -> None:
        command = build_task_command(Path("/workspace"), "Run the tests")
        self.assertEqual(command[0], sys.executable)
        self.assertIn("adaptive_orchestrator.cli", command)
        self.assertIn("--verbose", command)
        self.assertEqual(command.count("Run the tests"), 2)

    def test_requests_the_readable_summary_instead_of_the_raw_json_record(self) -> None:
        # The task's log view is meant to read like output, not a dumped
        # execution record: without --summary, `run` prints the full
        # {"plan": ..., "execution": ...} JSON on completion.
        command = build_task_command(Path("/workspace"), "Run the tests")
        self.assertIn("--summary", command)

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

    def test_ellipsis_marks_real_truncation_only(self) -> None:
        self.assertEqual(fit_to_width("abcdef", 4, ellipsis=True), "abc…")
        self.assertEqual(fit_to_width("abc", 10, ellipsis=True), "abc")
        self.assertEqual(display_width(fit_to_width("abcdef", 4, ellipsis=True)), 4)

    def test_ellipsis_is_skipped_when_the_budget_is_too_tight(self) -> None:
        self.assertEqual(fit_to_width("abcdef", 1, ellipsis=True), "a")
        self.assertEqual(fit_to_width("abcdef", 0, ellipsis=True), "")


class CondensePathTests(unittest.TestCase):
    def test_short_paths_are_unchanged(self) -> None:
        self.assertEqual(condense_path("/tmp/work", 40), "/tmp/work")

    def test_long_paths_keep_the_meaningful_tail(self) -> None:
        result = condense_path("/home/user/very/deeply/nested/orchestrator", 20)
        self.assertTrue(result.startswith("…/"))
        self.assertTrue(result.endswith("orchestrator"))
        self.assertLessEqual(display_width(result), 20)

    def test_a_single_oversized_segment_falls_back_to_tail_truncation(self) -> None:
        result = condense_path("/home/user/very/deeply/nested/adaptive-ai-orchestrator", 24)
        self.assertTrue(result.startswith("…"))
        self.assertLessEqual(display_width(result), 24)

    def test_degenerate_budget_never_crashes(self) -> None:
        self.assertEqual(condense_path("/a/b/c", 0), "")
        condense_path("/a/b/c", 1)  # must not raise


class MarkdownHeadingTests(unittest.TestCase):
    def test_hash_prefixed_lines_are_headings(self) -> None:
        self.assertEqual(markdown_heading("# Execution exec-1"), ("Execution exec-1", 1))
        self.assertEqual(markdown_heading("## Outcome"), ("Outcome", 2))

    def test_body_text_is_unaffected(self) -> None:
        self.assertEqual(markdown_heading("Attempts: 1"), ("Attempts: 1", 0))
        self.assertEqual(markdown_heading("#nospace"), ("#nospace", 0))
        self.assertEqual(markdown_heading(""), ("", 0))


class DashboardEmptyStateTests(unittest.TestCase):
    def _tui(self) -> OrchestratorTui:
        return OrchestratorTui.__new__(OrchestratorTui)

    def test_fresh_workspace_says_how_to_start(self) -> None:
        tui = self._tui()
        tui.rows = ()
        tui.filter_text = ""

        lines = tui._dashboard_empty_lines()
        self.assertIn("No executions recorded", lines[0])
        self.assertIn("Press n", " ".join(lines))

    def test_filter_that_hides_everything_is_distinguished_from_no_data(self) -> None:
        tui = self._tui()
        tui.rows = (
            DashboardRow("e1", "completed", "codex", "passed", "Build it", ()),
            DashboardRow("e2", "completed", "codex", "passed", "Ship it", ()),
        )
        tui.filter_text = "nomatch"

        lines = tui._dashboard_empty_lines()
        joined = " ".join(lines)
        self.assertIn("nomatch", joined)
        self.assertIn("2 hidden by the filter", joined)
        self.assertNotIn("No executions recorded", joined)


class WrapTextTests(unittest.TestCase):
    def test_short_text_is_returned_as_a_single_line(self) -> None:
        self.assertEqual(wrap_text("short line", 40), ["short line"])

    def test_blank_lines_are_preserved(self) -> None:
        self.assertEqual(wrap_text("", 40), [""])

    def test_long_prose_wraps_on_word_boundaries_within_budget(self) -> None:
        lines = wrap_text("Migrate the config loader from YAML to TOML", 12)
        self.assertGreater(len(lines), 1)
        for line in lines:
            self.assertLessEqual(display_width(line), 12)
        self.assertEqual(" ".join(lines), "Migrate the config loader from YAML to TOML")

    def test_a_single_overlong_word_is_hard_broken_not_dropped(self) -> None:
        lines = wrap_text("a" * 30, 10)
        self.assertEqual("".join(lines), "a" * 30)
        for line in lines:
            self.assertLessEqual(display_width(line), 10)

    def test_zero_budget_returns_text_unchanged(self) -> None:
        self.assertEqual(wrap_text("anything", 0), ["anything"])

    def test_double_width_character_wider_than_the_budget_terminates(self) -> None:
        # Both call sites clamp the wrap budget to a minimum of 1, so a
        # one-column pane is reachable. A double-width glyph never fits there,
        # and returning nothing for it used to leave the remainder unchanged and
        # spin forever.
        for text in ("한글", "abc한글def", "한 글"):
            with self.subTest(text=text):
                lines = wrap_text(text, 1)
                self.assertEqual("".join(lines), text.replace(" ", ""))
                self.assertTrue(all(lines))

    def test_hard_break_keeps_every_character_at_narrow_widths(self) -> None:
        text = "한글abc漢字"
        for columns in (1, 2, 3, 4):
            with self.subTest(columns=columns):
                self.assertEqual("".join(wrap_text(text, columns)), text)


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


class ComposeViewTests(unittest.TestCase):
    """VIEW_COMPOSE routes almost every key to the editor as literal text —
    only Enter and Esc are reserved — so shortcuts that work on every other
    view must not fire here.
    """

    def _app(self) -> OrchestratorTui:
        workspace = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, workspace, ignore_errors=True)
        app = OrchestratorTui(workspace)
        app.tasks = TaskManager(limit=2, factory=FakeTask)
        app.view = VIEW_COMPOSE
        return app

    def test_letters_that_are_shortcuts_on_every_other_view_are_typed_literally(self) -> None:
        app = self._app()
        for character in "n?q/aCx":
            app._handle_key(None, character)
        self.assertEqual(app.compose_editor.text, "n?q/aCx")
        self.assertEqual(app.view, VIEW_COMPOSE)
        self.assertFalse(app.help_visible)

    def test_enter_starts_the_task_and_stays_on_the_compose_view(self) -> None:
        app = self._app()
        for character in "do the thing":
            app._handle_key(None, character)
        app._handle_key(None, "\n")
        self.assertEqual(app.view, VIEW_COMPOSE)
        self.assertIsNotNone(app.compose_task)
        self.assertEqual(app.compose_task.request, "do the thing")
        # The editor resets so the next request can be typed immediately.
        self.assertEqual(app.compose_editor.text, "")

    def test_escape_cancels_back_to_the_dashboard_without_starting_anything(self) -> None:
        app = self._app()
        for character in "abandoned":
            app._handle_key(None, character)
        app._handle_key(None, "\x1b")
        self.assertEqual(app.view, VIEW_DASHBOARD)
        self.assertIsNone(app.compose_task)

    def test_submitting_blank_text_does_not_start_a_task(self) -> None:
        app = self._app()
        app._handle_key(None, "\n")
        self.assertIsNone(app.compose_task)
        self.assertEqual(app.view, VIEW_COMPOSE)

    def test_n_from_another_view_opens_a_fresh_compose_screen(self) -> None:
        app = self._app()
        app.view = VIEW_DASHBOARD
        app.compose_editor = LineEditor("leftover text")
        app._handle_key(None, "n")
        self.assertEqual(app.view, VIEW_COMPOSE)
        self.assertEqual(app.compose_editor.text, "")


class PresentationTests(unittest.TestCase):
    def test_status_categories_drive_color_selection(self) -> None:
        self.assertEqual(status_category("completed"), "ok")
        self.assertEqual(status_category("FAILED"), "fail")
        self.assertEqual(status_category("started"), "active")
        self.assertEqual(status_category("something-new"), "idle")

    def test_domain_terminal_statuses_are_categorized_correctly(self) -> None:
        # These spellings come from ExecutionStatus/VerificationStatus in core/domain.py.
        self.assertEqual(status_category("timed_out"), "fail")
        self.assertEqual(status_category("spawn_error"), "fail")

    def test_elapsed_text_scales_units(self) -> None:
        self.assertEqual(elapsed_text(9), "9s")
        self.assertEqual(elapsed_text(75), "1m15s")
        self.assertEqual(elapsed_text(3725), "1h02m")
        self.assertEqual(elapsed_text(-5), "0s")


class MainCleanupTests(unittest.TestCase):
    def test_running_tasks_are_force_cancelled_if_the_ui_loop_crashes(self) -> None:
        workspace = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, workspace, ignore_errors=True)
        captured: dict[str, object] = {}

        def fake_wrapper(run_method):
            app = run_method.__self__
            app.tasks = TaskManager(limit=2, factory=FakeTask)
            captured["task"] = app.tasks.start(workspace, "live")
            raise KeyboardInterrupt

        with mock.patch("adaptive_orchestrator.interfaces.tui.curses.wrapper", side_effect=fake_wrapper):
            with self.assertRaises(KeyboardInterrupt):
                main(["--workspace", str(workspace)])

        self.assertEqual(captured["task"].signals, [True])


if __name__ == "__main__":
    unittest.main()
