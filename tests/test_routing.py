import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.agents import ClaudeCodeAgent, CodexAgent
from adaptive_orchestrator.domain import Capability, Task
from adaptive_orchestrator.history import ExecutionHistory
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


if __name__ == "__main__":
    unittest.main()
