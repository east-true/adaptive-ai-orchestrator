from __future__ import annotations

import json
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = ROOT / "experiments" / "phase2b-candidate-ledger-v1.json"
LICENSE_PROBE_PATH = ROOT / "experiments" / "phase2b-license-probe-2026-07-19.json"
CANDIDATE_SCHEMA_PATH = (
    ROOT / "experiments" / "schemas" / "paired-pilot-candidate-ledger-v1.schema.json"
)
MANIFEST_SCHEMA_PATH = (
    ROOT / "experiments" / "schemas" / "paired-pilot-manifest-v1.schema.json"
)
PARITY_PATH = (
    ROOT / "experiments" / "phase2b-agent-instruction-parity-2026-07-20.json"
)
EXPECTED_INCLUSION_RULES = {
    "license-or-use-basis",
    "exact-base-resolvable",
    "single-bounded-task",
    "native-language-source",
    "low-risk-isolated-execution",
    "no-network-secret-push-production",
    "objective-evaluator-feasible",
    "gold-and-evaluator-hideable",
    "instruction-parity",
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
    "instruction-parity-mismatch",
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
        self.assertEqual(
            self.ledger["protocol_version"], "phase2b-pilot-prereg-v1.1"
        )

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
        self.assertEqual(len(reviewed), 31)
        self.assertEqual(
            Counter(candidate["source_kind"] for candidate in candidates),
            {"public-issue-discovery": 384, "public-issue-pr-pair": 27},
        )
        self.assertEqual(
            Counter(candidate["decision"] for candidate in reviewed),
            {
                "excluded": 28,
                "selected-for-task-authoring": 3,
            },
        )
        self.assertEqual(
            Counter(
                candidate["provisional_classification"]["instruction_language"]
                for candidate in reviewed
            ),
            {"ko": 30, "mixed": 1},
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
                # Resolved from the mechanical prefilter's promising rows. A
                # resolved base is not a selection; parity can still exclude it.
                "ghko-SeoyunL--factlog-academic-issue-342",
                "ghko-ohah--zntc-issue-4564",
                "ghko-ohah--zntc-issue-4563",
                "ghko-ohah--zntc-issue-4553",
                "ghko-itismyfield--AgentDesk-issue-4606",
                "ghko-Lyainc--filme-issue-432",
                "ghko-minacle--swift-tui-issue-15",
                "ghko-yvshdjcsldhdjt--ChunChuGwan-issue-406",
                "ghko-Aiddoo--Aido-platform-issue-655",
                "ghko-hissinger--small-village-issue-51",
                "ghko-Soku-JINSEOK--Soku-Convention-Boilerplate-issue-19",
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
        self.assertIn("instruction-parity-mismatch", EXPECTED_EXCLUSION_RULES)

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

        self.assertEqual(len(rows), 21)
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

    def test_exact_base_pass_requires_materialized_revision_and_tree(self) -> None:
        for candidate in self.ledger["candidates"]:
            if candidate["screening"]["exact_base_resolvable"] != "pass":
                continue
            self.assertTrue(candidate["base_revision"], candidate["candidate_id"])
            self.assertTrue(candidate["base_tree_hash"], candidate["candidate_id"])

    def test_exact_base_rows_follow_the_provisioning_principle(self) -> None:
        by_id = {
            candidate["candidate_id"]: candidate
            for candidate in self.ledger["candidates"]
        }

        # A missing runtime on the screening host was not an exclusion reason on its
        # own. factlog was subsequently reproduced and passes; swift-tui's Linux
        # measurements remain valid but its exact-base project parity now fails.
        factlog = by_id["ghko-SeoyunL--factlog-academic-issue-314"]
        self.assertEqual(factlog["decision"], "selected-for-task-authoring")
        self.assertEqual(factlog["exclusion_rule_ids_triggered"], [])
        self.assertEqual(factlog["screening"]["reproducible_within_budget"], "pass")
        self.assertEqual(factlog["screening"]["instruction_parity"], "pass")

        swift = by_id["ghko-minacle--swift-tui-issue-18"]
        self.assertEqual(swift["decision"], "excluded")
        self.assertEqual(
            swift["exclusion_rule_ids_triggered"],
            ["instruction-parity-mismatch"],
        )
        self.assertEqual(swift["screening"]["native_language_source"], "pass")
        self.assertEqual(swift["screening"]["exact_base_resolvable"], "pass")
        self.assertEqual(swift["screening"]["reproducible_within_budget"], "unknown")
        self.assertEqual(swift["screening"]["instruction_parity"], "fail")
        self.assertEqual(
            swift["solution_tree_hash"],
            "96259579393cf463fdb6e774d6cfd6846ce90094",
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
                "screening": 8,
                "excluded": 40,
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

    def test_resolved_external_bases_are_revision_grounded(self) -> None:
        by_id = {
            candidate["candidate_id"]: candidate
            for candidate in self.ledger["candidates"]
        }

        # Resolving a base and reading a licence settles only those two rules.
        # The 2026-07-22 parity amendment can now independently pass or terminally
        # exclude these rows from their recorded pinned instruction inventories.
        # anygarden-512 is deliberately absent: it was carried through reproduction
        # and all remaining rule judgements, so its selection does not rest on base
        # resolution alone.
        for candidate_id in (
            "ghmix-greenheadHQ--nixos-config-issue-918",
            "ghko-SeoyunL--factlog-academic-issue-342",
            "ghmix-SeokRae--blog-issue-12",
            "ghko-ohah--zntc-issue-4564",
            "ghko-ohah--zntc-issue-4563",
            "ghko-ohah--zntc-issue-4553",
            "ghko-itismyfield--AgentDesk-issue-4606",
            "ghko-Lyainc--filme-issue-432",
            "ghko-minacle--swift-tui-issue-15",
            "ghko-yvshdjcsldhdjt--ChunChuGwan-issue-406",
        ):
            candidate = by_id[candidate_id]
            self.assertTrue(candidate["base_revision"])
            self.assertTrue(candidate["base_tree_hash"])
            self.assertTrue(candidate["changed_files"])
            self.assertEqual(candidate["screening"]["exact_base_resolvable"], "pass")
            self.assertEqual(candidate["screening"]["license_or_use_basis"], "pass")
            # The basis has to name the pinned revision it was read from, so a
            # classifier signal can never be mistaken for artifact evidence.
            self.assertIn(candidate["base_revision"], candidate["license_or_use_basis"])
            self.assertNotIn("classifier", candidate["screening"].values())

            if candidate_id in {
                "ghko-SeoyunL--factlog-academic-issue-342",
                "ghko-yvshdjcsldhdjt--ChunChuGwan-issue-406",
            }:
                self.assertEqual(
                    candidate["decision"], "selected-for-task-authoring"
                )
                self.assertEqual(candidate["exclusion_rule_ids_triggered"], [])
                self.assertEqual(candidate["screening"]["instruction_parity"], "pass")
            else:
                self.assertEqual(candidate["decision"], "excluded")
                self.assertEqual(
                    candidate["exclusion_rule_ids_triggered"],
                    ["instruction-parity-mismatch"],
                )
                self.assertEqual(candidate["screening"]["instruction_parity"], "fail")

    def test_reproduction_and_instruction_parity_are_separate_rules(self) -> None:
        by_id = {
            candidate["candidate_id"]: candidate
            for candidate in self.ledger["candidates"]
        }

        # Both rows reproduced end to end without an agent. The explicit parity rule
        # now decides their different construction states without rewriting resource
        # reproducibility as an instruction-discovery claim.
        factlog = by_id["ghko-SeoyunL--factlog-academic-issue-314"]
        bidmate = by_id["ghmix-hskim-solv--BidMate-DocAgent-issue-1152"]
        for candidate in (factlog, bidmate):
            self.assertEqual(candidate["screening"]["reproducible_within_budget"], "pass")
            reasons = " ".join(candidate["decision_reasons"])
            self.assertIn("negative control", reasons.lower())
            self.assertIn("positive control", reasons.lower())

        self.assertEqual(factlog["screening"]["instruction_parity"], "pass")
        self.assertEqual(factlog["decision"], "selected-for-task-authoring")
        self.assertEqual(bidmate["screening"]["instruction_parity"], "fail")
        self.assertEqual(bidmate["decision"], "excluded")
        self.assertEqual(
            bidmate["exclusion_rule_ids_triggered"],
            ["instruction-parity-mismatch"],
        )

        # The licence basis that cited repository metadata was replaced by evidence
        # read from the pinned revision; the judgement itself did not change.
        self.assertEqual(factlog["screening"]["license_or_use_basis"], "pass")
        self.assertIn(factlog["base_revision"], factlog["license_or_use_basis"])

    def test_contextual_screening_keeps_terminal_reasons_separate(self) -> None:
        by_id = {
            candidate["candidate_id"]: candidate
            for candidate in self.ledger["candidates"]
        }
        coupled = by_id["ghmix-jinwon-int--ccc-node-issue-34"]

        self.assertEqual(
            coupled["task_statement_hash"],
            "5b64947d02b758006c75d4d57502241ab74c25af66754425abfe6cf68e1008f1",
        )
        self.assertEqual(coupled["decision"], "excluded")
        self.assertEqual(coupled["screening"]["single_bounded_task"], "fail")
        self.assertEqual(
            coupled["exclusion_rule_ids_triggered"], ["multiple-coupled-issues"]
        )
        self.assertTrue(
            all(value is None for value in coupled["provisional_classification"].values())
        )
        self.assertIsNone(coupled["base_revision"])
        self.assertIsNone(coupled["base_tree_hash"])
        self.assertEqual(coupled["screening"]["license_or_use_basis"], "unknown")
        self.assertEqual(coupled["screening"]["instruction_parity"], "unknown")

        for candidate_id in (
            "ghko-Lyainc--filme-issue-432",
            "ghko-minacle--swift-tui-issue-15",
        ):
            candidate = by_id[candidate_id]
            self.assertEqual(candidate["decision"], "excluded")
            self.assertEqual(
                candidate["exclusion_rule_ids_triggered"],
                ["instruction-parity-mismatch"],
            )
            self.assertEqual(candidate["screening"]["exact_base_resolvable"], "pass")
            self.assertEqual(candidate["screening"]["license_or_use_basis"], "pass")
            self.assertEqual(candidate["screening"]["instruction_parity"], "fail")
            self.assertEqual(candidate["screening"]["single_bounded_task"], "unknown")

        subjective = by_id["ghmix-semantic-reasoning--factlog-issue-269"]
        self.assertEqual(subjective["decision"], "excluded")
        self.assertEqual(
            subjective["exclusion_rule_ids_triggered"],
            ["subjective-only-evaluation"],
        )
        self.assertEqual(subjective["screening"]["single_bounded_task"], "pass")
        self.assertEqual(
            subjective["screening"]["objective_evaluator_feasible"], "fail"
        )

        external = by_id["ghmix-Lyainc--filme-issue-348"]
        self.assertEqual(external["decision"], "excluded")
        self.assertEqual(
            external["exclusion_rule_ids_triggered"],
            ["unsafe-or-external-side-effect"],
        )
        self.assertEqual(external["screening"]["low_risk_isolated_execution"], "fail")
        self.assertEqual(
            external["screening"]["no_network_secret_push_production"], "fail"
        )

        advancing = by_id["ghko-yvshdjcsldhdjt--ChunChuGwan-issue-406"]
        self.assertEqual(advancing["decision"], "selected-for-task-authoring")
        self.assertEqual(advancing["exclusion_rule_ids_triggered"], [])
        self.assertEqual(advancing["screening"]["single_bounded_task"], "pass")
        self.assertEqual(
            advancing["screening"]["objective_evaluator_feasible"], "pass"
        )
        self.assertEqual(
            advancing["base_revision"],
            "793d2a875d159d372254dc02712f0e79831c7ea1",
        )
        self.assertEqual(
            advancing["base_tree_hash"],
            "f94c1a6b9bc764dfaa3549dfac99971bab1f62e2",
        )
        self.assertEqual(advancing["screening"]["exact_base_resolvable"], "pass")
        self.assertEqual(advancing["screening"]["license_or_use_basis"], "pass")
        self.assertEqual(advancing["screening"]["instruction_parity"], "pass")

    def test_third_contextual_batch_separates_boundedness_from_parity(self) -> None:
        by_id = {
            candidate["candidate_id"]: candidate
            for candidate in self.ledger["candidates"]
        }

        bounded_failures = {
            "ghko-Aiddoo--Aido-platform-issue-655": {
                "base_revision": "f3083d85af3f9c7632448c0f276ac552bd7308cc",
                "base_tree_hash": "3877f9457c1213cd2bb9ffa66582a4ea34e0494d",
                "solution_revision": "6fcd167d32bcd29093e625a6c2617b084f1f8b78",
                "solution_tree_hash": "742d5fef0011e7151af41723af311c5a708d8ac0",
                "solution_artifact_hash": "baae84b0fe0f1b627dca2633ba287d72aeeb0bb6c0ad6e1fe4bca32a8cd918ce",
                "changed_file_count": 13,
            },
            "ghko-hissinger--small-village-issue-51": {
                "base_revision": "a8cb2884be553f91f2bfa50e306b5def1e6fc072",
                "base_tree_hash": "e191b027d4c1a7d410b10958701b2c3ce9b9967c",
                "solution_revision": "7f43eaacf1a89bf14af8e22a69b0bc34d3669541",
                "solution_tree_hash": "7ae34c27e1965da4652537134bfdea6044e44858",
                "solution_artifact_hash": "fb80d4c96c02ec88013ef3bd8f785d0efc580b179a08ed6b56cac2e80f892674",
                "changed_file_count": 19,
            },
        }
        for candidate_id, expected in bounded_failures.items():
            candidate = by_id[candidate_id]
            for field in (
                "base_revision",
                "base_tree_hash",
                "solution_revision",
                "solution_tree_hash",
                "solution_artifact_hash",
            ):
                self.assertEqual(candidate[field], expected[field])
            self.assertEqual(len(candidate["changed_files"]), expected["changed_file_count"])
            self.assertEqual(candidate["screening"]["license_or_use_basis"], "pass")
            self.assertEqual(candidate["screening"]["exact_base_resolvable"], "pass")
            self.assertEqual(candidate["screening"]["instruction_parity"], "pass")
            self.assertEqual(candidate["screening"]["single_bounded_task"], "fail")
            self.assertEqual(candidate["decision"], "excluded")
            self.assertEqual(
                candidate["exclusion_rule_ids_triggered"],
                ["multiple-coupled-issues"],
            )
            self.assertTrue(
                all(
                    value is None
                    for value in candidate["provisional_classification"].values()
                )
            )

        parity_failure = by_id[
            "ghko-Soku-JINSEOK--Soku-Convention-Boilerplate-issue-19"
        ]
        self.assertEqual(
            parity_failure["base_revision"],
            "404e695304d2e9fd7930a7134fcc2a15c7b5ffc4",
        )
        self.assertEqual(
            parity_failure["base_tree_hash"],
            "ad9c7296c25e328b5ba120f843b505300caa29d4",
        )
        self.assertEqual(len(parity_failure["changed_files"]), 26)
        self.assertEqual(parity_failure["screening"]["license_or_use_basis"], "pass")
        self.assertEqual(parity_failure["screening"]["exact_base_resolvable"], "pass")
        self.assertEqual(parity_failure["screening"]["single_bounded_task"], "unknown")
        self.assertEqual(parity_failure["screening"]["instruction_parity"], "fail")
        self.assertEqual(parity_failure["decision"], "excluded")
        self.assertEqual(
            parity_failure["exclusion_rule_ids_triggered"],
            ["instruction-parity-mismatch"],
        )

    def test_fourth_contextual_batch_preserves_source_and_git_boundaries(self) -> None:
        by_id = {
            candidate["candidate_id"]: candidate
            for candidate in self.ledger["candidates"]
        }

        translation = by_id["ghmix-jkas2016--hsr-warp-issue-12"]
        self.assertEqual(translation["decision"], "excluded")
        self.assertEqual(
            translation["exclusion_rule_ids_triggered"], ["translation-only"]
        )
        self.assertEqual(translation["screening"]["single_bounded_task"], "pass")
        self.assertEqual(translation["screening"]["native_language_source"], "fail")
        self.assertIsNone(translation["base_revision"])

        subjective = by_id["ghmix-Lyainc--filme-issue-391"]
        self.assertEqual(subjective["decision"], "excluded")
        self.assertEqual(
            subjective["exclusion_rule_ids_triggered"],
            ["subjective-only-evaluation"],
        )
        self.assertEqual(subjective["screening"]["single_bounded_task"], "pass")
        self.assertEqual(subjective["screening"]["native_language_source"], "pass")
        self.assertEqual(
            subjective["screening"]["objective_evaluator_feasible"], "fail"
        )
        self.assertIsNone(subjective["base_revision"])

        advancing = by_id["ghmix-genonai--doc_parser-issue-288"]
        self.assertEqual(advancing["decision"], "screening")
        self.assertEqual(advancing["exclusion_rule_ids_triggered"], [])
        self.assertEqual(
            advancing["base_revision"],
            "3107d9663355fc042faa3c19f8e37e357af8a370",
        )
        self.assertNotEqual(
            advancing["base_revision"],
            "b4b2b17becf049d77a1cc87526b9ed178635f058",
        )
        self.assertEqual(
            advancing["base_tree_hash"],
            "c7dd7005be6099763960903fd116a02dc29bf9fd",
        )
        self.assertEqual(
            advancing["solution_revision"],
            "9bf82283a973b77b7bdc1070cfac96a7f7c4d452",
        )
        self.assertEqual(
            advancing["solution_tree_hash"],
            "3de52e55a7f710d3c4899ea12774f877029367d6",
        )
        self.assertEqual(
            advancing["solution_artifact_hash"],
            "d3863f6475f6a1943b452e76a788a6ed08c16b83a5d9e3398fdba68fe9d76e65",
        )
        self.assertEqual(len(advancing["changed_files"]), 17)
        self.assertIn(advancing["base_revision"], advancing["license_or_use_basis"])
        self.assertEqual(
            advancing["provisional_classification"]["instruction_language"], "ko"
        )
        self.assertEqual(
            advancing["provisional_classification"]["task_category"],
            "implementation",
        )

        unresolved = {
            rule_id
            for rule_id, value in advancing["screening"].items()
            if value == "unknown"
        }
        self.assertEqual(unresolved, {"reproducible_within_budget"})
        self.assertEqual(
            Counter(advancing["screening"].values()),
            {"pass": 11, "unknown": 1},
        )

    def test_fifth_contextual_candidate_has_agent_free_reproducibility_controls(self) -> None:
        by_id = {
            candidate["candidate_id"]: candidate
            for candidate in self.ledger["candidates"]
        }
        selected = by_id["ghmix-KoreaNirsa--prompt-booster-issue-10"]

        self.assertEqual(selected["decision"], "selected-for-task-authoring")
        self.assertEqual(selected["exclusion_rule_ids_triggered"], [])
        self.assertEqual(
            selected["base_revision"],
            "5f6a045a7d8fae7fc3b4df6150cf98d3cee8acb2",
        )
        self.assertEqual(
            selected["base_tree_hash"],
            "7476e28bbd9ff11cd305f755098f9955bfae70bd",
        )
        self.assertEqual(
            selected["solution_revision"],
            "0533e40b06358fc9a8db61298b67904c5b43c271",
        )
        self.assertEqual(
            selected["solution_tree_hash"],
            "978a7844a746567764dd56e8f5755029671592d8",
        )
        self.assertEqual(
            selected["solution_artifact_hash"],
            "909b0f92f0e9a92480e9d25890f5aa7c2e0b0f7122fca6f37ed9ba7270678f98",
        )
        self.assertEqual(len(selected["changed_files"]), 9)
        self.assertIn(selected["base_revision"], selected["license_or_use_basis"])
        self.assertEqual(
            selected["provisional_classification"],
            {
                "instruction_language": "ko",
                "task_category": "implementation",
                "repository_code_language": "python",
                "repository_doc_language": "mixed",
            },
        )
        self.assertEqual(Counter(selected["screening"].values()), {"pass": 12})
        self.assertTrue(
            any(
                "pristine exact base passed 41 tests" in reason
                and "targeted pattern-library and optimizer suite passed 13 tests"
                in reason
                for reason in selected["decision_reasons"]
            )
        )

    def test_base_known_factlog_candidate_uses_its_atomic_issue_commit(self) -> None:
        by_id = {
            candidate["candidate_id"]: candidate
            for candidate in self.ledger["candidates"]
        }
        selected = by_id["ghko-SeoyunL--factlog-academic-issue-342"]

        self.assertEqual(selected["decision"], "selected-for-task-authoring")
        self.assertEqual(Counter(selected["screening"].values()), {"pass": 12})
        self.assertEqual(
            selected["solution_revision"],
            "6a31ec8c4eb53ec1e1a4a68b3d30a01e89e33440",
        )
        self.assertEqual(
            selected["solution_tree_hash"],
            "5286d5fa86043b8b61c7b552d955a229dde891b3",
        )
        self.assertEqual(
            selected["solution_artifact_hash"],
            "6b1dcd453355162eab5208b26fe7c7a590757491f0a625c0b69957dc8abbe420",
        )
        self.assertEqual(
            selected["changed_files"],
            ["tests/unit/test_run_logic_check.py", "tools/run_logic_check.py"],
        )
        self.assertEqual(
            selected["provisional_classification"]["task_category"], "debugging"
        )
        self.assertTrue(
            any(
                "failed in 0.28 s only with the stated JSONDecodeError" in reason
                and "passed 2/2 in 0.27 s" in reason
                for reason in selected["decision_reasons"]
            )
        )

    def test_chunchugwan_has_agent_free_route_reproduction(self) -> None:
        by_id = {
            candidate["candidate_id"]: candidate
            for candidate in self.ledger["candidates"]
        }
        candidate = by_id["ghko-yvshdjcsldhdjt--ChunChuGwan-issue-406"]

        self.assertEqual(candidate["decision"], "selected-for-task-authoring")
        self.assertEqual(candidate["screening"]["instruction_parity"], "pass")
        self.assertEqual(Counter(candidate["screening"].values()), {"pass": 12})
        self.assertEqual(
            candidate["source_evaluator_artifact_hash"],
            "d79234edccf77e9b1368a29ab929c645cc641e74d7f7cf87e3bedbe268f41c3e",
        )
        self.assertEqual(
            candidate["provisional_classification"],
            {
                "instruction_language": "ko",
                "task_category": "implementation",
                "repository_code_language": "python",
                "repository_doc_language": "ko",
            },
        )
        self.assertTrue(
            any(
                "Codex first receives AGENTS.md" in reason
                and "same path-scoped constraints" in reason
                for reason in candidate["decision_reasons"]
            )
        )
        self.assertTrue(
            any(
                "failed on the pristine base in 1.37 seconds" in reason
                and "passed on the one-commit solution in 1.38 seconds" in reason
                for reason in candidate["decision_reasons"]
            )
        )

    def test_membershipflow_is_revision_grounded_license_exclusion(self) -> None:
        by_id = {
            candidate["candidate_id"]: candidate
            for candidate in self.ledger["candidates"]
        }
        candidate = by_id["ghmix-ohhalim--MembershipFlow-issue-79"]

        self.assertEqual(candidate["decision"], "excluded")
        self.assertEqual(
            candidate["exclusion_rule_ids_triggered"],
            ["license-or-use-basis-unavailable"],
        )
        self.assertEqual(candidate["source_kind"], "public-issue-pr-pair")
        self.assertEqual(
            candidate["base_revision"],
            "b2bc8bac41e51b61774b3b98da43e420f4d46df3",
        )
        self.assertEqual(
            candidate["base_tree_hash"],
            "43678ee48b587b4404e944b50deba0c56824ff40",
        )
        self.assertEqual(
            candidate["solution_revision"],
            "b848a7411842952262f195c1eafdd5fd98b16b6e",
        )
        self.assertEqual(
            candidate["solution_tree_hash"],
            "5686d2242fed14e736ed6da3857cbe92e9e413fc",
        )
        self.assertEqual(
            candidate["solution_artifact_hash"],
            "4eb0a90972347568f256269bad57baca2426b7ca8c7ca2815375253f25e1218e",
        )
        self.assertEqual(
            candidate["changed_files"],
            [
                "src/main/java/com/membershipflow/collect/collector/"
                "MembershipTypeMapper.java"
            ],
        )
        self.assertEqual(candidate["screening"]["license_or_use_basis"], "fail")
        self.assertEqual(candidate["screening"]["exact_base_resolvable"], "pass")
        self.assertEqual(candidate["screening"]["native_language_source"], "pass")
        self.assertEqual(candidate["screening"]["instruction_parity"], "pass")
        self.assertIn(candidate["base_revision"], candidate["license_or_use_basis"])
        self.assertTrue(
            any(
                "complete tree plus README.md and build.gradle" in reason
                and "No LICENSE, LICENCE, COPYING, NOTICE, or UNLICENSE" in reason
                for reason in candidate["decision_reasons"]
            )
        )

    def test_seoul_challenge_has_two_revision_grounded_terminal_failures(self) -> None:
        by_id = {
            candidate["candidate_id"]: candidate
            for candidate in self.ledger["candidates"]
        }
        candidate = by_id["ghmix-0xkkun--seoul-challenge-issue-30"]

        self.assertEqual(candidate["decision"], "excluded")
        self.assertEqual(
            candidate["exclusion_rule_ids_triggered"],
            ["license-or-use-basis-unavailable", "instruction-parity-mismatch"],
        )
        self.assertEqual(candidate["source_kind"], "public-issue-pr-pair")
        self.assertEqual(
            candidate["base_revision"],
            "075464d7ec5ebf1771cde201e560bdf6fa0bdd2f",
        )
        self.assertEqual(
            candidate["base_tree_hash"],
            "f9058eebeb04463aac357ab037fe4d9449ed9338",
        )
        self.assertEqual(
            candidate["solution_revision"],
            "91cc1b4f9b1215dee9d2381f36caf3b8f9125541",
        )
        self.assertEqual(
            candidate["solution_tree_hash"],
            "ff6e4ad243ddcba580c6412eaaf1c67b0294e96f",
        )
        self.assertEqual(
            candidate["solution_artifact_hash"],
            "356e1603023d2a87eb2d77cdc0cb15c7174665a7b265d4987929197285d8d35c",
        )
        self.assertEqual(len(candidate["changed_files"]), 8)
        self.assertEqual(candidate["screening"]["license_or_use_basis"], "fail")
        self.assertEqual(candidate["screening"]["exact_base_resolvable"], "pass")
        self.assertEqual(candidate["screening"]["native_language_source"], "pass")
        self.assertEqual(candidate["screening"]["instruction_parity"], "fail")
        self.assertIn(candidate["base_revision"], candidate["license_or_use_basis"])
        reasons = " ".join(candidate["decision_reasons"])
        self.assertIn("no LICENSE, LICENCE, COPYING, NOTICE, or UNLICENSE", reasons)
        self.assertIn("contains root AGENTS.md only", reasons)

    def test_oat_has_scoped_license_and_claude_only_terminal_failures(self) -> None:
        by_id = {
            candidate["candidate_id"]: candidate
            for candidate in self.ledger["candidates"]
        }
        candidate = by_id["ghmix-Gn0lee--oat-issue-410"]

        self.assertEqual(candidate["decision"], "excluded")
        self.assertEqual(
            candidate["exclusion_rule_ids_triggered"],
            ["license-or-use-basis-unavailable", "instruction-parity-mismatch"],
        )
        self.assertEqual(candidate["source_kind"], "public-issue-pr-pair")
        self.assertEqual(
            candidate["base_revision"],
            "b19b34b63d1df554091b165484d78ce9cf2eba1d",
        )
        self.assertEqual(
            candidate["base_tree_hash"],
            "2ea4b5e9cc61d7345734c4d3df483d7bcb0736dd",
        )
        self.assertEqual(
            candidate["solution_revision"],
            "15c72d5c9329883f18c5433e1eb13432139ca1dc",
        )
        self.assertEqual(
            candidate["solution_tree_hash"],
            "b400c2c744ebfdd907d7a0ebf979db51846d98d4",
        )
        self.assertEqual(
            candidate["solution_artifact_hash"],
            "6f438103cdc0ef56d03c44338b7631792475b484a57f84e82b012c1784f85111",
        )
        self.assertEqual(len(candidate["changed_files"]), 14)
        self.assertEqual(candidate["screening"]["license_or_use_basis"], "fail")
        self.assertEqual(candidate["screening"]["exact_base_resolvable"], "pass")
        self.assertEqual(candidate["screening"]["native_language_source"], "pass")
        self.assertEqual(candidate["screening"]["instruction_parity"], "fail")
        self.assertIn(candidate["base_revision"], candidate["license_or_use_basis"])
        reasons = " ".join(candidate["decision_reasons"])
        self.assertIn("separate @oat-app/mcp-bridge package", reasons)
        self.assertIn("contains root CLAUDE.md only", reasons)

    def test_subway_now_corrects_api_base_and_records_two_terminal_failures(self) -> None:
        by_id = {
            candidate["candidate_id"]: candidate
            for candidate in self.ledger["candidates"]
        }
        candidate = by_id["ghmix-handokei--subway-now-issue-1465"]

        self.assertEqual(candidate["decision"], "excluded")
        self.assertEqual(
            candidate["exclusion_rule_ids_triggered"],
            ["license-or-use-basis-unavailable", "instruction-parity-mismatch"],
        )
        self.assertEqual(candidate["source_kind"], "public-issue-pr-pair")
        self.assertEqual(
            candidate["base_revision"],
            "1c73ae582b535514feb43bbc393b5cec1ba12920",
        )
        self.assertEqual(
            candidate["base_tree_hash"],
            "158cfbad7be784dbd5d7588ca4e3195ab2dfad22",
        )
        self.assertEqual(
            candidate["solution_revision"],
            "c53892702dd905265f956027297b870f18046596",
        )
        self.assertEqual(
            candidate["solution_tree_hash"],
            "c0fb21b4cde5be012893db2d70551ff8d48568aa",
        )
        self.assertEqual(
            candidate["solution_artifact_hash"],
            "04863235be107c887f1d9d88e54b26e8a9eb9da38322ec5a30b5cbd2b7b39185",
        )
        self.assertEqual(len(candidate["changed_files"]), 5)
        self.assertEqual(candidate["screening"]["license_or_use_basis"], "fail")
        self.assertEqual(candidate["screening"]["exact_base_resolvable"], "pass")
        self.assertEqual(candidate["screening"]["native_language_source"], "pass")
        self.assertEqual(candidate["screening"]["instruction_parity"], "fail")
        self.assertIn(candidate["base_revision"], candidate["license_or_use_basis"])
        reasons = " ".join(candidate["decision_reasons"])
        self.assertIn("current Pull Request API base", reasons)
        self.assertIn("not an ancestor", reasons)
        self.assertIn("contains root CLAUDE.md only", reasons)
        self.assertIn("OpenStreetMap map data", reasons)

    def test_jackpot_has_exact_one_commit_lineage_and_license_only_exclusion(self) -> None:
        by_id = {
            candidate["candidate_id"]: candidate
            for candidate in self.ledger["candidates"]
        }
        candidate = by_id[
            "ghmix-prgrms-aibe-devcourse--AIBE5_FinalProject_Team7_JackPot-issue-499"
        ]

        self.assertEqual(candidate["decision"], "excluded")
        self.assertEqual(
            candidate["exclusion_rule_ids_triggered"],
            ["license-or-use-basis-unavailable"],
        )
        self.assertEqual(candidate["source_kind"], "public-issue-pr-pair")
        self.assertEqual(
            candidate["base_revision"],
            "9ae892a4f9074dfea2f93d534977cc3da3a051f8",
        )
        self.assertEqual(
            candidate["base_tree_hash"],
            "6722de4d5709782f1a0a47643a08b36c984f9342",
        )
        self.assertEqual(
            candidate["solution_revision"],
            "e323f65b51321216ab821e50f1b87e358905cb4e",
        )
        self.assertEqual(
            candidate["solution_tree_hash"],
            "2d37ba43ed0b33d2597cf458aa9357db077d6866",
        )
        self.assertEqual(
            candidate["solution_artifact_hash"],
            "c9e2b6ecdf6c04e1f32e0fbc20965c97e1e9c73d1416c5fa870a4d0daeef97b5",
        )
        self.assertEqual(
            candidate["changed_files"],
            [
                "frontend/index.html",
                "frontend/src/styles/global.css",
                "frontend/src/styles/wireframe.css",
            ],
        )
        self.assertEqual(candidate["screening"]["license_or_use_basis"], "fail")
        self.assertEqual(candidate["screening"]["exact_base_resolvable"], "pass")
        self.assertEqual(candidate["screening"]["native_language_source"], "pass")
        self.assertEqual(candidate["screening"]["instruction_parity"], "pass")
        self.assertIn(candidate["base_revision"], candidate["license_or_use_basis"])
        reasons = " ".join(candidate["decision_reasons"])
        self.assertIn("complete base tree has 520 entries", reasons)
        self.assertIn("no AGENTS.override.md, AGENTS.md, or CLAUDE.md", reasons)

    def test_skala_uses_atomic_final_commit_not_coupled_pull_request_diff(self) -> None:
        by_id = {
            candidate["candidate_id"]: candidate
            for candidate in self.ledger["candidates"]
        }
        candidate = by_id["ghmix-SKALA-TEAM5--frontend-issue-66"]

        self.assertEqual(candidate["decision"], "excluded")
        self.assertEqual(
            candidate["exclusion_rule_ids_triggered"],
            ["license-or-use-basis-unavailable"],
        )
        self.assertEqual(candidate["source_kind"], "public-issue-pr-pair")
        self.assertEqual(
            candidate["base_revision"],
            "0950a8e281c1dfc5021bb5d05910d3107f899fa4",
        )
        self.assertEqual(
            candidate["base_tree_hash"],
            "55524f7af8c79871fe5a9f8dd1e94a89060506a9",
        )
        self.assertEqual(
            candidate["solution_revision"],
            "7c5dcde28c555e8696f6f222bc8010303c820ba2",
        )
        self.assertEqual(
            candidate["solution_tree_hash"],
            "1f2a972c683a18e7992eed282f3bbe3d6e30cd69",
        )
        self.assertEqual(
            candidate["solution_artifact_hash"],
            "afab6ba4ecc548d5ffbc13f29a3d82b712e5d1ead737c189b7598fb770acf929",
        )
        self.assertEqual(
            candidate["changed_files"],
            ["src/features/project-tab/UsageStatementDetailScreen.tsx"],
        )
        self.assertEqual(candidate["screening"]["license_or_use_basis"], "fail")
        self.assertEqual(candidate["screening"]["exact_base_resolvable"], "pass")
        self.assertEqual(candidate["screening"]["native_language_source"], "pass")
        self.assertEqual(candidate["screening"]["instruction_parity"], "pass")
        reasons = " ".join(candidate["decision_reasons"])
        self.assertIn("closes #66, #67, and #68 together", reasons)
        self.assertIn("The full PR diff is therefore not used as gold", reasons)
        self.assertIn("complete base tree has 68 entries", reasons)

    def test_pinned_instruction_parity_decisions_are_exact_base_only(self) -> None:
        by_id = {
            candidate["candidate_id"]: candidate
            for candidate in self.ledger["candidates"]
        }
        passing = {
            "ghko-SeoyunL--factlog-academic-issue-314",
            "ghmix-joshua-jingu-lee--ante-issue-2349",
            "ghmix-semantic-reasoning--factlog-issue-26",
            "ghmix-e7217--anygarden-issue-512",
            "ghko-SeoyunL--factlog-academic-issue-342",
            "ghko-Aiddoo--Aido-platform-issue-655",
            "ghko-hissinger--small-village-issue-51",
            "ghmix-genonai--doc_parser-issue-288",
            "ghmix-KoreaNirsa--prompt-booster-issue-10",
            "ghko-yvshdjcsldhdjt--ChunChuGwan-issue-406",
            "ghmix-ohhalim--MembershipFlow-issue-79",
            "ghmix-prgrms-aibe-devcourse--AIBE5_FinalProject_Team7_JackPot-issue-499",
            "ghmix-SKALA-TEAM5--frontend-issue-66",
        }
        failing = {
            "ghmix-hskim-solv--BidMate-DocAgent-issue-1152",
            "ghmix-SeokRae--blog-issue-12",
            "ghmix-greenheadHQ--nixos-config-issue-918",
            "ghko-ohah--zntc-issue-4564",
            "ghko-ohah--zntc-issue-4563",
            "ghko-ohah--zntc-issue-4553",
            "ghko-itismyfield--AgentDesk-issue-4606",
            "ghko-Lyainc--filme-issue-432",
            "ghko-minacle--swift-tui-issue-15",
            "ghko-minacle--swift-tui-issue-18",
            "ghko-Soku-JINSEOK--Soku-Convention-Boilerplate-issue-19",
            "ghmix-0xkkun--seoul-challenge-issue-30",
            "ghmix-Gn0lee--oat-issue-410",
            "ghmix-handokei--subway-now-issue-1465",
        }

        self.assertEqual(
            {
                candidate_id
                for candidate_id, candidate in by_id.items()
                if candidate["screening"]["instruction_parity"] == "pass"
            },
            passing,
        )
        self.assertEqual(
            {
                candidate_id
                for candidate_id, candidate in by_id.items()
                if candidate["screening"]["instruction_parity"] == "fail"
            },
            failing,
        )
        for candidate_id in failing:
            self.assertEqual(by_id[candidate_id]["decision"], "excluded")
            self.assertIn(
                "instruction-parity-mismatch",
                by_id[candidate_id]["exclusion_rule_ids_triggered"],
            )

        # Docker-Compose has only default-branch prevalence evidence for instruction
        # files. Its independent subjective-evaluation exclusion is unchanged.
        docker = by_id["ghko-Chigo55--Docker-Compose-issue-38"]
        self.assertEqual(docker["screening"]["instruction_parity"], "unknown")
        self.assertEqual(
            docker["exclusion_rule_ids_triggered"], ["subjective-only-evaluation"]
        )

    def test_instruction_parity_artifact_separates_evidence_types(self) -> None:
        artifact = json.loads(PARITY_PATH.read_text(encoding="utf-8"))
        update = artifact["codex_measurement_update_2026_07_22"]

        behavioral = update["behavioral_evidence"]
        self.assertEqual(behavioral["evidence_type"], "behavioral")
        self.assertEqual(behavioral["cli_version"], "0.144.6")
        self.assertEqual(
            behavioral["observed_final_answer"], "PROJECT_AGENTS_MARKER_7F31"
        )
        self.assertEqual(
            behavioral["usage"],
            {"input_tokens": 12706, "output_tokens": 13, "reasoning_tokens": 0},
        )

        documented = update["official_document_evidence"]
        self.assertEqual(documented["evidence_type"], "official-document")
        self.assertEqual(len(update["not_behaviorally_measured"]), 3)
        self.assertFalse(
            update["local_configuration_observation"][
                "project_doc_fallback_filenames_present"
            ]
        )

        assessments = artifact["pinned_candidate_parity_2026_07_22"]
        self.assertIn("Default-branch prevalence", assessments["method"])
        self.assertEqual(assessments["codex_project_doc_fallback_filenames"], [])
        self.assertEqual(len(assessments["assessments"]), 27)
        contextual = assessments["contextual_batch_materialized_inventory"]
        self.assertEqual(
            {
                candidate["candidate_id"]: (
                    candidate["base_tree_hash"],
                    candidate["tree_entry_count"],
                )
                for candidate in contextual["candidates"]
            },
            {
                "ghko-Lyainc--filme-issue-432": (
                    "bda44c3f34b49e97a50d11064f4486ca95a90b3a",
                    452,
                ),
                "ghko-minacle--swift-tui-issue-15": (
                    "ce24efb94cc5f63405daa5fdd6d3feb3811d7bc3",
                    219,
                ),
            },
        )
        second_contextual = assessments[
            "second_contextual_batch_materialized_inventory"
        ]["candidates"]
        self.assertEqual(len(second_contextual), 1)
        self.assertEqual(
            second_contextual[0]["candidate_id"],
            "ghko-yvshdjcsldhdjt--ChunChuGwan-issue-406",
        )
        self.assertEqual(
            second_contextual[0]["base_tree_hash"],
            "f94c1a6b9bc764dfaa3549dfac99971bab1f62e2",
        )
        self.assertEqual(second_contextual[0]["tree_entry_count"], 616)
        self.assertEqual(second_contextual[0]["assessment"], "pass")
        third_contextual = assessments[
            "third_contextual_batch_materialized_inventory"
        ]["candidates"]
        self.assertEqual(
            {
                candidate["candidate_id"]: (
                    candidate["base_tree_hash"],
                    candidate["tree_entry_count"],
                    candidate["assessment"],
                )
                for candidate in third_contextual
            },
            {
                "ghko-Aiddoo--Aido-platform-issue-655": (
                    "3877f9457c1213cd2bb9ffa66582a4ea34e0494d",
                    2344,
                    "pass",
                ),
                "ghko-hissinger--small-village-issue-51": (
                    "e191b027d4c1a7d410b10958701b2c3ce9b9967c",
                    173,
                    "pass",
                ),
                "ghko-Soku-JINSEOK--Soku-Convention-Boilerplate-issue-19": (
                    "ad9c7296c25e328b5ba120f843b505300caa29d4",
                    113,
                    "fail",
                ),
            },
        )
        fourth_contextual = assessments[
            "fourth_contextual_batch_materialized_inventory"
        ]["candidates"]
        self.assertEqual(len(fourth_contextual), 1)
        self.assertEqual(
            fourth_contextual[0]["candidate_id"],
            "ghmix-genonai--doc_parser-issue-288",
        )
        self.assertEqual(
            fourth_contextual[0]["api_base_revision_not_used"],
            "b4b2b17becf049d77a1cc87526b9ed178635f058",
        )
        self.assertFalse(fourth_contextual[0]["api_base_is_head_ancestor"])
        self.assertEqual(
            fourth_contextual[0]["base_tree_hash"],
            "c7dd7005be6099763960903fd116a02dc29bf9fd",
        )
        self.assertEqual(fourth_contextual[0]["tree_entry_count"], 1167)
        self.assertEqual(fourth_contextual[0]["assessment"], "pass")
        fifth_contextual = assessments[
            "fifth_contextual_batch_materialized_inventory"
        ]["candidates"]
        self.assertEqual(len(fifth_contextual), 1)
        self.assertEqual(
            fifth_contextual[0]["candidate_id"],
            "ghmix-KoreaNirsa--prompt-booster-issue-10",
        )
        self.assertEqual(
            fifth_contextual[0]["base_revision"],
            "5f6a045a7d8fae7fc3b4df6150cf98d3cee8acb2",
        )
        self.assertEqual(
            fifth_contextual[0]["base_tree_hash"],
            "7476e28bbd9ff11cd305f755098f9955bfae70bd",
        )
        self.assertEqual(fifth_contextual[0]["tree_entry_count"], 28)
        self.assertEqual(fifth_contextual[0]["assessment"], "pass")
        sixth_contextual = assessments[
            "sixth_contextual_batch_materialized_inventory"
        ]["candidates"]
        self.assertEqual(len(sixth_contextual), 1)
        self.assertEqual(
            sixth_contextual[0]["candidate_id"],
            "ghko-minacle--swift-tui-issue-18",
        )
        self.assertEqual(
            sixth_contextual[0]["base_tree_hash"],
            "56bf597e58a103217d56530007f9ec30ee9f187e",
        )
        self.assertEqual(sixth_contextual[0]["tree_entry_count"], 224)
        self.assertEqual(sixth_contextual[0]["assessment"], "fail")
        self.assertEqual(
            sixth_contextual[0]["workspace_root_matching_paths"][0]["blob_sha"],
            "1d6e381624e8701843aeaa28b9ccd1835a92e4c1",
        )
        seventh_contextual = assessments[
            "seventh_contextual_batch_materialized_inventory"
        ]["candidates"]
        self.assertEqual(len(seventh_contextual), 1)
        self.assertEqual(
            seventh_contextual[0]["candidate_id"],
            "ghmix-ohhalim--MembershipFlow-issue-79",
        )
        self.assertEqual(
            seventh_contextual[0]["base_tree_hash"],
            "43678ee48b587b4404e944b50deba0c56824ff40",
        )
        self.assertEqual(seventh_contextual[0]["tree_entry_count"], 155)
        self.assertEqual(seventh_contextual[0]["assessment"], "pass")
        self.assertEqual(seventh_contextual[0]["workspace_root_matching_paths"], [])
        eighth_contextual = assessments[
            "eighth_contextual_batch_materialized_inventory"
        ]["candidates"]
        self.assertEqual(len(eighth_contextual), 1)
        self.assertEqual(
            eighth_contextual[0]["candidate_id"],
            "ghmix-0xkkun--seoul-challenge-issue-30",
        )
        self.assertEqual(
            eighth_contextual[0]["base_tree_hash"],
            "f9058eebeb04463aac357ab037fe4d9449ed9338",
        )
        self.assertEqual(eighth_contextual[0]["tree_entry_count"], 146)
        self.assertEqual(eighth_contextual[0]["assessment"], "fail")
        self.assertEqual(
            eighth_contextual[0]["workspace_root_matching_paths"][0]["blob_sha"],
            "01623c43f8326517fb47c708e05d57c92c9aa25f",
        )
        ninth_contextual = assessments[
            "ninth_contextual_batch_materialized_inventory"
        ]["candidates"]
        self.assertEqual(len(ninth_contextual), 1)
        self.assertEqual(
            ninth_contextual[0]["candidate_id"],
            "ghmix-Gn0lee--oat-issue-410",
        )
        self.assertEqual(
            ninth_contextual[0]["base_tree_hash"],
            "2ea4b5e9cc61d7345734c4d3df483d7bcb0736dd",
        )
        self.assertEqual(ninth_contextual[0]["tree_entry_count"], 717)
        self.assertEqual(ninth_contextual[0]["assessment"], "fail")
        self.assertEqual(
            ninth_contextual[0]["workspace_root_matching_paths"][0]["blob_sha"],
            "0773a2b4a435bcfc2c29b47a1646d66687595d4e",
        )
        tenth_contextual = assessments[
            "tenth_contextual_batch_materialized_inventory"
        ]["candidates"]
        self.assertEqual(len(tenth_contextual), 1)
        self.assertEqual(
            tenth_contextual[0]["candidate_id"],
            "ghmix-handokei--subway-now-issue-1465",
        )
        self.assertEqual(
            tenth_contextual[0]["base_tree_hash"],
            "158cfbad7be784dbd5d7588ca4e3195ab2dfad22",
        )
        self.assertEqual(tenth_contextual[0]["tree_entry_count"], 985)
        self.assertEqual(tenth_contextual[0]["assessment"], "fail")
        self.assertEqual(
            tenth_contextual[0]["workspace_root_matching_paths"][0]["blob_sha"],
            "529d172c873e2f215d1d1dc691a0cbbd00053232",
        )
        eleventh_contextual = assessments[
            "eleventh_contextual_batch_materialized_inventory"
        ]["candidates"]
        self.assertEqual(len(eleventh_contextual), 1)
        self.assertEqual(
            eleventh_contextual[0]["candidate_id"],
            "ghmix-prgrms-aibe-devcourse--AIBE5_FinalProject_Team7_JackPot-issue-499",
        )
        self.assertEqual(
            eleventh_contextual[0]["base_tree_hash"],
            "6722de4d5709782f1a0a47643a08b36c984f9342",
        )
        self.assertEqual(eleventh_contextual[0]["tree_entry_count"], 520)
        self.assertEqual(eleventh_contextual[0]["assessment"], "pass")
        self.assertEqual(eleventh_contextual[0]["workspace_root_matching_paths"], [])
        twelfth_contextual = assessments[
            "twelfth_contextual_batch_materialized_inventory"
        ]["candidates"]
        self.assertEqual(len(twelfth_contextual), 1)
        self.assertEqual(
            twelfth_contextual[0]["candidate_id"],
            "ghmix-SKALA-TEAM5--frontend-issue-66",
        )
        self.assertEqual(
            twelfth_contextual[0]["base_tree_hash"],
            "55524f7af8c79871fe5a9f8dd1e94a89060506a9",
        )
        self.assertEqual(twelfth_contextual[0]["tree_entry_count"], 68)
        self.assertEqual(twelfth_contextual[0]["assessment"], "pass")
        self.assertEqual(twelfth_contextual[0]["workspace_root_matching_paths"], [])
        rechecked = assessments["pinned_tree_inventory_recheck"]
        self.assertEqual(
            {
                candidate["candidate_id"]: (
                    candidate["base_tree_hash"],
                    candidate["tree_entry_count"],
                    candidate["truncated"],
                )
                for candidate in rechecked["candidates"]
            },
            {
                "ghmix-semantic-reasoning--factlog-issue-26": (
                    "12a8b1a18e99c07121bdcef7be87573383e13228",
                    77,
                    False,
                ),
                "ghmix-joshua-jingu-lee--ante-issue-2349": (
                    "c9df972424265b8a96e39ba06720138b6fe2d58b",
                    1057,
                    False,
                ),
                "ghko-SeoyunL--factlog-academic-issue-314": (
                    "47004414a82cbf9d2218cda3661690b15c159ef2",
                    373,
                    False,
                ),
                "ghmix-hskim-solv--BidMate-DocAgent-issue-1152": (
                    "40c93b2720fa97c94f479f0c5e13f6c4950df64b",
                    845,
                    False,
                ),
            },
        )
        confounder = artifact["global_instruction_confounder_2026_07_22"]
        self.assertEqual(confounder["gate_status"], "unresolved")
        self.assertEqual(
            confounder["claude_code"], {"private_inventory_disclosed": False}
        )
        self.assertEqual(
            confounder["codex"], {"private_inventory_disclosed": False}
        )
        self.assertNotIn("root", confounder["claude_code"])
        self.assertNotIn("imports", confounder["claude_code"])
        self.assertNotIn("root", confounder["codex"])
        self.assertNotIn("semantic_coverage", confounder["codex"])

    def test_v11_schemas_expose_candidate_and_global_instruction_gates(self) -> None:
        candidate_schema = json.loads(
            CANDIDATE_SCHEMA_PATH.read_text(encoding="utf-8")
        )
        manifest_schema = json.loads(
            MANIFEST_SCHEMA_PATH.read_text(encoding="utf-8")
        )

        self.assertEqual(
            candidate_schema["properties"]["protocol_version"]["const"],
            "phase2b-pilot-prereg-v1.1",
        )
        self.assertIn(
            "instruction-parity",
            candidate_schema["properties"]["inclusion_rule_ids"]["const"],
        )
        self.assertIn(
            "instruction-parity-mismatch",
            candidate_schema["properties"]["exclusion_rule_ids"]["const"],
        )

        self.assertEqual(
            manifest_schema["properties"]["protocol_version"]["const"],
            "phase2b-pilot-prereg-v1.1",
        )
        environment = manifest_schema["$defs"]["environment"]
        self.assertIn("global_instruction_context", environment["required"])
        resolution = manifest_schema["$defs"]["globalInstructionContext"][
            "properties"
        ]["resolution"]["enum"]
        self.assertEqual(
            set(resolution),
            {
                "semantically-equivalent",
                "isolated-empty-agent-homes",
            },
        )
        self.assertEqual(
            manifest_schema["$defs"]["globalInstructionContext"]["properties"][
                "codex_project_doc_fallback_filenames"
            ]["const"],
            [],
        )


if __name__ == "__main__":
    unittest.main()
