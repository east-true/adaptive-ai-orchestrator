import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.agents import CodexAgent
from adaptive_orchestrator.domain import Capability, EvaluatorRole, EvaluatorSpec, ExecutionStatus, Task, VerificationStatus
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
            self.assertEqual(record.policy_version, "legacy-biased")
            self.assertEqual(record.selection_mode, "exploit")
            self.assertEqual(record.cohort, "legacy")
            self.assertFalse(record.routing_evidence_eligible)
            self.assertEqual(len(record.execution_id or ""), 36)
            self.assertEqual(len(record.attempt_id or ""), 36)
            self.assertEqual(len(record.config_hash or ""), 64)
            self.assertEqual([item.role for item in record.evaluations], [EvaluatorRole.RELIABILITY, EvaluatorRole.CONSTRAINT])
            self.assertTrue(record.evaluation_projection["reliability"]["observed"])
            self.assertTrue(record.evaluation_projection["constraint"]["observed"])
            self.assertFalse(record.evaluation_projection["quality"]["observed"])

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
            self.assertTrue(record.evaluations[0].observed)
            self.assertFalse(record.evaluations[1].observed)
            self.assertFalse(record.evaluation_projection["quality"]["observed"])

    def test_explicit_quality_evaluator_is_separate_from_constraint_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            artifact = root / "held-out.py"
            artifact.write_text("# held-out quality evaluator\n")
            artifact.chmod(0o444)
            runner = SequencedRunner()
            agent = CodexAgent(capabilities=frozenset())
            kernel = OrchestratorKernel({agent.agent_id: agent}, JsonlExecutionLogger(workspace / "log.jsonl"), workspace, runner)
            quality = EvaluatorSpec(
                "held-out-quality",
                "v1",
                EvaluatorRole.QUALITY,
                "task objective",
                ("python3", str(artifact)),
                evidence_scope="held-out acceptance test",
                artifact_paths=(str(artifact),),
            )
            workflow = EngineeringWorkflow(
                kernel,
                CapabilitySelector(),
                CommandVerifier(("python3", "-V"), evaluator_specs=(quality,)),
            )

            _, record = workflow.run(Task("Implement feature", "Acceptance test passes"))

            self.assertEqual(record.verification.status, VerificationStatus.PASSED)
            self.assertEqual([item.role for item in record.evaluations], [
                EvaluatorRole.RELIABILITY,
                EvaluatorRole.CONSTRAINT,
                EvaluatorRole.QUALITY,
            ])
            self.assertEqual(record.evaluation_projection["quality"]["scores"], [1.0])
            self.assertEqual(len(runner.calls), 3)

    def test_same_config_hash_has_unique_execution_and_attempt_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            runner = SequencedRunner()
            agent = CodexAgent(capabilities=frozenset())
            kernel = OrchestratorKernel({agent.agent_id: agent}, JsonlExecutionLogger(workspace / "log.jsonl"), workspace, runner)
            workflow = EngineeringWorkflow(kernel, CapabilitySelector(), CommandVerifier(()))
            task = Task("Run", "Run")

            _, first = workflow.run(task)
            _, second = workflow.run(task)

            self.assertEqual(first.config_hash, second.config_hash)
            self.assertNotEqual(first.execution_id, second.execution_id)
            self.assertNotEqual(first.attempt_id, second.attempt_id)

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
