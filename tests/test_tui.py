from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.interfaces.tui import build_task_command, dashboard_rows
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


if __name__ == "__main__":
    unittest.main()
