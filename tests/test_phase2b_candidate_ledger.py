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
        self.assertEqual(len(reviewed), 29)
        self.assertEqual(
            Counter(candidate["source_kind"] for candidate in candidates),
            {"public-issue-discovery": 384, "public-issue-pr-pair": 27},
        )
        self.assertEqual(
            Counter(candidate["decision"] for candidate in reviewed),
            {
                "screening": 1,
                "excluded": 27,
                "selected-for-task-authoring": 1,
            },
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

        # A missing runtime on the screening host was not an exclusion reason on its
        # own. factlog was subsequently reproduced and passes; swift-tui remains
        # screening because its evaluator path is unresolved.
        factlog = by_id["ghko-SeoyunL--factlog-academic-issue-314"]
        self.assertEqual(factlog["decision"], "selected-for-task-authoring")
        self.assertEqual(factlog["exclusion_rule_ids_triggered"], [])
        self.assertEqual(factlog["screening"]["reproducible_within_budget"], "pass")
        self.assertEqual(factlog["screening"]["instruction_parity"], "pass")

        swift = by_id["ghko-minacle--swift-tui-issue-18"]
        self.assertEqual(swift["decision"], "screening")
        self.assertEqual(swift["exclusion_rule_ids_triggered"], [])
        self.assertEqual(swift["screening"]["native_language_source"], "pass")
        self.assertEqual(swift["screening"]["exact_base_resolvable"], "pass")
        self.assertEqual(swift["screening"]["reproducible_within_budget"], "unknown")
        self.assertEqual(swift["screening"]["instruction_parity"], "unknown")

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
                "screening": 14,
                "excluded": 34,
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

            if candidate_id == "ghko-SeoyunL--factlog-academic-issue-342":
                self.assertEqual(candidate["decision"], "screening")
                self.assertEqual(candidate["exclusion_rule_ids_triggered"], [])
                self.assertEqual(candidate["screening"]["instruction_parity"], "pass")
            elif candidate_id == "ghko-yvshdjcsldhdjt--ChunChuGwan-issue-406":
                self.assertEqual(candidate["decision"], "screening")
                self.assertEqual(candidate["exclusion_rule_ids_triggered"], [])
                self.assertEqual(
                    candidate["screening"]["instruction_parity"], "unknown"
                )
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
        self.assertEqual(advancing["decision"], "screening")
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
        self.assertEqual(advancing["screening"]["instruction_parity"], "unknown")

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
            self.assertEqual(
                by_id[candidate_id]["exclusion_rule_ids_triggered"],
                ["instruction-parity-mismatch"],
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
        self.assertEqual(len(assessments["assessments"]), 14)
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
        self.assertEqual(second_contextual[0]["assessment"], "unknown")
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
        self.assertEqual(
            artifact["global_instruction_confounder_2026_07_22"]["gate_status"],
            "unresolved",
        )

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
