import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.domain import ExecutionRecord, ExecutionStatus, Task
from adaptive_orchestrator.logging import JsonlExecutionLogger


class JsonlExecutionLoggerTests(unittest.TestCase):
    def test_redacts_sensitive_context_keys_and_common_token_literals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "executions.jsonl"
            record = ExecutionRecord(
                Task("Use sk-abcdefghijklmnop", "Test", context={"api_key": "never-log-this"}),
                "agent", "prompt", (), ExecutionStatus.COMPLETED, "token=also-hidden", None, 0, 1.0,
            )
            JsonlExecutionLogger(path).write(record)
            payload = json.loads(path.read_text())
            self.assertEqual(payload["task"]["context"]["api_key"], "[REDACTED]")
            self.assertNotIn("abcdefghijklmnop", payload["task"]["description"])
            self.assertIn("token=[REDACTED]", payload["result"])


if __name__ == "__main__":
    unittest.main()
