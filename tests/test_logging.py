import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.core.domain import ExecutionMetadata, ExecutionRecord, ExecutionStatus, Task
from adaptive_orchestrator.infrastructure.logging import JsonlExecutionLogger, redact


class JsonlExecutionLoggerTests(unittest.TestCase):
    def test_redacts_sensitive_context_keys_and_common_token_literals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "executions.jsonl"
            record = ExecutionRecord(
                Task("Use sk-abcdefghijklmnop", "Test", context={"api_key": "never-log-this"}),
                "agent", "prompt", (), ExecutionStatus.COMPLETED, "token=also-hidden", None, 0, 1.0,
                metadata=ExecutionMetadata(input_tokens=12, output_tokens=5, cached_input_tokens=3),
            )
            JsonlExecutionLogger(path).write(record)
            payload = json.loads(path.read_text())
            self.assertEqual(payload["task"]["context"]["api_key"], "[REDACTED]")
            self.assertNotIn("abcdefghijklmnop", payload["task"]["description"])
            self.assertIn("token=[REDACTED]", payload["result"])
            self.assertEqual(payload["metadata"]["input_tokens"], 12)
            self.assertEqual(payload["metadata"]["output_tokens"], 5)
            self.assertEqual(payload["metadata"]["cached_input_tokens"], 3)

    @unittest.skipUnless(os.name == "posix", "POSIX file mode")
    def test_execution_log_is_written_owner_only(self) -> None:
        # This sink holds full prompts, agent output, and the workspace diff when
        # it is enabled, so it must not be left at the umask's world-readable
        # default while the lifecycle log and routing state are owner-only.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "executions.jsonl"
            record = ExecutionRecord(
                Task("Describe", "Test"), "agent", "prompt", (), ExecutionStatus.COMPLETED,
                "result", None, 0, 1.0,
            )
            JsonlExecutionLogger(path).write(record)

            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    @unittest.skipUnless(os.name == "posix", "POSIX file mode")
    def test_existing_world_readable_execution_log_is_tightened_on_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "executions.jsonl"
            path.write_text("", encoding="utf-8")
            os.chmod(path, 0o644)
            record = ExecutionRecord(
                Task("Describe", "Test"), "agent", "prompt", (), ExecutionStatus.COMPLETED,
                "result", None, 0, 1.0,
            )
            JsonlExecutionLogger(path).write(record)

            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_token_named_string_values_are_still_redacted(self) -> None:
        self.assertEqual(redact({"input_tokens": "secret-value", "access_token": "secret-value"}), {
            "input_tokens": "[REDACTED]",
            "access_token": "[REDACTED]",
        })


if __name__ == "__main__":
    unittest.main()
