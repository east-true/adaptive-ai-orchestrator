import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.agents import ClaudeCodeAgent, CodexAgent
from adaptive_orchestrator.domain import Capability, ExecutionStatus, Task, VerificationStatus
from adaptive_orchestrator.escalation import EscalationPolicy
from adaptive_orchestrator.kernel import OrchestratorKernel
from adaptive_orchestrator.logging import JsonlExecutionLogger
from adaptive_orchestrator.planning import CapabilitySelector
from adaptive_orchestrator.process_runner import ProcessResult
from adaptive_orchestrator.verification import CommandVerifier
from adaptive_orchestrator.workflow import EngineeringWorkflow


class EscalationPolicyTests(unittest.TestCase):
    def test_completed_and_passed_never_escalates(self) -> None:
        decision = EscalationPolicy().decide({"risk": 0, "uncertainty": 0}, ExecutionStatus.COMPLETED, VerificationStatus.PASSED)
        self.assertFalse(decision.should_escalate)
        self.assertEqual(decision.reasons, ())

    def test_execution_failure_escalates_regardless_of_analysis(self) -> None:
        decision = EscalationPolicy().decide(None, ExecutionStatus.FAILED, VerificationStatus.SKIPPED)
        self.assertTrue(decision.should_escalate)
        self.assertIn("execution_failed", decision.reasons)

    def test_verification_failure_escalates(self) -> None:
        decision = EscalationPolicy().decide({}, ExecutionStatus.COMPLETED, VerificationStatus.FAILED)
        self.assertTrue(decision.should_escalate)
        self.assertEqual(decision.reasons, ("verification_failed",))

    def test_high_risk_or_uncertainty_escalates_even_on_success(self) -> None:
        decision = EscalationPolicy(risk_threshold=3).decide({"risk": 4, "uncertainty": 0}, ExecutionStatus.COMPLETED, VerificationStatus.PASSED)
        self.assertTrue(decision.should_escalate)
        self.assertEqual(decision.reasons, ("high_risk",))

    def test_below_threshold_does_not_escalate(self) -> None:
        decision = EscalationPolicy(risk_threshold=3, uncertainty_threshold=3, difficulty_threshold=4).decide(
            {"risk": 2, "uncertainty": 2, "difficulty": 3}, ExecutionStatus.COMPLETED, VerificationStatus.PASSED
        )
        self.assertFalse(decision.should_escalate)

    def test_high_difficulty_escalates_even_on_success(self) -> None:
        decision = EscalationPolicy(difficulty_threshold=4).decide({"risk": 0, "uncertainty": 0, "difficulty": 5}, ExecutionStatus.COMPLETED, VerificationStatus.PASSED)
        self.assertTrue(decision.should_escalate)
        self.assertEqual(decision.reasons, ("high_difficulty",))


class AgentSwitchingRunner:
    """Fails whichever agent's CLI is named first in `failing_executables`, succeeds otherwise."""

    def __init__(self, failing_executables: set[str]) -> None:
        self.failing_executables = failing_executables
        self.calls: list[tuple[str, ...]] = []

    def run(self, command, cwd, timeout_seconds):
        self.calls.append(tuple(command))
        if command[0] in self.failing_executables:
            return ProcessResult(command, ExecutionStatus.FAILED, "", "boom", 1, 5)
        return ProcessResult(command, ExecutionStatus.COMPLETED, "ok", "", 0, 5)


class WorkflowEscalationTests(unittest.TestCase):
    def _kernel(self, runner, workspace, agent_order=("codex", "claude-code")):
        agents = {"codex": CodexAgent(), "claude-code": ClaudeCodeAgent()}
        ordered = {agent_id: agents[agent_id] for agent_id in agent_order}
        return OrchestratorKernel(ordered, JsonlExecutionLogger(workspace / "log.jsonl"), workspace, runner)

    def test_escalates_to_second_agent_after_execution_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            runner = AgentSwitchingRunner({"codex"})
            kernel = self._kernel(runner, workspace)
            workflow = EngineeringWorkflow(kernel, CapabilitySelector(), CommandVerifier(()), EscalationPolicy())
            plan, record = workflow.run(Task("Fix a production bug", "Fix it"))

            self.assertEqual(plan.agent_id, "codex")
            self.assertEqual(record.status, ExecutionStatus.FAILED)
            self.assertIsNotNone(record.escalation)
            self.assertEqual(record.escalation.agent_id, "claude-code")
            self.assertIn("execution_failed", record.escalation.reasons)
            self.assertEqual(record.escalation.record.status, ExecutionStatus.COMPLETED)
            self.assertEqual(len(runner.calls), 2)

    def test_successful_run_does_not_escalate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            runner = AgentSwitchingRunner(set())
            kernel = self._kernel(runner, workspace)
            workflow = EngineeringWorkflow(kernel, CapabilitySelector(), CommandVerifier(()), EscalationPolicy())
            _, record = workflow.run(Task("Fix a bug", "Fix it"))

            self.assertIsNone(record.escalation)
            self.assertEqual(len(runner.calls), 1)

    def test_explicit_agent_request_is_never_escalated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            runner = AgentSwitchingRunner({"codex"})
            kernel = self._kernel(runner, workspace)
            workflow = EngineeringWorkflow(kernel, CapabilitySelector(), CommandVerifier(()), EscalationPolicy())
            _, record = workflow.run(Task("Fix a bug", "Fix it"), requested_agent_id="codex")

            self.assertEqual(record.status, ExecutionStatus.FAILED)
            self.assertIsNone(record.escalation)
            self.assertEqual(len(runner.calls), 1)

    def test_no_other_capable_agent_leaves_escalation_unset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            runner = AgentSwitchingRunner({"codex"})
            kernel = OrchestratorKernel({"codex": CodexAgent()}, JsonlExecutionLogger(workspace / "log.jsonl"), workspace, runner)
            workflow = EngineeringWorkflow(kernel, CapabilitySelector(), CommandVerifier(()), EscalationPolicy())
            _, record = workflow.run(Task("Fix a bug", "Fix it"))

            self.assertEqual(record.status, ExecutionStatus.FAILED)
            self.assertIsNone(record.escalation)

    def test_escalation_disabled_when_no_policy_configured(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            runner = AgentSwitchingRunner({"codex"})
            kernel = self._kernel(runner, workspace)
            workflow = EngineeringWorkflow(kernel, CapabilitySelector(), CommandVerifier(()))
            _, record = workflow.run(Task("Fix a bug", "Fix it"))

            self.assertIsNone(record.escalation)
            self.assertEqual(len(runner.calls), 1)


if __name__ == "__main__":
    unittest.main()
