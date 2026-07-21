from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.operations.reporting import (
    ExecutionLookupError,
    ExecutionReportStore,
    render_markdown_report,
    render_text_summary,
    task_spec_for_retry,
)


def _record(agent: str, attempt: str, parent: str | None = None) -> dict:
    return {
        "execution_id": "exec-1",
        "attempt_id": attempt,
        "parent_attempt_id": parent,
        "occurred_at": "2026-07-18T00:00:00Z",
        "task": {
            "description": "Fix the failing test",
            "objective": "Tests pass",
            "constraints": ["Do not change the API"],
            "required_capabilities": ["debugging", "testing"],
            "priority": "high",
            "time_limit_seconds": 120,
            "task_id": "task-1",
        },
        "agent_id": agent,
        "status": "completed",
        "duration_ms": 1250,
        "verification": {"status": "passed"},
        "workspace_modified_files": ["src/example.py"],
        "result": "Fixed it.",
        "task_analysis": {"difficulty": 2, "risk": 1, "uncertainty": 1},
        "routing_decision": {"selected_agent": "codex"},
    }


class ExecutionReportStoreTests(unittest.TestCase):
    def test_groups_attempts_by_execution_and_selects_primary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "executions.jsonl"
            records = [_record("codex", "attempt-1"), _record("claude-code", "attempt-2", "attempt-1")]
            path.write_text("\n".join(json.dumps(item) for item in records) + "\n{broken", encoding="utf-8")
            store = ExecutionReportStore(path)

            by_execution = store.find("exec-1")
            by_attempt = store.find("attempt-2")

        self.assertEqual(len(by_execution.attempts), 2)
        self.assertEqual(by_execution.primary["agent_id"], "codex")
        self.assertEqual(by_attempt.execution_id, "exec-1")

    def test_supports_legacy_one_based_record_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "executions.jsonl"
            record = _record("codex", "attempt-1")
            record.pop("execution_id")
            path.write_text(json.dumps(record), encoding="utf-8")
            bundle = ExecutionReportStore(path).find("#1")
        self.assertEqual(bundle.execution_id, "legacy-1")

    def test_missing_execution_has_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ExecutionLookupError, "No executions"):
                ExecutionReportStore(Path(directory) / "missing.jsonl").find("exec-1")

    def test_renders_human_summary_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "executions.jsonl"
            path.write_text(json.dumps(_record("codex", "attempt-1")), encoding="utf-8")
            bundle = ExecutionReportStore(path).find("exec-1")
        summary = render_text_summary(bundle)
        markdown = render_markdown_report(bundle)
        self.assertIn("Status: completed", summary)
        self.assertIn("Modified: src/example.py", summary)
        self.assertIn("# Execution exec-1", markdown)
        self.assertIn("## Agent result", markdown)
        self.assertNotIn("Recorded workspace diff", markdown)

    def test_extracts_retry_task_without_prompt_or_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "executions.jsonl"
            path.write_text(json.dumps(_record("codex", "attempt-1")), encoding="utf-8")
            spec = task_spec_for_retry(ExecutionReportStore(path).find("exec-1"))
        self.assertEqual(spec["description"], "Fix the failing test")
        self.assertEqual(spec["capabilities"], ["debugging", "testing"])
        self.assertEqual(spec["task_id"], "task-1")
        self.assertNotIn("result", spec)


if __name__ == "__main__":
    unittest.main()
