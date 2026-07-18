from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.configuration import initialize_project_config
from adaptive_orchestrator.diagnostics import diagnose_project, diagnostics_succeeded


class DiagnoseProjectTests(unittest.TestCase):
    def test_reports_valid_config_and_authenticated_agents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            initialize_project_config(workspace)
            completed = subprocess.CompletedProcess([], 0, stdout="logged in\n", stderr="")
            with patch("adaptive_orchestrator.diagnostics.shutil.which", side_effect=lambda name: f"/bin/{name}"), patch(
                "adaptive_orchestrator.diagnostics.subprocess.run", return_value=completed
            ):
                checks = diagnose_project(workspace)

        self.assertTrue(diagnostics_succeeded(checks))
        self.assertEqual({check.name: check.status for check in checks}["selected-agent"], "PASS")

    def test_missing_agents_make_auto_selection_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            initialize_project_config(workspace)
            with patch("adaptive_orchestrator.diagnostics.shutil.which", return_value=None):
                checks = diagnose_project(workspace)
        statuses = {check.name: check.status for check in checks}
        self.assertEqual(statuses["claude-code"], "WARN")
        self.assertEqual(statuses["codex"], "WARN")
        self.assertEqual(statuses["selected-agent"], "FAIL")
        self.assertFalse(diagnostics_succeeded(checks))

    def test_invalid_config_is_a_failure_not_an_exception(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            path = workspace / ".orchestrator" / "config.json"
            path.parent.mkdir()
            path.write_text("{broken", encoding="utf-8")
            with patch("adaptive_orchestrator.diagnostics.shutil.which", return_value=None):
                checks = diagnose_project(workspace)
        self.assertEqual({check.name: check.status for check in checks}["config"], "FAIL")


if __name__ == "__main__":
    unittest.main()
