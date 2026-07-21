import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.execution.agents import ClaudeCodeAgent, CodexAgent
from adaptive_orchestrator.core.domain import Capability, Task
from adaptive_orchestrator.infrastructure.events import JsonlEventStore, LifecycleEventType
from adaptive_orchestrator.infrastructure.history import ExecutionHistory
from adaptive_orchestrator.routing.analysis import TaskAnalyzer
from adaptive_orchestrator.routing.context import RoutingContextBuilder
from adaptive_orchestrator.routing.policy import CorrectedStaticRouter, RoutingPolicyRouter, ShadowBaselineEvaluator
from adaptive_orchestrator.routing.state import LifecycleRecorder


class CorrectedStaticRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agents = (ClaudeCodeAgent(), CodexAgent())

    def test_selects_explicit_baseline_without_vendor_skill_claim(self) -> None:
        router = CorrectedStaticRouter(TaskAnalyzer(), "claude-code")
        plan = router.select(Task("Write code and tests", "Implement it"), self.agents)

        self.assertEqual(plan.agent_id, "claude-code")
        self.assertEqual(plan.decision["candidate_scores"]["claude-code"]["score"], None)
        self.assertEqual(plan.decision["candidate_scores"]["codex"]["measured_samples"], 0)
        self.assertIn("no vendor skill difference", plan.rationale.lower())

    def test_inferred_capability_is_context_not_eligibility(self) -> None:
        agents = (
            ClaudeCodeAgent(capabilities=frozenset({Capability.ARCHITECTURE_REASONING})),
            CodexAgent(capabilities=frozenset()),
        )
        plan = CorrectedStaticRouter(TaskAnalyzer(), "codex").select(
            Task("Review the architecture", "Recommend a design"),
            agents,
        )

        self.assertEqual(plan.agent_id, "codex")
        self.assertIn("architecture_reasoning", plan.decision["routing_context"]["inferred_capabilities"])

    def test_required_capability_remains_hard_eligibility(self) -> None:
        router = CorrectedStaticRouter(TaskAnalyzer(), "codex")
        incapable = (CodexAgent(capabilities=frozenset()),)
        with self.assertRaisesRegex(ValueError, "explicitly required"):
            router.select(Task("Run tests", "Pass", required_capabilities=(Capability.TESTING,)), incapable)

    def test_manual_request_overrides_configured_baseline(self) -> None:
        plan = CorrectedStaticRouter(TaskAnalyzer(), "claude-code").select(Task("Do work", "Done"), self.agents, "codex")
        self.assertEqual(plan.agent_id, "codex")


class RoutingContextTests(unittest.TestCase):
    def test_context_separates_required_inferred_and_language(self) -> None:
        task = Task("테스트를 debug", "오류를 fix", required_capabilities=(Capability.TESTING,))
        analysis = TaskAnalyzer().analyze(task)
        context = RoutingContextBuilder().build(
            task,
            inferred_capabilities=analysis.inferred_capabilities,
            difficulty=analysis.difficulty,
            risk=analysis.risk,
            uncertainty=analysis.uncertainty,
            objective_evaluator_available=True,
            constraint_evaluator_count=2,
            environment_epoch="epoch-1",
        )

        self.assertEqual(context.required_capabilities, ("testing",))
        self.assertIn("debugging", context.inferred_capabilities)
        self.assertEqual(context.instruction_language, "mixed")
        self.assertEqual(context.environment_epoch, "epoch-1")


class ShadowBaselineTests(unittest.TestCase):
    def _context(self):
        task = Task("Run tests", "Verify")
        analysis = TaskAnalyzer().analyze(task)
        return RoutingContextBuilder().build(
            task,
            inferred_capabilities=analysis.inferred_capabilities,
            difficulty=analysis.difficulty,
            risk=analysis.risk,
            uncertainty=analysis.uncertainty,
            objective_evaluator_available=True,
            constraint_evaluator_count=0,
            environment_epoch="epoch-1",
        )

    def test_shadow_refuses_legacy_or_missing_quality_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.jsonl"
            path.write_text(json.dumps({
                "agent_id": "codex",
                "cohort": "legacy",
                "environment_epoch": "epoch-1",
                "evaluations": [{"role": "quality", "observed": True, "score": 1.0}],
            }) + "\n")
            decisions = ShadowBaselineEvaluator(ExecutionHistory(path), "codex", 7, "epoch-1").evaluate(
                self._context(),
                (ClaudeCodeAgent(), CodexAgent()),
            )

            self.assertFalse(decisions["best-single"]["available"])
            self.assertFalse(decisions["stratified-beta-greedy"]["available"])
            self.assertEqual(decisions["corrected-static"]["selected_agent"], "codex")

    def test_best_single_uses_only_typed_paired_quality_in_same_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.jsonl"
            context = self._context()
            rows = [
                {
                    "agent_id": "claude-code",
                    "agent_base_id": "claude-code",
                    "cohort": "paired",
                    "environment_epoch": "epoch-1",
                    "routing_context": context.as_dict(),
                    "evaluations": [{"role": "quality", "observed": True, "score": 1.0}],
                },
                {
                    "agent_id": "codex",
                    "agent_base_id": "codex",
                    "cohort": "paired",
                    "environment_epoch": "epoch-1",
                    "routing_context": context.as_dict(),
                    "evaluations": [{"role": "quality", "observed": True, "score": 0.0}],
                },
                {
                    "agent_id": "codex",
                    "agent_base_id": "codex",
                    "cohort": "paired",
                    "environment_epoch": "other-epoch",
                    "routing_context": context.as_dict(),
                    "evaluations": [{"role": "quality", "observed": True, "score": 1.0}],
                },
            ]
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

            decisions = ShadowBaselineEvaluator(ExecutionHistory(path), "codex", 7, "epoch-1").evaluate(
                context,
                (ClaudeCodeAgent(), CodexAgent()),
            )

            self.assertEqual(decisions["best-single"]["selected_agent"], "claude-code")
            self.assertEqual(decisions["stratified-beta-greedy"]["selected_agent"], "claude-code")
            self.assertEqual(decisions["best-single"]["backoff_level"], "exact-agent-environment")

    def test_shadow_decisions_are_deterministic_for_same_seed_and_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            history = ExecutionHistory(Path(directory) / "missing.jsonl")
            evaluator = ShadowBaselineEvaluator(history, "codex", 42, "epoch-1")
            context = self._context()
            first = evaluator.evaluate(context, (ClaudeCodeAgent(), CodexAgent()))
            second = evaluator.evaluate(context, (ClaudeCodeAgent(), CodexAgent()))
            self.assertEqual(first, second)
            self.assertTrue(first["random-safe"]["shadow_only"])

    def test_stratified_baseline_has_deterministic_exact_then_base_backoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.jsonl"
            context = self._context()
            row = {
                "agent_id": "claude-code:sonnet",
                "agent_base_id": "claude-code",
                "cohort": "paired",
                "environment_epoch": "epoch-1",
                "routing_context": {**context.as_dict(), "instruction_language": "ko"},
                "evaluations": [{"role": "quality", "observed": True, "score": 1.0}],
            }
            path.write_text(json.dumps(row) + "\n")
            decisions = ShadowBaselineEvaluator(ExecutionHistory(path), "codex", 7, "epoch-1").evaluate(
                context,
                (ClaudeCodeAgent(model="opus"), CodexAgent()),
            )

            self.assertEqual(decisions["stratified-beta-greedy"]["selected_agent"], "claude-code:opus")
            self.assertEqual(decisions["stratified-beta-greedy"]["backoff_level"], "base-agent-task")

    def test_policy_wrapper_records_context_and_shadows_without_changing_active_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            history = ExecutionHistory(Path(directory) / "missing.jsonl")
            recorder = LifecycleRecorder(JsonlEventStore(Path(directory) / "control" / "events.jsonl"))
            router = RoutingPolicyRouter(
                "static",
                TaskAnalyzer(),
                history,
                baseline_agent_id="claude-code",
                shadow=True,
                seed=3,
                environment_epoch="epoch-1",
                objective_evaluator_available=True,
                constraint_evaluator_count=1,
                routing_state_provider=recorder.rebuild_state,
            )

            first = router.select(Task("Run tests", "Verify"), (ClaudeCodeAgent(), CodexAgent()))
            second = router.select(Task("Run tests", "Verify"), (ClaudeCodeAgent(), CodexAgent()))

            self.assertEqual(first.agent_id, "claude-code")
            self.assertEqual(first.decision, second.decision)
            self.assertEqual(first.decision["routing_context"]["schema_version"], "routing-context-v1")
            self.assertIn("best-single", first.decision["shadow_decisions"])
            self.assertIn("legacy-adaptive", first.decision["shadow_decisions"])
            self.assertIn("legacy-static-profile", first.decision["shadow_decisions"])
            self.assertFalse(first.decision["shadow_decisions"]["legacy-adaptive"]["evidence_trusted"])

    def test_protected_event_state_takes_precedence_over_legacy_execution_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history_path = root / "history.jsonl"
            context = self._context()
            history_path.write_text(json.dumps({
                "agent_id": "codex",
                "agent_base_id": "codex",
                "cohort": "paired",
                "environment_epoch": "epoch-1",
                "routing_context": context.as_dict(),
                "evaluations": [{"role": "quality", "observed": True, "score": 1.0}],
            }) + "\n")
            recorder = LifecycleRecorder(JsonlEventStore(root / "control" / "events.jsonl"))
            for index, (agent_id, base_id, score) in enumerate((
                ("claude-code", "claude-code", 1.0),
                ("codex", "codex", 0.0),
            )):
                common = {"execution_id": f"execution-{index}", "task_id": f"task-{index}", "attempt_id": f"attempt-{index}"}
                recorder.record(LifecycleEventType.SELECTION_MADE, payload={
                    "selected_agent": agent_id,
                    "selected_agent_base_id": base_id,
                    "cohort": "paired",
                    "context_features": context.as_dict(),
                    "eligible_candidates": [agent_id],
                    "ineligible_reasons": {},
                    "candidate_probabilities": {agent_id: 1.0},
                    "selected_probability": 1.0,
                }, **common)
                recorder.record(LifecycleEventType.EXECUTION_STARTED, **common)
                recorder.record(LifecycleEventType.EXECUTION_TERMINAL, payload={"status": "completed"}, **common)
                recorder.record(LifecycleEventType.EVALUATION_COMPLETED, payload={
                    "role": "quality", "observed": True, "score": score,
                }, **common)
                recorder.record(LifecycleEventType.OUTCOME_FINALIZED, payload={"status": "completed"}, **common)

            decisions = ShadowBaselineEvaluator(
                ExecutionHistory(history_path),
                "codex",
                7,
                "epoch-1",
                recorder.rebuild_state(),
            ).evaluate(context, (ClaudeCodeAgent(), CodexAgent()))

            self.assertEqual(decisions["best-single"]["selected_agent"], "claude-code")


if __name__ == "__main__":
    unittest.main()
