from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.operations.reporting import (
    ExecutionBundle,
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
            bundles = store.bundles()

        self.assertEqual(len(by_execution.attempts), 2)
        self.assertEqual(len(bundles), 1)
        self.assertEqual(by_execution.primary["agent_id"], "codex")
        self.assertEqual(by_execution.outcome["agent_id"], "claude-code")
        self.assertEqual(by_attempt.execution_id, "exec-1")

    def test_indexes_modern_bundles_by_each_groups_last_physical_row(self) -> None:
        first_primary = _record("codex", "attempt-1")
        second_primary = _record("codex", "attempt-3")
        second_primary["execution_id"] = "exec-2"
        first_child = _record("claude-code", "attempt-2", "attempt-1")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "executions.jsonl"
            path.write_text(
                "\n".join(json.dumps(item) for item in (first_primary, second_primary, first_child)),
                encoding="utf-8",
            )
            indexed = ExecutionReportStore(path).indexed_bundles()

        self.assertEqual(
            [(physical_index, bundle.execution_id) for physical_index, bundle in indexed],
            [(3, "exec-1"), (2, "exec-2")],
        )

    def test_supports_legacy_one_based_record_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "executions.jsonl"
            record = _record("codex", "attempt-1")
            record.pop("execution_id")
            path.write_text(json.dumps(record), encoding="utf-8")
            bundle = ExecutionReportStore(path).find("#1")
        self.assertEqual(bundle.execution_id, "legacy-1")

    def test_unique_execution_id_prefix_resolves(self) -> None:
        # The tools print a 36-character UUID and used to demand every character
        # of it back; a leading fragment is what people actually retype.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "executions.jsonl"
            rows = [
                {"execution_id": "abcd1111-aaaa", "attempt_id": "att-1", "agent_id": "codex"},
                {"execution_id": "efgh2222-bbbb", "attempt_id": "att-2", "agent_id": "codex"},
            ]
            path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            store = ExecutionReportStore(path)

            self.assertEqual(store.find("abcd").execution_id, "abcd1111-aaaa")
            self.assertEqual(store.find("efgh2222").execution_id, "efgh2222-bbbb")
            # An exact id still resolves exactly as before.
            self.assertEqual(store.find("abcd1111-aaaa").execution_id, "abcd1111-aaaa")

    def test_ambiguous_prefix_is_reported_rather_than_guessed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "executions.jsonl"
            rows = [
                {"execution_id": "same1111", "attempt_id": "att-1", "agent_id": "codex"},
                {"execution_id": "same2222", "attempt_id": "att-2", "agent_id": "codex"},
            ]
            path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

            with self.assertRaisesRegex(ExecutionLookupError, "Ambiguous execution prefix"):
                ExecutionReportStore(path).find("same")

    def test_short_fragments_are_not_treated_as_prefixes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "executions.jsonl"
            path.write_text(
                json.dumps({"execution_id": "abcdef12", "attempt_id": "a1", "agent_id": "codex"}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ExecutionLookupError, "Execution not found"):
                ExecutionReportStore(path).find("abc")

    def test_an_exact_id_wins_over_a_prefix_of_another(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "executions.jsonl"
            rows = [
                {"execution_id": "abcd", "attempt_id": "att-1", "agent_id": "codex"},
                {"execution_id": "abcd9999", "attempt_id": "att-2", "agent_id": "claude-code"},
            ]
            path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

            self.assertEqual(ExecutionReportStore(path).find("abcd").execution_id, "abcd")

    def test_non_decimal_digit_reference_raises_a_lookup_error(self) -> None:
        # str.isdigit accepts characters int() rejects, such as the superscript
        # "²"; the lookup must still fail as a lookup, not as a ValueError.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "executions.jsonl"
            path.write_text(json.dumps(_record("codex", "attempt-1")), encoding="utf-8")
            store = ExecutionReportStore(path)

            for identifier in ("#²", "#³"):
                with self.subTest(identifier=identifier):
                    with self.assertRaisesRegex(ExecutionLookupError, "Execution not found"):
                        store.find(identifier)

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
        self.assertNotIn("Model", summary)
        self.assertNotIn("Model", markdown)

    def test_surfaces_the_agent_model_when_recorded(self) -> None:
        record = _record("claude-code", "attempt-1")
        record["metadata"] = {"model": "claude-opus-4-8"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "executions.jsonl"
            path.write_text(json.dumps(record), encoding="utf-8")
            bundle = ExecutionReportStore(path).find("exec-1")
        summary = render_text_summary(bundle)
        markdown = render_markdown_report(bundle)
        self.assertIn("Model: claude-opus-4-8", summary)
        self.assertIn("- Model: `claude-opus-4-8`", markdown)
        self.assertIn("`claude-code` (claude-opus-4-8) —", markdown)

    def test_extracts_retry_task_without_prompt_or_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "executions.jsonl"
            record = _record("codex", "attempt-1")
            record["task"]["cost_limit_usd"] = 2.5
            path.write_text(json.dumps(record), encoding="utf-8")
            spec = task_spec_for_retry(ExecutionReportStore(path).find("exec-1"))
        self.assertEqual(spec["description"], "Fix the failing test")
        self.assertEqual(spec["capabilities"], ["debugging", "testing"])
        self.assertEqual(spec["task_id"], "task-1")
        self.assertEqual(spec["cost_limit_usd"], 2.5)
        self.assertNotIn("result", spec)

    def test_groups_idless_standalone_child_with_following_nested_primary(self) -> None:
        child = _record("claude-code", "unused-child-id")
        primary = _record("codex", "unused-primary-id")
        for record in (child, primary):
            record.pop("execution_id")
            record.pop("attempt_id")
            record.pop("parent_attempt_id")
        primary["escalation"] = {"record": dict(child)}

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "executions.jsonl"
            path.write_text(
                "\n".join(json.dumps(item) for item in (child, primary)),
                encoding="utf-8",
            )
            store = ExecutionReportStore(path)
            bundles = store.bundles()
            indexed = store.indexed_bundles()
            from_child_row = store.find("#1")
            from_primary_row = store.find("#2")

        self.assertEqual(len(bundles), 1)
        self.assertEqual([(index, bundle.execution_id) for index, bundle in indexed], [(2, "legacy-2")])
        self.assertEqual(bundles[0].execution_id, "legacy-2")
        self.assertEqual(from_child_row, from_primary_row)
        self.assertEqual(from_primary_row.primary["agent_id"], "codex")
        self.assertEqual(from_primary_row.terminal_attempt["agent_id"], "claude-code")
        self.assertEqual(from_primary_row.attempt_count, 2)
        self.assertIn("1. `codex`", render_markdown_report(from_primary_row))
        self.assertIn("2. `claude-code`", render_markdown_report(from_primary_row))

    def test_escalation_outcome_uses_child_while_task_and_retry_use_primary(self) -> None:
        primary = _record("codex", "attempt-1")
        primary.update({
            "status": "failed",
            "duration_ms": 500,
            "verification": {"status": "failed"},
            "workspace_modified_files": ["src/primary.py"],
            "workspace_git_diff": "-primary\n",
            "result": None,
            "error": "primary boom",
            "escalation_reasons": ["execution_failed"],
        })
        child = _record("claude-code", "attempt-2", "attempt-1")
        child.update({
            "occurred_at": "2026-07-18T00:00:01Z",
            "duration_ms": 2250,
            "workspace_modified_files": ["src/final.py"],
            "workspace_git_diff": "+final\n",
            "result": "Recovered successfully.",
            "error": None,
            "metadata": {"model": "claude-opus-4-8"},
        })
        child["task"] = {**child["task"], "description": "Nested task copy must not replace the original"}
        primary["escalation"] = {
            "reasons": ["execution_failed"],
            "agent_id": "claude-code",
            "record": child,
        }

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "executions.jsonl"
            # The workflow logs the escalation attempt before the primary row,
            # whose nested escalation repeats that same terminal attempt.
            path.write_text(
                "\n".join(json.dumps(item) for item in (child, primary)),
                encoding="utf-8",
            )
            bundle = ExecutionReportStore(path).find("exec-1")

        summary = render_text_summary(bundle)
        markdown = render_markdown_report(bundle, include_diff=True)
        retry = task_spec_for_retry(bundle)

        self.assertEqual(bundle.primary["agent_id"], "codex")
        self.assertEqual(bundle.outcome["attempt_id"], "attempt-2")
        self.assertIn("Task: Fix the failing test", summary)
        self.assertIn("Status: completed", summary)
        self.assertIn("Agent: claude-code", summary)
        self.assertIn("Model: claude-opus-4-8", summary)
        self.assertIn("Verification: passed", summary)
        self.assertIn("Attempts: 2", summary)
        self.assertIn("Duration: 2.2s", summary)
        self.assertIn("Modified: src/final.py", summary)

        self.assertIn("- Status: `completed`", markdown)
        self.assertIn("- Agent: `claude-code`", markdown)
        self.assertIn("- Recorded at: `2026-07-18T00:00:01Z`", markdown)
        self.assertIn("Fix the failing test", markdown)
        self.assertIn("Selected agent: `codex`", markdown)
        self.assertLess(markdown.index("1. `codex`"), markdown.index("2. `claude-code`"))
        self.assertIn("Recovered successfully.", markdown)
        self.assertNotIn("primary boom", markdown)
        self.assertIn("`src/final.py`", markdown)
        self.assertNotIn("`src/primary.py`", markdown)
        self.assertIn("+final", markdown)
        self.assertNotIn("-primary", markdown)
        self.assertEqual(retry["description"], "Fix the failing test")
        self.assertEqual(retry["task_id"], "task-1")

    def test_nested_escalation_supplies_outcome_when_child_row_is_missing(self) -> None:
        primary = _record("codex", "attempt-1")
        primary.update({
            "status": "failed",
            "verification": {"status": "failed"},
            "result": None,
            "error": "first attempt failed",
        })
        child = _record("claude-code", "attempt-2", "attempt-1")
        child["result"] = "Nested recovery"
        primary["escalation"] = {"record": child}

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "executions.jsonl"
            path.write_text(json.dumps(primary), encoding="utf-8")
            bundle = ExecutionReportStore(path).find("exec-1")

        self.assertEqual(len(bundle.attempts), 1)
        self.assertEqual(bundle.outcome["attempt_id"], "attempt-2")
        self.assertIn("Status: completed", render_text_summary(bundle))
        markdown = render_markdown_report(bundle)
        self.assertIn("- Attempts: 2", markdown)
        self.assertIn("1. `codex`", markdown)
        self.assertIn("2. `claude-code`", markdown)
        self.assertIn("Nested recovery", markdown)

    def test_failed_advisory_escalation_does_not_erase_successful_primary_outcome(self) -> None:
        primary = _record("codex", "attempt-1")
        child = _record("claude-code", "attempt-2", "attempt-1")
        child.update({
            "status": "failed",
            "verification": {"status": "failed"},
            "workspace_modified_files": ["src/primary.py", "src/child.py"],
            "workspace_git_diff": "+child change\n",
            "result": None,
            "error": "advisory escalation failed",
        })
        primary["workspace_modified_files"] = ["src/primary.py"]
        primary["workspace_git_diff"] = "+primary change\n"
        primary["escalation"] = {"record": child}

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "executions.jsonl"
            path.write_text(
                "\n".join(json.dumps(item) for item in (child, primary)),
                encoding="utf-8",
            )
            bundle = ExecutionReportStore(path).find("exec-1")

        self.assertEqual(bundle.terminal_attempt["attempt_id"], "attempt-2")
        self.assertEqual(bundle.outcome["attempt_id"], "attempt-1")
        summary = render_text_summary(bundle)
        markdown = render_markdown_report(bundle, include_diff=True)
        self.assertIn("Status: completed", summary)
        self.assertIn("Agent: codex", summary)
        self.assertIn("Terminal attempt: failed by claude-code", summary)
        self.assertIn("Modified: src/primary.py, src/child.py", summary)
        self.assertIn("- Attempts: 2", markdown)
        self.assertLess(markdown.index("1. `codex`"), markdown.index("2. `claude-code`"))
        self.assertIn("- Terminal escalation: `failed` by `claude-code`", markdown)
        self.assertIn("`src/child.py`", markdown)
        self.assertIn("## Terminal escalation error", markdown)
        self.assertIn("advisory escalation failed", markdown)
        self.assertIn("+child change", markdown)
        self.assertNotIn("+primary change", markdown)

    def test_nested_escalation_is_authoritative_over_a_stale_child_row(self) -> None:
        primary = _record("codex", "attempt-1")
        primary.update({"status": "failed", "verification": {"status": "failed"}})
        nested = _record("claude-code", "attempt-2", "attempt-1")
        stale_child = {
            **nested,
            "status": "failed",
            "verification": {"status": "failed"},
        }
        primary["escalation"] = {"record": nested}

        bundle = ExecutionBundle("exec-1", (stale_child, primary))

        self.assertEqual(bundle.terminal_attempt["status"], "completed")
        self.assertEqual(bundle.outcome["status"], "completed")
        self.assertIn("Status: completed", render_text_summary(bundle))


if __name__ == "__main__":
    unittest.main()
