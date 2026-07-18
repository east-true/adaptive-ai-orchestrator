from __future__ import annotations

import json
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = ROOT / "experiments" / "phase2b-candidate-ledger-v1.json"
EXPECTED_INCLUSION_RULES = {
    "license-or-use-basis",
    "exact-base-resolvable",
    "single-bounded-task",
    "native-language-source",
    "low-risk-isolated-execution",
    "no-network-secret-push-production",
    "objective-evaluator-feasible",
    "gold-and-evaluator-hideable",
    "reproducible-within-budget",
    "selection-independent-of-agent-results",
    "not-used-for-confirmatory-round",
}
EXPECTED_SCREENING_FIELDS = {
    rule_id.replace("-", "_") for rule_id in EXPECTED_INCLUSION_RULES
}


class Phase2bCandidateLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))

    def test_references_unique_source_rows(self) -> None:
        pools = self.ledger["source_pools"]
        candidates = self.ledger["candidates"]
        pool_ids = [pool["source_pool_id"] for pool in pools]
        candidate_ids = [candidate["candidate_id"] for candidate in candidates]

        self.assertEqual(len(pool_ids), len(set(pool_ids)))
        self.assertEqual(len(candidate_ids), len(set(candidate_ids)))
        self.assertTrue(
            all(candidate["source_pool_id"] in pool_ids for candidate in candidates)
        )
        self.assertTrue(all(candidate["changed_files"] for candidate in candidates))
        self.assertFalse(self.ledger["agent_results_observed"])

    def test_selected_rows_are_fully_screened(self) -> None:
        self.assertEqual(
            set(self.ledger["inclusion_rule_ids"]),
            EXPECTED_INCLUSION_RULES,
        )

        for candidate in self.ledger["candidates"]:
            decision = candidate["decision"]
            triggered = candidate["exclusion_rule_ids_triggered"]
            if decision == "excluded":
                self.assertTrue(triggered)
            else:
                self.assertFalse(triggered)
            if decision != "selected-for-task-authoring":
                continue
            self.assertTrue(candidate["source_statement_available"])
            self.assertTrue(candidate["task_statement_hash"])
            self.assertTrue(candidate["base_revision"])
            self.assertTrue(candidate["base_tree_hash"])
            self.assertEqual(
                set(candidate["screening"]),
                EXPECTED_SCREENING_FIELDS,
            )
            self.assertEqual(set(candidate["screening"].values()), {"pass"})

    def test_summary_is_recomputed_from_rows(self) -> None:
        candidates = self.ledger["candidates"]
        summary = self.ledger["summary"]
        decisions = Counter(candidate["decision"] for candidate in candidates)
        languages = Counter(
            candidate["provisional_classification"]["instruction_language"]
            for candidate in candidates
        )
        categories = Counter(
            candidate["provisional_classification"]["task_category"]
            for candidate in candidates
        )

        self.assertEqual(summary["candidate_count"], len(candidates))
        self.assertEqual(summary["screening_count"], decisions["screening"])
        self.assertEqual(summary["excluded_count"], decisions["excluded"])
        self.assertEqual(
            summary["selected_for_task_authoring_count"],
            decisions["selected-for-task-authoring"],
        )
        self.assertEqual(
            summary["language_assignment_counts"],
            {
                "ko": languages["ko"],
                "en": languages["en"],
                "mixed": languages["mixed"],
                "unassigned": languages[None],
            },
        )
        self.assertEqual(
            summary["category_assignment_counts"],
            {
                "implementation": categories["implementation"],
                "debugging": categories["debugging"],
                "testing": categories["testing"],
                "refactoring": categories["refactoring"],
                "repository-analysis-planning": categories[
                    "repository-analysis-planning"
                ],
                "unassigned": categories[None],
            },
        )

    def test_preserves_complete_source_pool_counts(self) -> None:
        by_pool = Counter(
            candidate["source_pool_id"] for candidate in self.ledger["candidates"]
        )

        self.assertEqual(
            by_pool,
            {
                "aao-local-history-through-0e32241": 36,
                "swebench-multilingual-at-2b7aced": 300,
            },
        )


if __name__ == "__main__":
    unittest.main()
