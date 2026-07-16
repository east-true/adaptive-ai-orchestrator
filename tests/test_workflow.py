import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.agents import CodexAgent
from adaptive_orchestrator.domain import Capability, ExecutionStatus, Task, VerificationStatus
from adaptive_orchestrator.kernel import OrchestratorKernel
from adaptive_orchestrator.logging import JsonlExecutionLogger
from adaptive_orchestrator.planning import CapabilitySelector
from adaptive_orchestrator.process_runner import ProcessResult
from adaptive_orchestrator.verification import CommandVerifier
from adaptive_orchestrator.workflow import EngineeringWorkflow


class SequencedRunner:
    def __init__(self) -> None:
        self.calls = []

    def run(self, command, cwd, timeout_seconds):
        self.calls.append(tuple(command))
        return ProcessResult(command, ExecutionStatus.COMPLETED, "ok", "", 0, 1)


class WorkflowTests(unittest.TestCase):
    def test_auto_selects_capable_agent_and_runs_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            runner = SequencedRunner()
            agent = CodexAgent(capabilities=frozenset({Capability.TESTING}))
            kernel = OrchestratorKernel({agent.agent_id: agent}, JsonlExecutionLogger(workspace / "log.jsonl"), workspace, runner)
            workflow = EngineeringWorkflow(kernel, CapabilitySelector(), CommandVerifier(("python3", "-V")))
            plan, record = workflow.run(Task("Run tests", "Verify", required_capabilities=(Capability.TESTING,)))
            self.assertEqual(plan.agent_id, "codex")
            self.assertEqual(record.verification.status, VerificationStatus.PASSED)
            self.assertEqual(len(runner.calls), 2)

    def test_verification_is_skipped_when_execution_fails(self) -> None:
        class FailingRunner(SequencedRunner):
            def run(self, command, cwd, timeout_seconds):
                self.calls.append(tuple(command))
                return ProcessResult(command, ExecutionStatus.FAILED, "", "failed", 1, 1)

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            runner = FailingRunner()
            agent = CodexAgent(capabilities=frozenset())
            kernel = OrchestratorKernel({agent.agent_id: agent}, JsonlExecutionLogger(workspace / "log.jsonl"), workspace, runner)
            _, record = EngineeringWorkflow(kernel, CapabilitySelector(), CommandVerifier(("python3", "-V"))).run(Task("Run", "Run"))
            self.assertEqual(record.verification.status, VerificationStatus.SKIPPED)
            self.assertEqual(len(runner.calls), 1)

    def test_run_plan_executes_every_step_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            runner = SequencedRunner()
            agent = CodexAgent(capabilities=frozenset({Capability.TESTING}))
            kernel = OrchestratorKernel({agent.agent_id: agent}, JsonlExecutionLogger(workspace / "log.jsonl"), workspace, runner)
            workflow = EngineeringWorkflow(kernel, CapabilitySelector(), CommandVerifier(("python3", "-V")))
            tasks = [Task("Step one", "First", required_capabilities=(Capability.TESTING,)), Task("Step two", "Second", required_capabilities=(Capability.TESTING,))]

            result = workflow.run_plan(tasks)

            self.assertFalse(result.stopped_early)
            self.assertTrue(result.succeeded)
            self.assertEqual(len(result.steps), 2)
            self.assertEqual(len(runner.calls), 4)  # 2 steps x (execute + verify)

    def test_run_plan_stops_at_first_failure_by_default(self) -> None:
        class FirstStepFailsRunner(SequencedRunner):
            def run(self, command, cwd, timeout_seconds):
                self.calls.append(tuple(command))
                status = ExecutionStatus.FAILED if len(self.calls) == 1 else ExecutionStatus.COMPLETED
                return ProcessResult(command, status, "ok" if status is ExecutionStatus.COMPLETED else "", "boom" if status is ExecutionStatus.FAILED else "", 0, 1)

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            runner = FirstStepFailsRunner()
            agent = CodexAgent(capabilities=frozenset())
            kernel = OrchestratorKernel({agent.agent_id: agent}, JsonlExecutionLogger(workspace / "log.jsonl"), workspace, runner)
            workflow = EngineeringWorkflow(kernel, CapabilitySelector(), CommandVerifier(()))
            tasks = [Task("Step one", "First"), Task("Step two", "Second")]

            result = workflow.run_plan(tasks)

            self.assertTrue(result.stopped_early)
            self.assertFalse(result.succeeded)
            self.assertEqual(len(result.steps), 1)

    def test_run_plan_continue_on_failure_runs_every_step(self) -> None:
        class FirstStepFailsRunner(SequencedRunner):
            def run(self, command, cwd, timeout_seconds):
                self.calls.append(tuple(command))
                status = ExecutionStatus.FAILED if len(self.calls) == 1 else ExecutionStatus.COMPLETED
                return ProcessResult(command, status, "ok" if status is ExecutionStatus.COMPLETED else "", "boom" if status is ExecutionStatus.FAILED else "", 0, 1)

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            runner = FirstStepFailsRunner()
            agent = CodexAgent(capabilities=frozenset())
            kernel = OrchestratorKernel({agent.agent_id: agent}, JsonlExecutionLogger(workspace / "log.jsonl"), workspace, runner)
            workflow = EngineeringWorkflow(kernel, CapabilitySelector(), CommandVerifier(()))
            tasks = [Task("Step one", "First"), Task("Step two", "Second")]

            result = workflow.run_plan(tasks, stop_on_failure=False)

            self.assertFalse(result.stopped_early)
            self.assertFalse(result.succeeded)
            self.assertEqual(len(result.steps), 2)


if __name__ == "__main__":
    unittest.main()
