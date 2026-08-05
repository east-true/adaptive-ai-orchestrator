from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.infrastructure.configuration import initialize_project_config
from adaptive_orchestrator.operations.diagnostics import diagnose_project, diagnostics_succeeded


class DiagnoseProjectTests(unittest.TestCase):
    def test_reports_valid_config_and_authenticated_agents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            initialize_project_config(workspace)
            completed = subprocess.CompletedProcess([], 0, stdout="logged in\n", stderr="")
            with patch("adaptive_orchestrator.operations.diagnostics.shutil.which", side_effect=lambda name: f"/bin/{name}"), patch(
                "adaptive_orchestrator.operations.diagnostics.subprocess.run", return_value=completed
            ):
                checks = diagnose_project(workspace)

        self.assertTrue(diagnostics_succeeded(checks))
        self.assertEqual({check.name: check.status for check in checks}["selected-agent"], "PASS")

    def test_missing_agents_make_auto_selection_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            initialize_project_config(workspace)
            with patch("adaptive_orchestrator.operations.diagnostics.shutil.which", return_value=None):
                checks = diagnose_project(workspace)
        statuses = {check.name: check.status for check in checks}
        self.assertEqual(statuses["claude-code"], "WARN")
        self.assertEqual(statuses["codex"], "WARN")
        self.assertEqual(statuses["selected-agent"], "FAIL")
        self.assertFalse(diagnostics_succeeded(checks))

    def test_json_login_status_is_summarized_without_account_identifiers(self) -> None:
        # `claude auth status` answers with JSON carrying the account email,
        # organization ID, and organization name. doctor output gets pasted into
        # issues and screenshots, so only usability fields may be echoed.
        status = json.dumps({
            "loggedIn": True,
            "authMethod": "claude.ai",
            "apiProvider": "firstParty",
            "email": "person@example.com",
            "orgId": "179a9108-0f59-4cc1-925a-fbe948ef207a",
            "orgName": "person@example.com's Organization",
            "subscriptionType": "pro",
        })
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            initialize_project_config(workspace)
            completed = subprocess.CompletedProcess([], 0, stdout=status, stderr="")
            with (
                patch(
                    "adaptive_orchestrator.operations.diagnostics.shutil.which",
                    side_effect=lambda name: f"/bin/{name}",
                ),
                patch(
                    "adaptive_orchestrator.operations.diagnostics.subprocess.run",
                    return_value=completed,
                ),
            ):
                checks = diagnose_project(workspace)

        detail = {check.name: check.detail for check in checks}["claude-code"]
        for identifier in ("person@example.com", "179a9108", "Organization"):
            self.assertNotIn(identifier, detail)
        self.assertIn("loggedIn=True", detail)
        self.assertIn("subscriptionType=pro", detail)
        self.assertTrue(diagnostics_succeeded(checks))

    def test_non_json_login_status_is_still_shown_as_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            initialize_project_config(workspace)
            completed = subprocess.CompletedProcess([], 0, stdout="Logged in using ChatGPT\n", stderr="")
            with (
                patch(
                    "adaptive_orchestrator.operations.diagnostics.shutil.which",
                    side_effect=lambda name: f"/bin/{name}",
                ),
                patch(
                    "adaptive_orchestrator.operations.diagnostics.subprocess.run",
                    return_value=completed,
                ),
            ):
                checks = diagnose_project(workspace)

        self.assertEqual(
            {check.name: check.detail for check in checks}["codex"],
            "Logged in using ChatGPT",
        )

    def test_invalid_config_is_a_failure_not_an_exception(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            path = workspace / ".orchestrator" / "config.json"
            path.parent.mkdir()
            path.write_text("{broken", encoding="utf-8")
            with patch("adaptive_orchestrator.operations.diagnostics.shutil.which", return_value=None):
                checks = diagnose_project(workspace)
        self.assertEqual({check.name: check.status for check in checks}["config"], "FAIL")


if __name__ == "__main__":
    unittest.main()
