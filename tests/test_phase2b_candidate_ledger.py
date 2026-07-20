from __future__ import annotations

import json
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = ROOT / "experiments" / "phase2b-candidate-ledger-v1.json"
LICENSE_PROBE_PATH = ROOT / "experiments" / "phase2b-license-probe-2026-07-19.json"
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
EXPECTED_EXCLUSION_RULES = [
    "no-parent-or-exact-base",
    "task-source-unavailable-or-underspecified",
    "license-or-use-basis-unavailable",
    "translation-only",
    "multiple-coupled-issues",
    "unsafe-or-external-side-effect",
    "subjective-only-evaluation",
    "broken-or-flaky-fixture",
    "gold-or-evaluator-leakage",
    "resource-budget-exceeded",
    "selected-after-agent-result",
    "previous-paired-task-reuse",
]


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
        self.assertEqual(
            len(candidates),
            len({candidate["source_reference"] for candidate in candidates}),
        )
        self.assertTrue(
            all(candidate["source_pool_id"] in pool_ids for candidate in candidates)
        )
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
            self.assertTrue(candidate["solution_artifact_hash"])
            self.assertTrue(candidate["changed_files"])
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
                "github-korean-bearing-issues-2026-07-19": 411,
                "github-explicit-multilingual-issues-2026-07-19": 383,
            },
        )

    def test_preserves_korean_bearing_probe_audit(self) -> None:
        candidates = [
            candidate
            for candidate in self.ledger["candidates"]
            if candidate["source_pool_id"]
            == "github-korean-bearing-issues-2026-07-19"
        ]
        reviewed = [
            candidate
            for candidate in candidates
            if candidate["provisional_classification"]["task_category"] is not None
        ]

        self.assertEqual(len(candidates), 411)
        self.assertEqual(len(reviewed), 29)
        self.assertEqual(
            Counter(candidate["source_kind"] for candidate in candidates),
            {"public-issue-discovery": 384, "public-issue-pr-pair": 27},
        )
        self.assertEqual(
            Counter(candidate["decision"] for candidate in reviewed),
            {"screening": 2, "excluded": 27},
        )
        self.assertEqual(
            Counter(
                candidate["provisional_classification"]["instruction_language"]
                for candidate in reviewed
            ),
            {"ko": 28, "mixed": 1},
        )
        self.assertEqual(
            {
                candidate["candidate_id"]
                for candidate in candidates
                if candidate["screening"]["exact_base_resolvable"] == "pass"
            },
            {
                "ghko-Chigo55--Docker-Compose-issue-38",
                "ghko-SeoyunL--factlog-academic-issue-314",
                "ghko-ProudlyOffbeat--ProudlyOffbeat-MVP-iOS-issue-93",
                "ghko-minacle--swift-tui-issue-18",
                # Resolved 2026-07-20 from the mechanical prefilter's promising rows.
                # A resolved base is not a selection: all of these stay screening.
                "ghko-SeoyunL--factlog-academic-issue-342",
                "ghko-ohah--zntc-issue-4564",
                "ghko-ohah--zntc-issue-4563",
                "ghko-ohah--zntc-issue-4553",
                "ghko-itismyfield--AgentDesk-issue-4606",
            },
        )

    def test_license_probe_is_never_treated_as_terminal(self) -> None:
        probe = json.loads(LICENSE_PROBE_PATH.read_text(encoding="utf-8"))

        # The probe reads default-branch HEAD, not a candidate's pinned revision,
        # so it may order work but must never settle license-or-use-basis.
        self.assertFalse(probe["terminal_status"])
        self.assertTrue(probe["terminal_status_note"])

        probed = {entry["repository"] for entry in probe["entries"]}
        self.assertEqual(len(probed), len(probe["entries"]))

        for entry in probe["entries"]:
            self.assertIn(
                entry["signal"],
                {"license-artifact-or-spdx-present", "none-observed"},
            )
            self.assertIn(
                entry["probe_method"],
                set(probe["probe_methods"]),
            )

        # No candidate may have been marked license-passing on this evidence: every
        # row whose license_or_use_basis passes must carry its own recorded basis.
        for candidate in self.ledger["candidates"]:
            if candidate["screening"]["license_or_use_basis"] == "pass":
                self.assertTrue(candidate["license_or_use_basis"])

    def test_every_inclusion_rule_has_a_terminal_exclusion_path(self) -> None:
        # A required inclusion criterion with no corresponding exclusion reason
        # would strand unsatisfiable candidates in screening forever.
        self.assertEqual(self.ledger["exclusion_rule_ids"], EXPECTED_EXCLUSION_RULES)
        self.assertIn("license-or-use-basis-unavailable", EXPECTED_EXCLUSION_RULES)

        for candidate in self.ledger["candidates"]:
            failed = {
                rule
                for rule, value in candidate["screening"].items()
                if value == "fail"
            }
            if failed:
                self.assertEqual(candidate["decision"], "excluded")
                self.assertTrue(candidate["exclusion_rule_ids_triggered"])
            for rule in candidate["exclusion_rule_ids_triggered"]:
                self.assertIn(rule, EXPECTED_EXCLUSION_RULES)

    def test_license_exclusions_are_revision_grounded(self) -> None:
        rows = [
            candidate
            for candidate in self.ledger["candidates"]
            if "license-or-use-basis-unavailable"
            in candidate["exclusion_rule_ids_triggered"]
        ]

        self.assertEqual(len(rows), 15)
        for candidate in rows:
            self.assertEqual(candidate["decision"], "excluded")
            self.assertEqual(candidate["screening"]["license_or_use_basis"], "fail")
            reasons = " ".join(candidate["decision_reasons"])
            if candidate["base_revision"]:
                # Strongest evidence: the terms were read at the candidate's own revision.
                self.assertIn(candidate["base_revision"], reasons)
            else:
                # Weaker evidence is allowed only to exclude, never to pass, and the
                # default-branch basis has to be stated so it is not mistaken for the above.
                self.assertIn("default branch", reasons)

    def test_exact_base_rows_follow_the_provisioning_principle(self) -> None:
        by_id = {
            candidate["candidate_id"]: candidate
            for candidate in self.ledger["candidates"]
        }

        # A missing runtime on the screening host is not an exclusion reason on its
        # own; both rows stay screening until a provisioned environment is verified.
        for candidate_id in (
            "ghko-SeoyunL--factlog-academic-issue-314",
            "ghko-minacle--swift-tui-issue-18",
        ):
            candidate = by_id[candidate_id]
            self.assertEqual(candidate["decision"], "screening")
            self.assertEqual(candidate["exclusion_rule_ids_triggered"], [])
            self.assertEqual(candidate["screening"]["native_language_source"], "pass")
            self.assertEqual(candidate["screening"]["exact_base_resolvable"], "pass")
            self.assertEqual(
                candidate["screening"]["reproducible_within_budget"], "unknown"
            )

        # Prose-only deliverables fail the objective evaluator rule and are excluded
        # on that reason alone.
        docker = by_id["ghko-Chigo55--Docker-Compose-issue-38"]
        self.assertEqual(docker["decision"], "excluded")
        self.assertEqual(
            docker["exclusion_rule_ids_triggered"], ["subjective-only-evaluation"]
        )
        self.assertEqual(docker["screening"]["objective_evaluator_feasible"], "fail")

        # The macOS-only toolchain row stays excluded on resource grounds.
        ios = by_id["ghko-ProudlyOffbeat--ProudlyOffbeat-MVP-iOS-issue-93"]
        self.assertEqual(ios["decision"], "excluded")
        self.assertIn("resource-budget-exceeded", ios["exclusion_rule_ids_triggered"])

    def test_preserves_explicit_multilingual_probe_audit(self) -> None:
        candidates = [
            candidate
            for candidate in self.ledger["candidates"]
            if candidate["source_pool_id"]
            == "github-explicit-multilingual-issues-2026-07-19"
        ]
        # The audited sample is the deterministic seeded 50-row probe. Rows carried
        # in later through the mechanical prefilter reach classification by a
        # different selection path, so they are scoped out by screening role rather
        # than being folded into this count.
        reviewed = [
            candidate
            for candidate in candidates
            if candidate["provisional_classification"]["task_category"] is not None
            and candidate["screened_by_role_id"] != "task-source-construction-2026-07-20"
        ]

        self.assertEqual(len(candidates), 383)
        self.assertEqual(len(reviewed), 50)
        self.assertEqual(
            Counter(candidate["decision"] for candidate in reviewed),
            {
                "screening": 15,
                "excluded": 33,
                "selected-for-task-authoring": 2,
            },
        )
        self.assertEqual(
            Counter(
                candidate["provisional_classification"]["instruction_language"]
                for candidate in reviewed
            ),
            {"ko": 28, "mixed": 21, "en": 1},
        )

    def test_bases_resolved_on_2026_07_20_are_revision_grounded(self) -> None:
        by_id = {
            candidate["candidate_id"]: candidate
            for candidate in self.ledger["candidates"]
        }

        # Resolving a base and reading a licence settles two of the eleven rules.
        # It settles none of the others, so a row that got only that far stays
        # screening. anygarden-512 is deliberately absent: it was carried further
        # the same day through reproduction and the remaining rule judgements, so
        # its promotion rests on those, not on having a base.
        for candidate_id in (
            "ghmix-greenheadHQ--nixos-config-issue-918",
            "ghko-SeoyunL--factlog-academic-issue-342",
            "ghmix-SeokRae--blog-issue-12",
            "ghko-ohah--zntc-issue-4564",
            "ghko-ohah--zntc-issue-4563",
            "ghko-ohah--zntc-issue-4553",
            "ghko-itismyfield--AgentDesk-issue-4606",
        ):
            candidate = by_id[candidate_id]
            self.assertEqual(candidate["decision"], "screening")
            self.assertEqual(candidate["exclusion_rule_ids_triggered"], [])
            self.assertTrue(candidate["base_revision"])
            self.assertTrue(candidate["base_tree_hash"])
            self.assertTrue(candidate["changed_files"])
            self.assertEqual(candidate["screening"]["exact_base_resolvable"], "pass")
            self.assertEqual(candidate["screening"]["license_or_use_basis"], "pass")
            # The basis has to name the pinned revision it was read from, so a
            # classifier signal can never be mistaken for artifact evidence.
            self.assertIn(candidate["base_revision"], candidate["license_or_use_basis"])
            self.assertNotIn("classifier", candidate["screening"].values())

    def test_reproduced_rows_are_held_only_by_instruction_parity(self) -> None:
        by_id = {
            candidate["candidate_id"]: candidate
            for candidate in self.ledger["candidates"]
        }

        # Both reproduced end to end without an agent on 2026-07-20: pinned toolchain,
        # negative control failing only for the intended missing behaviour, passing
        # positive control. Neither may pass reproducible_within_budget while the
        # equivalence of what each CLI reads from the base tree is unproven.
        for candidate_id in (
            "ghko-SeoyunL--factlog-academic-issue-314",
            "ghmix-hskim-solv--BidMate-DocAgent-issue-1152",
        ):
            candidate = by_id[candidate_id]
            self.assertEqual(candidate["decision"], "screening")
            self.assertEqual(
                candidate["screening"]["reproducible_within_budget"], "unknown"
            )
            reasons = " ".join(candidate["decision_reasons"])
            self.assertIn("negative control", reasons.lower())
            self.assertIn("positive control", reasons.lower())
            self.assertIn("Codex", reasons)

        # The licence basis that cited repository metadata was replaced by evidence
        # read from the pinned revision; the judgement itself did not change.
        factlog = by_id["ghko-SeoyunL--factlog-academic-issue-314"]
        self.assertEqual(factlog["screening"]["license_or_use_basis"], "pass")
        self.assertIn(factlog["base_revision"], factlog["license_or_use_basis"])


if __name__ == "__main__":
    unittest.main()
