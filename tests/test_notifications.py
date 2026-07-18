from __future__ import annotations

import io
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.notifications import notify_execution


class NotifyExecutionTests(unittest.TestCase):
    def test_terminal_bell_is_opt_in(self) -> None:
        stream = io.StringIO()
        self.assertEqual(notify_execution({"status": "completed"}, stream=stream), ())
        results = notify_execution({"status": "completed"}, terminal_bell=True, stream=stream)
        self.assertEqual(stream.getvalue(), "\a")
        self.assertTrue(results[0].delivered)

    def test_desktop_notification_contains_metadata_but_not_task_content(self) -> None:
        record = {
            "execution_id": "exec-1",
            "agent_id": "codex",
            "status": "failed",
            "verification": {"status": "failed"},
            "task": {"description": "private task details"},
        }
        completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with patch("adaptive_orchestrator.notifications.shutil.which", return_value="/usr/bin/notify-send"), patch(
            "adaptive_orchestrator.notifications.subprocess.run", return_value=completed
        ) as run:
            results = notify_execution(record, desktop=True)
        command = run.call_args.args[0]
        self.assertIn("critical", command)
        self.assertNotIn("private task details", " ".join(command))
        self.assertTrue(results[0].delivered)

    def test_missing_desktop_notifier_is_a_nonfatal_delivery_failure(self) -> None:
        with patch("adaptive_orchestrator.notifications.shutil.which", return_value=None):
            results = notify_execution({"status": "completed"}, desktop=True)
        self.assertFalse(results[0].delivered)
        self.assertIn("not found", results[0].detail)


if __name__ == "__main__":
    unittest.main()
