import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.agents import ClaudeCodeAgent, CodexAgent


class ClaudeCodeAgentTests(unittest.TestCase):
    def test_build_command_requests_structured_json_output(self) -> None:
        command = ClaudeCodeAgent().build_command("hello", Path("/tmp/workspace"))
        self.assertIn("--output-format", command)
        self.assertEqual(command[command.index("--output-format") + 1], "json")

    def test_parse_result_extracts_text_and_normalized_metadata(self) -> None:
        # Shape verified live against Claude Code 2.1.211's `--print --output-format json`.
        payload = {
            "type": "result",
            "subtype": "success",
            "result": "PONG",
            "num_turns": 1,
            "session_id": "db98e8e4-84bb-4cd8-bee2-58f8e14bdc58",
            "total_cost_usd": 0.065859,
            "usage": {"input_tokens": 2, "output_tokens": 5, "cache_read_input_tokens": 15800},
        }
        result, metadata = ClaudeCodeAgent().parse_result(json.dumps(payload))

        self.assertEqual(result, "PONG")
        self.assertEqual(metadata.cost_usd, 0.065859)
        self.assertEqual(metadata.input_tokens, 2)
        self.assertEqual(metadata.output_tokens, 5)
        self.assertEqual(metadata.cached_input_tokens, 15800)
        self.assertEqual(metadata.num_turns, 1)
        self.assertEqual(metadata.session_id, "db98e8e4-84bb-4cd8-bee2-58f8e14bdc58")

    def test_parse_result_falls_back_on_non_json_output(self) -> None:
        result, metadata = ClaudeCodeAgent().parse_result("plain legacy text, not json")
        self.assertEqual(result, "plain legacy text, not json")
        self.assertIsNone(metadata)

    def test_parse_result_handles_empty_output(self) -> None:
        result, metadata = ClaudeCodeAgent().parse_result("")
        self.assertIsNone(result)
        self.assertIsNone(metadata)


class CodexAgentTests(unittest.TestCase):
    def test_build_command_unchanged_pending_verified_json_schema(self) -> None:
        command = CodexAgent().build_command("hello", Path("/tmp/workspace"))
        self.assertNotIn("--json", command)

    def test_parse_result_is_plain_passthrough(self) -> None:
        result, metadata = CodexAgent().parse_result("Passed. 9 tests ran successfully.")
        self.assertEqual(result, "Passed. 9 tests ran successfully.")
        self.assertIsNone(metadata)


if __name__ == "__main__":
    unittest.main()
