import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.usage import CodexUsage, read_claude_subscription, read_codex_usage


def _rate_limit_line(used_percent: float = 1.0) -> str:
    return json.dumps({
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "rate_limits": {
                "primary": {"used_percent": used_percent, "window_minutes": 10080, "resets_at": 1784827154},
                "secondary": None,
                "plan_type": "plus",
            },
        },
    })


class CodexUsageTests(unittest.TestCase):
    def test_rate_limit_line_returns_usage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            sessions = home / "sessions" / "2026" / "07"
            sessions.mkdir(parents=True)
            (sessions / "rollout.jsonl").write_text(f"{{}}\n{_rate_limit_line()}\n", encoding="utf-8")

            self.assertEqual(
                read_codex_usage(home),
                CodexUsage(plan_type="plus", used_percent=1.0, window_minutes=10080, resets_at=1784827154),
            )

    def test_older_recent_file_is_checked_when_newest_has_no_rate_limits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            sessions = home / "sessions"
            sessions.mkdir()
            older = sessions / "older.jsonl"
            newer = sessions / "newer.jsonl"
            older.write_text(_rate_limit_line(27.5), encoding="utf-8")
            newer.write_text(json.dumps({"type": "event_msg", "payload": {"type": "token_count"}}), encoding="utf-8")
            older.touch()
            newer.touch()

            usage = read_codex_usage(home)

            self.assertIsNotNone(usage)
            self.assertEqual(usage.used_percent, 27.5)

    def test_missing_sessions_directory_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(read_codex_usage(Path(directory)))

    def test_malformed_json_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sessions = Path(directory) / "sessions"
            sessions.mkdir()
            (sessions / "broken.jsonl").write_text("not json\n{also broken", encoding="utf-8")
            self.assertIsNone(read_codex_usage(Path(directory)))


class ClaudeSubscriptionTests(unittest.TestCase):
    @patch("adaptive_orchestrator.usage.subprocess.run")
    def test_valid_json_returns_subscription_type(self, run: Mock) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, json.dumps({"subscriptionType": "pro"}), "")
        self.assertEqual(read_claude_subscription(), "pro")
        run.assert_called_once_with(
            ["claude", "auth", "status"], capture_output=True, text=True, check=False, timeout=5.0
        )

    @patch("adaptive_orchestrator.usage.subprocess.run")
    def test_nonzero_exit_returns_none(self, run: Mock) -> None:
        run.return_value = subprocess.CompletedProcess([], 1, "", "failed")
        self.assertIsNone(read_claude_subscription())

    @patch("adaptive_orchestrator.usage.subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 5))
    def test_timeout_returns_none(self, run: Mock) -> None:
        self.assertIsNone(read_claude_subscription())

    @patch("adaptive_orchestrator.usage.subprocess.run")
    def test_malformed_json_returns_none(self, run: Mock) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, "not json", "")
        self.assertIsNone(read_claude_subscription())


if __name__ == "__main__":
    unittest.main()
