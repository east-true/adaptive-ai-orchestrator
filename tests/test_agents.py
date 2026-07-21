import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.execution.agents import ClaudeCodeAgent, CodexAgent


class ClaudeCodeAgentTests(unittest.TestCase):
    def test_agent_id_derivation_and_explicit_name(self) -> None:
        self.assertEqual(ClaudeCodeAgent().agent_id, "claude-code")
        self.assertEqual(ClaudeCodeAgent(model="opus").agent_id, "claude-code:opus")
        self.assertEqual(ClaudeCodeAgent(agent_id="CO", model="opus").agent_id, "CO")

    def test_base_id_is_shared_and_unaffected_by_custom_agent_id(self) -> None:
        self.assertEqual(ClaudeCodeAgent.base_id, ClaudeCodeAgent(agent_id="CO").base_id)
        self.assertEqual(ClaudeCodeAgent(agent_id="CO").base_id, "claude-code")

    def test_build_command_model_flag_is_additive(self) -> None:
        default = ClaudeCodeAgent().build_command("hello", Path("/tmp/workspace"))
        self.assertEqual(default, ("claude", "--print", "--output-format", "json", "--permission-mode", "acceptEdits", "hello"))
        self.assertEqual(ClaudeCodeAgent(model="opus").build_command("hello", Path("/tmp/workspace"))[-3:], ("--model", "opus", "hello"))

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

    def test_parse_result_records_only_one_actual_model(self) -> None:
        _, metadata = ClaudeCodeAgent(model="opus").parse_result(json.dumps({"result": "ok", "modelUsage": {"claude-sonnet-5": {}}}))
        self.assertEqual(metadata.model, "claude-sonnet-5")
        for model_usage in ({}, {"one": {}, "two": {}}):
            _, metadata = ClaudeCodeAgent().parse_result(json.dumps({"result": "ok", "modelUsage": model_usage}))
            self.assertIsNone(metadata.model)


class CodexAgentTests(unittest.TestCase):
    def test_agent_id_derivation(self) -> None:
        self.assertEqual(CodexAgent(reasoning_effort="high").agent_id, "codex:high")
        self.assertEqual(CodexAgent(model="gpt-5.5", reasoning_effort="high").agent_id, "codex:gpt-5.5:high")

    def test_build_command_configuration_flags_are_additive(self) -> None:
        default = CodexAgent().build_command("hello", Path("/tmp/workspace"))
        self.assertEqual(default, ("codex", "exec", "--sandbox", "workspace-write", "--cd", "/tmp/workspace", "--json", "hello"))
        configured = CodexAgent(model="gpt-5.5", reasoning_effort="high").build_command("hello", Path("/tmp/workspace"))
        self.assertIn(("-m", "gpt-5.5"), tuple(zip(configured, configured[1:])))
        self.assertIn(("-c", "model_reasoning_effort=high"), tuple(zip(configured, configured[1:])))

    def test_build_command_requests_structured_json_output(self) -> None:
        command = CodexAgent().build_command("hello", Path("/tmp/workspace"))
        self.assertEqual(command[:4], ("codex", "exec", "--sandbox", "workspace-write"))
        self.assertIn("--json", command)

    def test_parse_result_extracts_final_agent_message_and_normalized_metadata(self) -> None:
        # Shape verified live against Codex CLI 0.144.5's `exec --json`.
        lines = [
            {"type": "thread.started", "thread_id": "019f6bf0-7b90-7b92-9736-675309bf27f9"},
            {"type": "turn.started"},
            {"type": "item.completed", "item": {"id": "item_0", "type": "agent_message", "text": "PONG2"}},
            {"type": "turn.completed", "usage": {"input_tokens": 10612, "cached_input_tokens": 8576, "output_tokens": 26, "reasoning_output_tokens": 17}},
        ]
        result, metadata = CodexAgent().parse_result("\n".join(json.dumps(line) for line in lines))

        self.assertEqual(result, "PONG2")
        self.assertEqual(metadata.input_tokens, 10612)
        self.assertEqual(metadata.output_tokens, 26)
        self.assertEqual(metadata.cached_input_tokens, 8576)
        self.assertEqual(metadata.session_id, "019f6bf0-7b90-7b92-9736-675309bf27f9")
        self.assertIsNone(metadata.cost_usd)  # Codex CLI does not expose a cost field, unlike Claude Code

    def test_parse_result_ignores_tool_call_items_and_keeps_final_agent_message(self) -> None:
        # Shape verified live: a task that runs a shell command before answering.
        lines = [
            {"type": "thread.started", "thread_id": "019f6bf1-17ec-70a0-9293-2dcf03aa2057"},
            {"type": "turn.started"},
            {"type": "item.started", "item": {"id": "item_0", "type": "command_execution", "command": "echo hello-from-codex", "status": "in_progress"}},
            {"type": "item.completed", "item": {"id": "item_0", "type": "command_execution", "command": "echo hello-from-codex", "aggregated_output": "hello-from-codex\n", "exit_code": 0, "status": "completed"}},
            {"type": "item.completed", "item": {"id": "item_1", "type": "agent_message", "text": "DONE"}},
            {"type": "turn.completed", "usage": {"input_tokens": 22081, "cached_input_tokens": 19200, "output_tokens": 133, "reasoning_output_tokens": 41}},
        ]
        result, metadata = CodexAgent().parse_result("\n".join(json.dumps(line) for line in lines))
        self.assertEqual(result, "DONE")
        self.assertEqual(metadata.output_tokens, 133)

    def test_parse_result_extracts_error_message_on_failure(self) -> None:
        # Shape verified live against an actual usage-cap error response.
        lines = [
            {"type": "thread.started", "thread_id": "019f6bcf-7e35-7ff3-a462-5d45d3eee524"},
            {"type": "turn.started"},
            {"type": "error", "message": "You've hit your usage limit."},
            {"type": "turn.failed", "error": {"message": "You've hit your usage limit."}},
        ]
        result, metadata = CodexAgent().parse_result("\n".join(json.dumps(line) for line in lines))
        self.assertEqual(result, "You've hit your usage limit.")
        self.assertEqual(metadata.session_id, "019f6bcf-7e35-7ff3-a462-5d45d3eee524")

    def test_parse_result_falls_back_on_non_json_output(self) -> None:
        result, metadata = CodexAgent().parse_result("Passed. 9 tests ran successfully.")
        self.assertEqual(result, "Passed. 9 tests ran successfully.")
        self.assertIsNone(metadata)

    def test_parse_result_skips_truncated_line_without_discarding_the_rest(self) -> None:
        lines = [
            json.dumps({"type": "thread.started", "thread_id": "abc"}),
            '{"type": "item.completed", "item": {"type": "agent_message", "tex',  # truncated, e.g. after a timeout
        ]
        result, metadata = CodexAgent().parse_result("\n".join(lines))
        self.assertEqual(metadata.session_id, "abc")

    def test_parse_result_records_requested_model(self) -> None:
        _, metadata = CodexAgent(model="gpt-5.5").parse_result(json.dumps({"type": "thread.started", "thread_id": "abc"}))
        self.assertEqual(metadata.model, "gpt-5.5")


if __name__ == "__main__":
    unittest.main()
