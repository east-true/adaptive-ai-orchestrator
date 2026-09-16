import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.execution.agents import ClaudeCodeAgent, CodexAgent
from adaptive_orchestrator.core.domain import Capability, ExecutionStatus, Task
from adaptive_orchestrator.orchestration.kernel import OrchestratorKernel
from adaptive_orchestrator.infrastructure.logging import JsonlExecutionLogger
from adaptive_orchestrator.infrastructure.events import (
    JsonlEventStore,
    LifecycleEventType,
)
from adaptive_orchestrator.execution.process_runner import ProcessResult


class FakeRunner:
    def __init__(self, result: ProcessResult) -> None:
        self.result = result
        self.calls = []

    def run(self, command, cwd, timeout_seconds):
        self.calls.append((command, cwd, timeout_seconds))
        return self.result


class InterruptingRunner:
    def run(self, command, cwd, timeout_seconds):
        raise KeyboardInterrupt()


class TerminalFailingRecorder:
    def __init__(self) -> None:
        self.attempted: list[LifecycleEventType] = []

    def record(self, event_type, **kwargs):
        del kwargs
        self.attempted.append(event_type)
        if event_type in {
            LifecycleEventType.EXECUTION_TERMINAL,
            LifecycleEventType.OUTCOME_FINALIZED,
        }:
            raise RuntimeError("synthetic durable recorder failure")
        return None


class KernelTests(unittest.TestCase):
    def test_terminal_recorder_failure_does_not_mask_original_interruption(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            recorder = TerminalFailingRecorder()
            kernel = OrchestratorKernel(
                {"codex": CodexAgent()},
                JsonlExecutionLogger(workspace / "executions.jsonl"),
                workspace,
                InterruptingRunner(),
                lifecycle_recorder=recorder,  # type: ignore[arg-type]
            )

            with self.assertRaises(KeyboardInterrupt):
                kernel.execute(Task("Plan", "Plan"), "codex")

        self.assertEqual(
            recorder.attempted[-2:],
            [
                LifecycleEventType.EXECUTION_TERMINAL,
                LifecycleEventType.OUTCOME_FINALIZED,
            ],
        )

    def test_terminal_provider_errors_and_collisions_use_prevalidated_fallback(
        self,
    ) -> None:
        fallback = {
            "resource_observation": {
                "resource_supervisor_invocations": [{"role": "fallback"}],
            }
        }

        def raises():
            raise RuntimeError("synthetic provider failure")

        providers = (
            raises,
            lambda: {
                "status": "must-not-overwrite",
                "resource_observation": {},
            },
            lambda: {"resource_observation": []},
        )
        for provider in providers:
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                events = JsonlEventStore(
                    workspace / ".orchestrator" / "events.jsonl"
                )
                kernel = OrchestratorKernel(
                    {"codex": CodexAgent()},
                    JsonlExecutionLogger(workspace / "executions.jsonl"),
                    workspace,
                    InterruptingRunner(),
                    terminal_outcome_payload_provider=provider,
                    terminal_outcome_payload_fallback=fallback,
                )
                with self.assertRaises(KeyboardInterrupt):
                    kernel.execute(Task("Plan", "Plan"), "codex")
                outcomes = [
                    event
                    for event in events.read()
                    if event.event_type is LifecycleEventType.OUTCOME_FINALIZED
                ]
                self.assertEqual(len(outcomes), 1)
                self.assertEqual(outcomes[0].payload["status"], "interrupted")
                self.assertEqual(
                    outcomes[0].payload["error_type"], "KeyboardInterrupt"
                )
                self.assertEqual(
                    outcomes[0].payload["resource_observation"],
                    fallback["resource_observation"],
                )
                self.assertEqual(
                    outcomes[0].payload[
                        "terminal_outcome_payload_provider"
                    ]["status"],
                    "failed",
                )

    def test_codex_execution_is_logged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            runner = FakeRunner(ProcessResult(("codex", "exec"), ExecutionStatus.COMPLETED, "done", "non-error diagnostic", 0, 12.5))
            log_path = workspace / "executions.jsonl"
            agent = CodexAgent(capabilities=frozenset({Capability.PLANNING}))
            record = OrchestratorKernel({"codex": agent}, JsonlExecutionLogger(log_path), workspace, runner).execute(
                Task("Make a plan", "Plan", required_capabilities=(Capability.PLANNING,), time_limit_seconds=30), "codex"
            )
            self.assertEqual(record.status, ExecutionStatus.COMPLETED)
            self.assertEqual(record.result, "done")
            self.assertIsNone(record.error)
            self.assertEqual(runner.calls[0][2], 30)
            payload = json.loads(log_path.read_text())
            self.assertEqual(payload["agent_id"], "codex")
            self.assertIsNone(payload["workspace_git_diff"])
            self.assertEqual(payload["execution_id"], record.execution_id)
            self.assertEqual(payload["attempt_id"], record.attempt_id)
            self.assertEqual(payload["selection_mode"], "manual")
            self.assertEqual(payload["cohort"], "manual")
            self.assertFalse(payload["routing_evidence_eligible"])
            self.assertEqual(len(payload["config_hash"]), 64)
            self.assertIsNotNone(datetime.fromisoformat(payload["occurred_at"].replace("Z", "+00:00")))

    def test_claude_json_output_is_parsed_into_normalized_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            stdout = json.dumps({"result": "PONG", "num_turns": 1, "session_id": "abc", "total_cost_usd": 0.01, "usage": {"input_tokens": 2, "output_tokens": 5}})
            runner = FakeRunner(ProcessResult(("claude",), ExecutionStatus.COMPLETED, stdout, "", 0, 5.0))
            agent = ClaudeCodeAgent(capabilities=frozenset({Capability.PLANNING}))
            record = OrchestratorKernel({"claude-code": agent}, JsonlExecutionLogger(workspace / "log.jsonl"), workspace, runner).execute(
                Task("Make a plan", "Plan", required_capabilities=(Capability.PLANNING,)), "claude-code"
            )
            self.assertEqual(record.result, "PONG")
            self.assertEqual(record.metadata.cost_usd, 0.01)
            self.assertEqual(record.metadata.input_tokens, 2)
            self.assertEqual(record.metadata.session_id, "abc")

    def test_missing_capability_is_logged_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            runner = FakeRunner(ProcessResult((), ExecutionStatus.COMPLETED, "", "", 0, 1))
            agent = CodexAgent(capabilities=frozenset({Capability.PLANNING}))
            record = OrchestratorKernel({"codex": agent}, JsonlExecutionLogger(workspace / "log.jsonl"), workspace, runner).execute(
                Task("Find a bug", "Debug", required_capabilities=(Capability.DEBUGGING,)), "codex"
            )
            self.assertEqual(record.status, ExecutionStatus.FAILED)
            self.assertIn("lacks capabilities", record.error or "")

    def test_cli_adapters_build_noninteractive_safe_default_commands(self) -> None:
        workspace = Path("/tmp/workspace")
        claude = ClaudeCodeAgent()
        codex = CodexAgent()
        self.assertIn("--print", claude.build_command("hello", workspace))
        self.assertNotIn("--dangerously-skip-permissions", claude.build_command("hello", workspace))
        self.assertEqual(codex.build_command("hello", workspace)[:4], ("codex", "exec", "--sandbox", "workspace-write"))

    def test_time_limit_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            Task("Plan", "Plan", time_limit_seconds=0)


if __name__ == "__main__":
    unittest.main()
