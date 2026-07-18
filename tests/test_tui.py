from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.tui import build_task_command, dashboard_rows


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
