import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.agents import ClaudeCodeAgent, CodexAgent
from adaptive_orchestrator.domain import Capability, Task
from adaptive_orchestrator.history import ExecutionHistory
from adaptive_orchestrator.routing import _MIN_SAMPLES_FOR_FULL_CONFIDENCE as _MIN_SAMPLES
from adaptive_orchestrator.routing import AdaptiveRouter, TaskAnalyzer


class AdaptiveRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agents = (ClaudeCodeAgent(), CodexAgent())

    def test_test_focused_task_selects_codex_with_explanation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = AdaptiveRouter(TaskAnalyzer(), ExecutionHistory(Path(directory) / "history.jsonl")).select(
                Task("Run tests and diagnose failures", "Verify the test suite."), self.agents
            )
            self.assertEqual(plan.agent_id, "codex")
            self.assertIn("testing", plan.analysis["capabilities"])
            self.assertIn("codex", plan.decision["candidate_scores"])

    def test_architecture_task_selects_claude(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = AdaptiveRouter(TaskAnalyzer(), ExecutionHistory(Path(directory) / "history.jsonl")).select(
                Task("Analyze architecture and design a migration plan for this repository.", "Recommend a safe design."), self.agents
            )
            self.assertEqual(plan.agent_id, "claude-code")
            self.assertIn("architecture_reasoning", plan.analysis["capabilities"])

    def test_history_aggregates_execution_and_verification_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.jsonl"
            path.write_text(json.dumps({"agent_id": "codex", "status": "completed", "duration_ms": 10, "verification": {"status": "passed"}}) + "\n")
            metrics = ExecutionHistory(path).metrics_for("codex")
            self.assertEqual(metrics.executions, 1)
            self.assertEqual(metrics.success_rate, 1.0)
            self.assertEqual(metrics.verification_pass_rate, 1.0)

    def test_history_aggregates_cost_only_from_samples_that_have_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.jsonl"
            lines = [
                {"agent_id": "claude-code", "status": "completed", "duration_ms": 10, "metadata": {"cost_usd": 0.02}},
                {"agent_id": "claude-code", "status": "completed", "duration_ms": 10, "metadata": {"cost_usd": 0.04}},
                {"agent_id": "claude-code", "status": "completed", "duration_ms": 10},  # no metadata, e.g. Codex today
            ]
            path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
            metrics = ExecutionHistory(path).metrics_for("claude-code")
            self.assertEqual(metrics.cost_samples, 2)
            self.assertAlmostEqual(metrics.average_cost_usd, 0.03)

    def test_history_average_cost_is_none_without_samples(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            metrics = ExecutionHistory(Path(directory) / "missing.jsonl").metrics_for("codex")
            self.assertIsNone(metrics.average_cost_usd)

    def test_all_failures_is_not_conflated_with_no_history(self) -> None:
        # Regression test: `metrics.success_rate or 0.5` treated a real 0.0 success rate
        # (an agent that has always failed) the same as "no history yet" (also falsy-ish
        # via `or`). A consistently-failing agent must score below one with no history at all.
        with tempfile.TemporaryDirectory() as directory:
            failing_path = Path(directory) / "failing.jsonl"
            failing_lines = [{"agent_id": "codex", "status": "failed", "duration_ms": 10} for _ in range(_MIN_SAMPLES)]
            failing_path.write_text("\n".join(json.dumps(line) for line in failing_lines) + "\n")

            task = Task("Run tests and diagnose failures", "Verify the test suite.")
            failing_plan = AdaptiveRouter(TaskAnalyzer(), ExecutionHistory(failing_path)).select(task, self.agents)
            neutral_plan = AdaptiveRouter(TaskAnalyzer(), ExecutionHistory(Path(directory) / "missing.jsonl")).select(task, self.agents)

            self.assertLess(failing_plan.decision["candidate_scores"]["codex"]["score"], neutral_plan.decision["candidate_scores"]["codex"]["score"])

    def test_single_execution_does_not_fully_trust_historical_evidence(self) -> None:
        # With few samples, evidence should stay close to the neutral prior rather than
        # swing to the raw (100% or 0%) observed rate.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.jsonl"
            path.write_text(json.dumps({"agent_id": "codex", "status": "completed", "duration_ms": 10, "verification": {"status": "passed"}}) + "\n")

            task = Task("Run tests and diagnose failures", "Verify the test suite.")
            plan = AdaptiveRouter(TaskAnalyzer(), ExecutionHistory(path)).select(task, self.agents)
            history = plan.decision["candidate_scores"]["codex"]["history"]

            self.assertEqual(history["confidence"], 0.2)  # 1 of _MIN_SAMPLES_FOR_FULL_CONFIDENCE=5

    def test_cost_limit_penalizes_agent_whose_historical_average_exceeds_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.jsonl"
            lines = [{"agent_id": "codex", "status": "completed", "duration_ms": 10, "metadata": {"cost_usd": 5.0}} for _ in range(_MIN_SAMPLES)]
            path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")

            cheap_task = Task("Run tests and diagnose failures", "Verify the test suite.", cost_limit_usd=1.0)
            unconstrained_task = Task("Run tests and diagnose failures", "Verify the test suite.")

            constrained_plan = AdaptiveRouter(TaskAnalyzer(), ExecutionHistory(path)).select(cheap_task, self.agents)
            unconstrained_plan = AdaptiveRouter(TaskAnalyzer(), ExecutionHistory(path)).select(unconstrained_task, self.agents)

            self.assertIsNotNone(constrained_plan.decision["candidate_scores"]["codex"]["cost_penalty_reason"])
            self.assertIsNone(unconstrained_plan.decision["candidate_scores"]["codex"]["cost_penalty_reason"])
            self.assertLess(
                constrained_plan.decision["candidate_scores"]["codex"]["score"],
                unconstrained_plan.decision["candidate_scores"]["codex"]["score"],
            )

    def test_richer_risk_keywords_raise_analyzed_risk(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = AdaptiveRouter(TaskAnalyzer(), ExecutionHistory(Path(directory) / "history.jsonl")).select(
                Task("Force push to main and rm -rf the old build directory", "Clean up."), self.agents
            )
            self.assertGreater(plan.analysis["risk"], 0)

    def test_long_well_specified_description_does_not_hit_max_difficulty(self) -> None:
        # Regression test: a real dogfooding run gave a thorough, successful, multi-requirement
        # task description max difficulty (5) purely because it was long and mentioned many
        # keyword categories, not because it was genuinely ambiguous or broad in scope. Length
        # and incidentally-inferred capabilities should carry much less weight than what the
        # caller actually declared as required.
        with tempfile.TemporaryDirectory() as directory:
            long_description = " ".join([
                "Add a minimal, structured, append-only engineering memory store to this orchestrator kernel.",
                "In domain.py, add a MemoryEntryType enum and a MemoryEntry dataclass with validation.",
                "Add a new module memory.py with an EngineeringMemoryStore class supporting record and search.",
                "Add two CLI subcommands: memory record and memory search, following the existing argparse style.",
                "Write unit tests covering recording, filtering by type, tag, and keyword, redaction of a summary",
                "that happens to mention the word credential as a test example, and malformed-line tolerance.",
                "Update README.md and docs/architecture.md to document this feature in the existing style.",
            ])
            task = Task(
                long_description,
                "Implement a queryable engineering-memory store, separate from execution telemetry.",
                required_capabilities=(Capability.CODE_GENERATION, Capability.ARCHITECTURE_REASONING),
            )
            plan = AdaptiveRouter(TaskAnalyzer(), ExecutionHistory(Path(directory) / "history.jsonl")).select(task, self.agents)
            self.assertLess(plan.analysis["difficulty"], 5)
            self.assertLess(plan.analysis["risk"], 4)

    def test_difficulty_scales_with_explicitly_required_capabilities_not_text_length(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            short_broad_task = Task(
                "Do it.",
                "Ship it.",
                required_capabilities=(Capability.CODE_GENERATION, Capability.DEBUGGING, Capability.ARCHITECTURE_REASONING, Capability.TESTING),
            )
            plan = AdaptiveRouter(TaskAnalyzer(), ExecutionHistory(Path(directory) / "history.jsonl")).select(short_broad_task, self.agents)
            self.assertGreaterEqual(plan.analysis["difficulty"], 3)

    def test_incidental_keyword_mention_does_not_reach_max_risk(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            task = Task(
                "Write a test asserting that a summary containing the word credential gets redacted.",
                "Verify redaction works.",
            )
            plan = AdaptiveRouter(TaskAnalyzer(), ExecutionHistory(Path(directory) / "history.jsonl")).select(task, self.agents)
            self.assertLess(plan.analysis["risk"], 4)

    def test_explicit_security_review_capability_raises_risk_more_than_incidental_mention(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            explicit_task = Task("Review this change", "Ship it safely", required_capabilities=(Capability.SECURITY_REVIEW,))
            incidental_task = Task("This mentions security in passing", "Ship it")
            router = AdaptiveRouter(TaskAnalyzer(), ExecutionHistory(Path(directory) / "history.jsonl"))
            self.assertGreater(router.select(explicit_task, self.agents).analysis["risk"], router.select(incidental_task, self.agents).analysis["risk"])


if __name__ == "__main__":
    unittest.main()
