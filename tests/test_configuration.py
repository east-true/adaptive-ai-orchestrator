from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.configuration import (
    ProjectConfigError,
    config_path,
    detect_verification_commands,
    initialize_project_config,
    load_project_config,
    project_config_from_mapping,
)


class ProjectConfigTests(unittest.TestCase):
    def test_missing_config_uses_safe_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = load_project_config(Path(directory))
        self.assertEqual(config.agent, "auto")
        self.assertEqual(config.verify_commands, ())
        self.assertTrue(config.escalation_enabled)
        self.assertFalse(config.include_git_diff)

    def test_loads_all_supported_values(self) -> None:
        payload = {
            "version": 1,
            "agent": "codex:gpt-5.5:high",
            "models": {"claude": "opus", "codex": "gpt-5.5", "codex_reasoning_effort": "high"},
            "execution": {"time_limit_seconds": 120, "verbose": True, "include_git_diff": True},
            "verification": {"commands": ["python3 -m unittest"], "time_limit_seconds": 30},
            "escalation": {"enabled": False, "risk_threshold": 2, "uncertainty_threshold": 4, "difficulty_threshold": 5},
        }
        config = project_config_from_mapping(payload)
        self.assertEqual(config.agent, "codex:gpt-5.5:high")
        self.assertEqual(config.claude_model, "opus")
        self.assertEqual(config.time_limit_seconds, 120)
        self.assertEqual(config.verify_commands, ("python3 -m unittest",))
        self.assertFalse(config.escalation_enabled)

    def test_rejects_unknown_fields_and_invalid_values(self) -> None:
        with self.assertRaisesRegex(ProjectConfigError, "unknown field"):
            project_config_from_mapping({"version": 1, "execution": {"verbsoe": True}})
        with self.assertRaisesRegex(ProjectConfigError, "expected auto"):
            project_config_from_mapping({"version": 1, "agent": "other"})
        with self.assertRaisesRegex(ProjectConfigError, "does not match"):
            project_config_from_mapping({"version": 1, "agent": "codex", "models": {"codex": "gpt-5.5"}})
        with self.assertRaisesRegex(ProjectConfigError, "integer from 1 to 5"):
            project_config_from_mapping({"version": 1, "escalation": {"difficulty_threshold": 0}})

    def test_init_writes_detected_unittest_command_and_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            tests = workspace / "tests"
            tests.mkdir()
            (tests / "test_example.py").write_text("", encoding="utf-8")

            path, commands = initialize_project_config(workspace)

            self.assertEqual(path, config_path(workspace))
            self.assertEqual(commands, ("python3 -m unittest discover -s tests -v",))
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["verification"]["commands"], list(commands))
            with self.assertRaisesRegex(ProjectConfigError, "already exists"):
                initialize_project_config(workspace)

    def test_force_replaces_existing_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            path = config_path(workspace)
            path.parent.mkdir()
            path.write_text("invalid", encoding="utf-8")
            initialize_project_config(workspace, force=True)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["version"], 1)

    def test_detects_common_project_test_commands_without_running_them(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "package.json").write_text(json.dumps({"scripts": {"test": "vitest"}}), encoding="utf-8")
            (workspace / "go.mod").write_text("module example", encoding="utf-8")
            self.assertEqual(detect_verification_commands(workspace), ("npm test", "go test ./..."))


if __name__ == "__main__":
    unittest.main()
