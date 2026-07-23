from __future__ import annotations

import hashlib
import json
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = ROOT / "experiments" / "phase2b-candidate-ledger-v1.json"
LICENSE_PROBE_PATH = ROOT / "experiments" / "phase2b-license-probe-2026-07-19.json"
LICENSE_PRIORITY_PATH = (
    ROOT / "experiments" / "phase2b-license-priority-2026-07-24.json"
)
LICENSE_CLASSIFICATION_PATH = (
    ROOT
    / "experiments"
    / "phase2b-license-file-classification-2026-07-24.json"
)
LINKED_SOLUTION_PREFILTER_PATH = (
    ROOT
    / "experiments"
    / "phase2b-linked-solution-prefilter-2026-07-24.json"
)
EXACT_REVISION_LICENSE_PATH = (
    ROOT / "experiments" / "phase2b-exact-revision-license-2026-07-24.json"
)
RANK5_APPLICATION_PATH = (
    ROOT
    / "experiments"
    / "phase2b-rank5-ledger-application-2026-07-24.json"
)
RANK6_PARITY_PATH = (
    ROOT / "experiments" / "phase2b-rank6-instruction-parity-2026-07-24.json"
)
RANK6_APPLICATION_PATH = (
    ROOT
    / "experiments"
    / "phase2b-rank6-ledger-application-2026-07-24.json"
)
RANK7_SEMANTIC_PATH = (
    ROOT / "experiments" / "phase2b-rank7-semantic-prefilter-2026-07-24.json"
)
RANK7_REPRODUCTION_PATH = (
    ROOT
    / "experiments"
    / "phase2b-rank7-agent-free-reproduction-2026-07-24.json"
)
RANK7_APPLICATION_PATH = (
    ROOT
    / "experiments"
    / "phase2b-rank7-ledger-application-2026-07-24.json"
)
PRE_RANK5_LEDGER_SHA256 = (
    "b59ff7449f5ebd50c182eeffb72abe9c0231b82dacb915a61c2d61e94c8d9bd2"
)
PRE_RANK6_LEDGER_SHA256 = (
    "faf4ee88177adc32e97cd331a6700ce55624f56eb0ec2db886126e086639ce2c"
)
PRE_RANK7_LEDGER_SHA256 = (
    "228dbbf05ec46a7f94dde40e780bad9b6d64a32944ace5bddb49839f15a1a0f1"
)
SCREENING_CASCADE_PATH = (
    ROOT / "experiments" / "phase2b-screening-cascade-2026-07-24.json"
)
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
        rank7_application = json.loads(
            RANK7_APPLICATION_PATH.read_text(encoding="utf-8")
        )
        self.rank7_mutations = {
            row["candidate_id"]: row for row in rank7_application["mutations"]
        }

    def _current_decision_after_rank7(
        self, candidate_id: str, prior_decision: str
    ) -> str:
        mutation = self.rank7_mutations.get(candidate_id)
        return mutation["after_decision"] if mutation else prior_decision

    def _current_exclusions_after_rank7(
        self, candidate_id: str, prior_exclusions: list[str]
    ) -> list[str]:
        mutation = self.rank7_mutations.get(candidate_id)
        return (
            mutation["exclusion_rule_ids_triggered"]
            if mutation
            else prior_exclusions
        )

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
            and candidate["candidate_id"] not in self.rank7_mutations
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
                # Rank 5 resolved the exact bases for eleven more Korean-bearing
                # rows. Four may still be excluded at this or later gates.
                "ghko-kangkyunghyun--LinKHU-issue-67",
                "ghko-dungsil-ai--intellij-plugin-egovframe-issue-4",
                "ghko-hissinger--small-village-issue-54",
                "ghko-yvshdjcsldhdjt--ChunChuGwan-issue-403",
                "ghko-kangkyunghyun--LinKHU-issue-89",
                "ghko-kangkyunghyun--LinKHU-issue-81",
                "ghko-prgrms-be-adv-devcourse--beadv6_6_3JMT_BE-issue-394",
                "ghko-happyduck-git--RetroNote-issue-81",
                "ghko-nodease--mbased-issue-528",
                "ghko-MannaDevelopers--meditation_blossom_frontend-issue-185",
                "ghko-hang-in--tunaRound-issue-131",
            },
        )

    def test_license_probe_is_never_treated_as_terminal(self) -> None:
        probe = json.loads(LICENSE_PROBE_PATH.read_text(encoding="utf-8"))
        exact = json.loads(EXACT_REVISION_LICENSE_PATH.read_text(encoding="utf-8"))
        preexisting_license_by_id = {
            row["candidate_id"]: row["ledger_preexisting_license_state"]
            for row in exact["observations"]
        }

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

    def test_license_priority_recomputes_current_screening_buckets(self) -> None:
        artifact = json.loads(LICENSE_PRIORITY_PATH.read_text(encoding="utf-8"))
        probe = json.loads(LICENSE_PROBE_PATH.read_text(encoding="utf-8"))
        exact = json.loads(EXACT_REVISION_LICENSE_PATH.read_text(encoding="utf-8"))
        preexisting_license_by_id = {
            row["candidate_id"]: row["ledger_preexisting_license_state"]
            for row in exact["observations"]
        }
        probe_by_key = {
            entry["repository"]: entry
            for entry in probe["entries"]
        }
        screening = [
            candidate
            for candidate in self.ledger["candidates"]
            if candidate["decision"] == "screening"
            or candidate["candidate_id"] in preexisting_license_by_id
        ]
        github = [
            candidate
            for candidate in screening
            if candidate["source_pool_id"].startswith("github-")
        ]

        def signal_for(candidate: dict[str, object]) -> str:
            repository = str(candidate["repository_id"]).replace("--", "/")
            entry = probe_by_key.get(repository)
            return "not-probed" if entry is None else entry["signal"]

        def license_state_at_snapshot(candidate: dict[str, object]) -> str:
            return preexisting_license_by_id.get(
                str(candidate["candidate_id"]),
                candidate["screening"]["license_or_use_basis"],
            )

        self.assertFalse(artifact["terminal_status"])
        self.assertEqual(
            artifact["protocol_version"], "phase2b-pilot-prereg-v1.1"
        )
        self.assertEqual(
            artifact["summary"],
            {
                "candidate_count": len(self.ledger["candidates"]),
                "screening_count": len(screening),
                "local_screening_pinned_license_pass": sum(
                    candidate["source_pool_id"]
                    == "aao-local-history-through-0e32241"
                    for candidate in screening
                ),
                "swebench_screening_exact_base_upstream_license_unverified": sum(
                    candidate["source_pool_id"]
                    == "swebench-multilingual-at-2b7aced"
                    for candidate in screening
                ),
                "github_screening_count": len(github),
                "github_pinned_license_pass": sum(
                    license_state_at_snapshot(candidate) == "pass"
                    for candidate in github
                ),
                "github_permissive_classifier_awaiting_exact_revision": 36,
                "github_file_only_awaiting_classification_and_exact_revision": 66,
                "github_ineligible_classifier_awaiting_exact_revision": 2,
                "github_none_observed_deferred": sum(
                    signal_for(candidate) == "none-observed"
                    for candidate in github
                ),
                "github_not_probed": sum(
                    signal_for(candidate) == "not-probed" for candidate in github
                ),
                "github_nonterminal_license_signal_rows": sum(
                    signal_for(candidate) == "license-artifact-or-spdx-present"
                    for candidate in github
                ),
                "github_deep_review_queue_after_classifier_filter": 104,
            },
        )

        expected_hashes = {
            "experiments/phase2b-candidate-ledger-v1.json": PRE_RANK5_LEDGER_SHA256,
            "experiments/phase2b-license-probe-2026-07-19.json": hashlib.sha256(
                LICENSE_PROBE_PATH.read_bytes()
            ).hexdigest(),
        }
        self.assertEqual(
            {
                entry["path"]: entry["sha256"]
                for entry in artifact["input_artifacts"]
            },
            expected_hashes,
        )

    def test_license_priority_never_promotes_unpinned_probe_signals(self) -> None:
        artifact = json.loads(LICENSE_PRIORITY_PATH.read_text(encoding="utf-8"))
        exact = json.loads(EXACT_REVISION_LICENSE_PATH.read_text(encoding="utf-8"))
        parity = json.loads(RANK6_PARITY_PATH.read_text(encoding="utf-8"))
        exact_by_id = {
            row["candidate_id"]: row for row in exact["observations"]
        }
        parity_by_id = {
            row["candidate_id"]: row for row in parity["assessments"]
        }
        by_id = {
            candidate["candidate_id"]: candidate
            for candidate in self.ledger["candidates"]
        }
        buckets = artifact["buckets"]
        explicit_bucket_names = [
            "pinned_license_pass_ready_for_remaining_rules",
            "ineligible_classifier_awaiting_exact_revision",
            "permissive_classifier_awaiting_exact_revision",
            "file_only_awaiting_classification_and_exact_revision",
            "not_probed",
        ]
        listed = [
            candidate
            for bucket_name in explicit_bucket_names
            for candidate in buckets[bucket_name]["candidates"]
        ]

        self.assertEqual(len(listed), len({row["candidate_id"] for row in listed}))
        for bucket_name in explicit_bucket_names:
            rows = buckets[bucket_name]["candidates"]
            self.assertEqual(
                [row["ledger_index"] for row in rows],
                sorted(row["ledger_index"] for row in rows),
            )
            self.assertEqual(buckets[bucket_name]["count"], len(rows))

        pinned = buckets["pinned_license_pass_ready_for_remaining_rules"][
            "candidates"
        ]
        self.assertEqual(len(pinned), 2)
        for row in pinned:
            candidate = by_id[row["candidate_id"]]
            prior_decision = (
                "excluded"
                if row["candidate_id"] in parity_by_id
                and parity_by_id[row["candidate_id"]]["result"] == "fail"
                else "screening"
            )
            self.assertEqual(
                candidate["decision"],
                self._current_decision_after_rank7(
                    row["candidate_id"], prior_decision
                ),
            )
            self.assertEqual(candidate["screening"]["license_or_use_basis"], "pass")
            self.assertTrue(candidate["base_revision"])

        eligible = set(artifact["eligible_permissive_spdx_ids"])
        for row in buckets["permissive_classifier_awaiting_exact_revision"][
            "candidates"
        ]:
            candidate = by_id[row["candidate_id"]]
            self.assertIn(row["classifier_spdx_id"], eligible)
            evidence = exact_by_id.get(row["candidate_id"])
            if evidence is None:
                self.assertEqual(
                    candidate["screening"]["license_or_use_basis"], "unknown"
                )
            else:
                self.assertEqual(
                    candidate["screening"]["license_or_use_basis"],
                    evidence["license_or_use_basis_decision"],
                )
                self.assertEqual(candidate["base_revision"], evidence["base_revision"])
            prior_decision = (
                "excluded"
                if evidence is not None
                and (
                    evidence["license_or_use_basis_decision"] == "fail"
                    or (
                        row["candidate_id"] in parity_by_id
                        and parity_by_id[row["candidate_id"]]["result"] == "fail"
                    )
                )
                else "screening"
            )
            self.assertEqual(
                candidate["decision"],
                self._current_decision_after_rank7(
                    row["candidate_id"], prior_decision
                ),
            )

        ineligible = set(artifact["explicitly_ineligible_classifier_ids"])

        def assert_current_state(row: dict[str, object]) -> None:
            candidate = by_id[row["candidate_id"]]
            evidence = exact_by_id.get(row["candidate_id"])
            if evidence is None:
                self.assertEqual(
                    candidate["screening"]["license_or_use_basis"], "unknown"
                )
                self.assertEqual(candidate["decision"], "screening")
                return
            self.assertEqual(
                candidate["screening"]["license_or_use_basis"],
                evidence["license_or_use_basis_decision"],
            )
            self.assertEqual(candidate["base_revision"], evidence["base_revision"])
            self.assertEqual(candidate["base_tree_hash"], evidence["base_tree_hash"])
            prior_decision = (
                "excluded"
                if evidence["license_or_use_basis_decision"] == "fail"
                or (
                    row["candidate_id"] in parity_by_id
                    and parity_by_id[row["candidate_id"]]["result"] == "fail"
                )
                else "screening"
            )
            self.assertEqual(
                candidate["decision"],
                self._current_decision_after_rank7(
                    row["candidate_id"], prior_decision
                ),
            )

        for row in buckets["ineligible_classifier_awaiting_exact_revision"][
            "candidates"
        ]:
            self.assertIn(row["classifier_spdx_id"], ineligible)
            assert_current_state(row)

        for row in buckets["file_only_awaiting_classification_and_exact_revision"][
            "candidates"
        ]:
            self.assertIsNone(row["classifier_spdx_id"])
            self.assertTrue(row["license_file_at_head"])
            assert_current_state(row)

        for row in buckets["not_probed"]["candidates"]:
            candidate = by_id[row["candidate_id"]]
            self.assertIsNone(row["probe_method"])
            self.assertEqual(candidate["screening"]["license_or_use_basis"], "unknown")
            self.assertEqual(candidate["decision"], "screening")

        self.assertEqual(
            artifact["summary"]["github_deep_review_queue_after_classifier_filter"],
            len(pinned)
            + buckets["permissive_classifier_awaiting_exact_revision"]["count"]
            + buckets["file_only_awaiting_classification_and_exact_revision"]["count"],
        )

    def test_file_only_license_classification_is_complete_and_nonterminal(self) -> None:
        artifact = json.loads(
            LICENSE_CLASSIFICATION_PATH.read_text(encoding="utf-8")
        )
        priority = json.loads(LICENSE_PRIORITY_PATH.read_text(encoding="utf-8"))
        exact = json.loads(EXACT_REVISION_LICENSE_PATH.read_text(encoding="utf-8"))
        parity = json.loads(RANK6_PARITY_PATH.read_text(encoding="utf-8"))
        exact_by_id = {
            row["candidate_id"]: row for row in exact["observations"]
        }
        parity_by_id = {
            row["candidate_id"]: row for row in parity["assessments"]
        }
        repositories = artifact["repositories"]
        classified_ids = {
            candidate_id
            for repository in repositories
            for candidate_id in repository["candidate_ids"]
        }
        expected_ids = {
            row["candidate_id"]
            for row in priority["buckets"][
                "file_only_awaiting_classification_and_exact_revision"
            ]["candidates"]
        }
        by_id = {
            candidate["candidate_id"]: candidate
            for candidate in self.ledger["candidates"]
        }

        self.assertFalse(artifact["terminal_status"])
        self.assertFalse(artifact["agent_results_observed"])
        self.assertEqual(len(repositories), 33)
        self.assertEqual(classified_ids, expected_ids)
        self.assertEqual(len(classified_ids), 66)
        self.assertEqual(
            artifact["summary"][
                "repository_counts_by_current_head_classification"
            ],
            {
                "eligible-permissive-current-head": 31,
                "suspected-ineligible-copyleft-current-head": 1,
                "suspected-ineligible-noncommercial-current-head": 1,
            },
        )
        self.assertEqual(
            artifact["summary"][
                "candidate_counts_by_current_head_classification"
            ],
            {
                "eligible-permissive-current-head": 64,
                "suspected-ineligible-copyleft-current-head": 1,
                "suspected-ineligible-noncommercial-current-head": 1,
            },
        )
        self.assertEqual(
            artifact["summary"][
                "github_deep_review_queue_after_current_head_classification"
            ],
            102,
        )
        self.assertEqual(
            artifact["summary"][
                "github_suspected_ineligible_exact_revision_queue"
            ],
            4,
        )
        self.assertEqual(artifact["summary"]["unknown_rows_after_classification"], 0)

        self.assertEqual(
            artifact["input_artifacts"],
            [
                {
                    "path": "experiments/phase2b-license-priority-2026-07-24.json",
                    "sha256": hashlib.sha256(
                        LICENSE_PRIORITY_PATH.read_bytes()
                    ).hexdigest(),
                }
            ],
        )
        self.assertEqual(
            sum(
                repository["review_method"]
                == "full-license-text-two-pass-review"
                for repository in repositories
            ),
            3,
        )
        for repository in repositories:
            self.assertRegex(repository["observed_head_revision"], r"^[0-9a-f]{40}$")
            self.assertRegex(repository["license_blob_sha"], r"^[0-9a-f]{40}$")
            self.assertRegex(
                repository["license_content_sha256"], r"^[0-9a-f]{64}$"
            )
            self.assertFalse(repository["terminal_status"])
            for candidate_id in repository["candidate_ids"]:
                candidate = by_id[candidate_id]
                evidence = exact_by_id.get(candidate_id)
                if evidence is None:
                    self.assertEqual(candidate["decision"], "screening")
                    self.assertEqual(
                        candidate["screening"]["license_or_use_basis"], "unknown"
                    )
                    continue
                self.assertEqual(
                    candidate["screening"]["license_or_use_basis"],
                    evidence["license_or_use_basis_decision"],
                )
                self.assertEqual(candidate["base_revision"], evidence["base_revision"])
                self.assertEqual(candidate["base_tree_hash"], evidence["base_tree_hash"])
                prior_decision = (
                    "excluded"
                    if evidence["license_or_use_basis_decision"] == "fail"
                    or (
                        candidate_id in parity_by_id
                        and parity_by_id[candidate_id]["result"] == "fail"
                    )
                    else "screening"
                )
                self.assertEqual(
                    candidate["decision"],
                    self._current_decision_after_rank7(
                        candidate_id, prior_decision
                    ),
                )

    def test_linked_solution_prefilter_is_complete_and_nonterminal(self) -> None:
        artifact = json.loads(
            LINKED_SOLUTION_PREFILTER_PATH.read_text(encoding="utf-8")
        )
        priority = json.loads(LICENSE_PRIORITY_PATH.read_text(encoding="utf-8"))
        exact = json.loads(EXACT_REVISION_LICENSE_PATH.read_text(encoding="utf-8"))
        parity = json.loads(RANK6_PARITY_PATH.read_text(encoding="utf-8"))
        exact_by_id = {
            row["candidate_id"]: row for row in exact["observations"]
        }
        parity_by_id = {
            row["candidate_id"]: row for row in parity["assessments"]
        }
        expected_ids = {
            row["candidate_id"]
            for bucket in (
                "pinned_license_pass_ready_for_remaining_rules",
                "permissive_classifier_awaiting_exact_revision",
                "ineligible_classifier_awaiting_exact_revision",
                "file_only_awaiting_classification_and_exact_revision",
            )
            for row in priority["buckets"][bucket]["candidates"]
        }
        candidate_rows = artifact["candidate_rows"]
        pull_requests = artifact["pull_requests"]
        queues = artifact["priority_queues"]
        listed_ids = {
            candidate_id
            for queue in queues.values()
            for candidate_id in queue
        }
        by_id = {
            candidate["candidate_id"]: candidate
            for candidate in self.ledger["candidates"]
        }

        self.assertFalse(artifact["terminal_status"])
        self.assertFalse(artifact["agent_results_observed"])
        self.assertEqual(len(candidate_rows), 106)
        self.assertEqual(listed_ids, expected_ids)
        self.assertEqual(
            sum(len(queue) for queue in queues.values()), len(listed_ids)
        )
        self.assertEqual(
            {
                name: len(candidate_ids)
                for name, candidate_ids in queues.items()
            },
            {
                "advance_exact_base_and_pinned_license": 27,
                "advance_suspected_ineligible_exact_revision_confirmation": 4,
                "needs_solution_segmentation_or_multi_issue_review": 18,
                "deferred_no_test_touch_single_scope": 57,
            },
        )
        self.assertEqual(len(pull_requests), 107)
        self.assertEqual(len({row["url"] for row in pull_requests}), 107)
        self.assertTrue(
            artifact["collection_integrity"][
                "all_required_observations_complete"
            ]
        )
        for row in candidate_rows:
            self.assertEqual(row["issue_html_status"], 200)
            self.assertRegex(row["issue_html_sha256"], r"^[0-9a-f]{64}$")
            self.assertFalse(row["terminal_status"])
            candidate = by_id[row["candidate_id"]]
            evidence = exact_by_id.get(row["candidate_id"])
            if evidence is None:
                self.assertEqual(candidate["decision"], "screening")
                continue
            self.assertEqual(candidate["base_revision"], evidence["base_revision"])
            self.assertEqual(candidate["base_tree_hash"], evidence["base_tree_hash"])
            prior_decision = (
                "excluded"
                if evidence["license_or_use_basis_decision"] == "fail"
                or (
                    row["candidate_id"] in parity_by_id
                    and parity_by_id[row["candidate_id"]]["result"] == "fail"
                )
                else "screening"
            )
            self.assertEqual(
                candidate["decision"],
                self._current_decision_after_rank7(
                    row["candidate_id"], prior_decision
                ),
            )
        for pull_request in pull_requests:
            self.assertEqual(pull_request["html_status"], 200)
            self.assertEqual(pull_request["diff_status"], 200)
            self.assertRegex(pull_request["html_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(pull_request["diff_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(pull_request["head_revision"], r"^[0-9a-f]{40}$")
            self.assertFalse(pull_request["terminal_status"])

        # Documentation paths named specs/test_cases are not executable test touch.
        no_test_ids = set(queues["deferred_no_test_touch_single_scope"])
        self.assertIn("ghmix-joshua-jingu-lee--ante-issue-2353", no_test_ids)
        self.assertIn("ghmix-joshua-jingu-lee--ante-issue-2390", no_test_ids)
        mbased_509 = next(
            row
            for row in pull_requests
            if row["url"] == "https://github.com/nodease/mbased/pull/509"
        )
        self.assertFalse(mbased_509["test_touch"])

        # A later stacked superset is scope-review, while the smaller complete
        # prefix PR remains eligible for its own issue.
        self.assertIn(
            "ghko-dungsil-ai--intellij-plugin-egovframe-issue-4",
            queues["advance_exact_base_and_pinned_license"],
        )
        self.assertIn(
            "ghko-dungsil-ai--intellij-plugin-egovframe-issue-5",
            queues["needs_solution_segmentation_or_multi_issue_review"],
        )

    def test_exact_revision_license_results_and_ledger_application_are_bound(self) -> None:
        exact = json.loads(EXACT_REVISION_LICENSE_PATH.read_text(encoding="utf-8"))
        application = json.loads(RANK5_APPLICATION_PATH.read_text(encoding="utf-8"))
        observations = exact["observations"]
        by_id = {
            candidate["candidate_id"]: candidate
            for candidate in self.ledger["candidates"]
        }

        self.assertTrue(exact["terminal_status"])
        self.assertIn(
            "terminal only for exact-base-resolvable and license-or-use-basis",
            exact["terminal_status_note"],
        )
        self.assertFalse(exact["agent_results_observed"])
        self.assertEqual(len(observations), 31)
        self.assertEqual(
            exact["collection_integrity"],
            {
                "source_observation_sha256": exact["collection_integrity"][
                    "source_observation_sha256"
                ],
                "requested_candidates": 31,
                "observed_candidates": 31,
                "failures": 0,
                "head_matches": 31,
                "commit_sequence_ancestry_ok": 31,
                "single_parent_first_solution_commit": 31,
                "github_diff_changed_paths_match": 31,
                "git_and_github_diff_byte_hash_match": 15,
            },
        )
        self.assertRegex(
            exact["collection_integrity"]["source_observation_sha256"],
            r"^[0-9a-f]{64}$",
        )
        self.assertEqual(
            exact["summary"],
            {
                "candidate_count": 31,
                "eligible_priority_input_rows": 27,
                "suspected_ineligible_confirmation_input_rows": 4,
                "license_counts_at_exact_base": {
                    "AGPL-3.0": 1,
                    "Apache-2.0": 6,
                    "GPL-3.0": 2,
                    "MIT": 21,
                    "absent": 1,
                },
                "license_pass_rows": 27,
                "license_fail_rows": 4,
                "eligible_priority_license_pass_rows": 26,
                "eligible_priority_license_fail_rows": 1,
                "suspected_queue_license_pass_rows": 1,
                "suspected_queue_license_fail_rows": 3,
                "comparable_current_head_signal_rows": 30,
                "current_head_signal_agreement_rows": 28,
                "current_head_signal_disagreement_rows": 2,
                "advance_remaining_rule_review_rows": 26,
                "return_to_solution_scope_review_rows": 1,
                "terminal_license_exclusion_rows": 4,
            },
        )
        self.assertTrue(
            all(
                row["head_matches"]
                and row["commit_sequence_ancestry_ok"]
                and row["first_solution_commit_parent_count"] == 1
                and row["github_diff_changed_paths_match"]
                for row in observations
            )
        )
        self.assertEqual(
            {
                row["candidate_id"]
                for row in observations
                if row["next_route"] == "terminal_license_exclusion"
            },
            {
                "ghko-MannaDevelopers--meditation_blossom_frontend-issue-185",
                "ghko-hang-in--tunaRound-issue-131",
                "ghmix-landfill--secure-doc-issue-22",
                "ghmix-hsu3046--MarkMind-issue-117",
            },
        )
        self.assertEqual(
            exact["current_head_counterexamples"],
            [
                {
                    "candidate_id": "ghmix-baekenough--oh-my-customcode-issue-1415",
                    "current_head_signal": "PolyForm-Noncommercial-1.0.0",
                    "exact_base_result": "MIT",
                    "workflow_effect": "return_to_solution_scope_review",
                },
                {
                    "candidate_id": "ghmix-landfill--secure-doc-issue-22",
                    "current_head_signal": "MIT",
                    "exact_base_result": None,
                    "workflow_effect": "terminal_license_exclusion",
                },
            ],
        )
        landfill = next(
            row
            for row in observations
            if row["candidate_id"] == "ghmix-landfill--secure-doc-issue-22"
        )
        self.assertEqual(landfill["license_artifact_count"], 0)
        self.assertEqual(
            {artifact["path"] for artifact in landfill["fallback_basis_artifacts"]},
            {"README.md", "package.json"},
        )
        self.assertTrue(
            all(
                artifact["declared_license"] is None
                and artifact["detected_full_license_text"] is None
                and not artifact["license_word_present"]
                for artifact in landfill["fallback_basis_artifacts"]
            )
        )

        self.assertFalse(application["agent_results_observed"])
        self.assertEqual(
            application["input_artifacts"],
            [
                {
                    "path": "experiments/phase2b-candidate-ledger-v1.json",
                    "sha256": PRE_RANK5_LEDGER_SHA256,
                    "state": "pre-rank5 Git-tracked snapshot",
                },
                {
                    "path": "experiments/phase2b-exact-revision-license-2026-07-24.json",
                    "sha256": hashlib.sha256(
                        EXACT_REVISION_LICENSE_PATH.read_bytes()
                    ).hexdigest(),
                },
            ],
        )
        self.assertEqual(
            application["output_artifact"]["sha256"],
            PRE_RANK6_LEDGER_SHA256,
        )
        self.assertEqual(
            application["output_artifact"]["summary"]["screening_count"], 1021
        )
        self.assertEqual(
            application["output_artifact"]["summary"]["excluded_count"], 102
        )
        self.assertEqual(
            application["output_artifact"]["summary"][
                "selected_for_task_authoring_count"
            ],
            7,
        )
        self.assertEqual(
            application["summary"],
            {
                "candidate_rows_updated": 31,
                "new_exact_base_pass_rows": 30,
                "exact_license_pass_rows": 27,
                "new_license_pass_rows": 26,
                "new_terminal_license_exclusions": 4,
                "screening_after": 1021,
                "excluded_after": 102,
                "selected_after": 7,
            },
        )
        rank6_ids = {
            row["candidate_id"]
            for row in json.loads(RANK6_PARITY_PATH.read_text(encoding="utf-8"))[
                "assessments"
            ]
        }
        later_stage_ids = rank6_ids | set(self.rank7_mutations)
        for mutation in application["mutations"]:
            candidate = by_id[mutation["candidate_id"]]
            for field in (
                "base_revision",
                "base_tree_hash",
                "solution_revision",
                "solution_tree_hash",
                "solution_artifact_hash",
            ):
                self.assertEqual(candidate[field], mutation[field])
            if mutation["candidate_id"] not in later_stage_ids:
                self.assertEqual(candidate["decision"], mutation["decision"])
                self.assertEqual(
                    candidate["exclusion_rule_ids_triggered"],
                    mutation["exclusion_rule_ids_triggered"],
                )
            self.assertTrue(candidate["license_or_use_basis"])
            self.assertEqual(
                len(candidate["changed_files"]), mutation["changed_file_count"]
            )
            self.assertEqual(
                candidate["screening"]["exact_base_resolvable"],
                mutation["exact_base_resolvable"],
            )
            self.assertEqual(
                candidate["screening"]["license_or_use_basis"],
                mutation["license_or_use_basis"],
            )

    def test_rank6_instruction_parity_and_ledger_application_are_bound(self) -> None:
        parity = json.loads(RANK6_PARITY_PATH.read_text(encoding="utf-8"))
        application = json.loads(RANK6_APPLICATION_PATH.read_text(encoding="utf-8"))
        assessments = parity["assessments"]
        by_id = {
            candidate["candidate_id"]: candidate
            for candidate in self.ledger["candidates"]
        }

        self.assertTrue(parity["terminal_status"])
        self.assertFalse(parity["agent_results_observed"])
        self.assertFalse(parity["design_change_required"])
        self.assertEqual(
            parity["collection_integrity"],
            {
                "requested_candidates": 25,
                "observed_candidates": 25,
                "failures": 0,
                "exact_tree_hash_matches": 25,
            },
        )
        self.assertEqual(
            parity["summary"],
            {
                "candidate_count": 25,
                "no_discovered_instruction_rows": 5,
                "byte_equivalent_symlink_rows": 3,
                "explicit_semantic_adapter_rows": 1,
                "instruction_parity_pass_rows": 9,
                "instruction_parity_fail_rows": 16,
                "instruction_parity_unknown_rows": 0,
                "advance_boundedness_evaluator_reproduction_rows": 9,
                "terminal_instruction_parity_exclusion_rows": 16,
            },
        )
        self.assertEqual(len(assessments), 25)
        self.assertEqual(
            Counter(row["result"] for row in assessments), {"pass": 9, "fail": 16}
        )
        self.assertTrue(all(row["terminal_evidence"] for row in assessments))
        self.assertTrue(
            all(
                row["base_tree_hash"] == by_id[row["candidate_id"]]["base_tree_hash"]
                for row in assessments
            )
        )
        self.assertEqual(
            {
                row["candidate_id"]
                for row in assessments
                if row["result"] == "pass"
            },
            {
                "ghko-hissinger--small-village-issue-54",
                "ghko-yvshdjcsldhdjt--ChunChuGwan-issue-403",
                "ghmix-jeongsk--daily_stock_analysis-issue-3",
                "ghmix-JeremyDev87--kratos-issue-64",
                "ghmix-Sungho-pk42ac--agentguard-issue-687",
                "ghmix-Sungho-pk42ac--agentguard-issue-591",
                "ghmix-KoreaNirsa--prompt-booster-issue-3",
                "ghmix-MTGVim--telltale-issue-11",
                "ghmix-joshua-jingu-lee--ante-issue-2398",
            },
        )
        for row in assessments:
            candidate = by_id[row["candidate_id"]]
            self.assertEqual(
                candidate["screening"]["instruction_parity"], row["result"]
            )
            prior_decision = "excluded" if row["result"] == "fail" else "screening"
            prior_exclusions = (
                ["instruction-parity-mismatch"] if row["result"] == "fail" else []
            )
            self.assertEqual(
                candidate["decision"],
                self._current_decision_after_rank7(
                    row["candidate_id"], prior_decision
                ),
            )
            self.assertEqual(
                candidate["exclusion_rule_ids_triggered"],
                self._current_exclusions_after_rank7(
                    row["candidate_id"], prior_exclusions
                ),
            )
            for entry in row["task_active_instruction_entries"]:
                self.assertRegex(entry["object_sha"], r"^[0-9a-f]{40}$")
                self.assertRegex(entry["content_sha256"], r"^[0-9a-f]{64}$")

        self.assertFalse(application["agent_results_observed"])
        self.assertEqual(
            application["input_artifacts"],
            [
                {
                    "path": "experiments/phase2b-candidate-ledger-v1.json",
                    "sha256": PRE_RANK6_LEDGER_SHA256,
                    "state": "pre-rank6 Git-tracked working snapshot",
                },
                {
                    "path": "experiments/phase2b-rank6-instruction-parity-2026-07-24.json",
                    "sha256": hashlib.sha256(RANK6_PARITY_PATH.read_bytes()).hexdigest(),
                },
            ],
        )
        self.assertEqual(
            application["output_artifact"]["sha256"],
            PRE_RANK7_LEDGER_SHA256,
        )
        output_summary = application["output_artifact"]["summary"]
        self.assertEqual(
            {
                key: output_summary[key]
                for key in (
                    "candidate_count",
                    "screening_count",
                    "excluded_count",
                    "selected_for_task_authoring_count",
                )
            },
            {
                "candidate_count": 1130,
                "screening_count": 1005,
                "excluded_count": 118,
                "selected_for_task_authoring_count": 7,
            },
        )
        self.assertEqual(
            application["summary"],
            {
                "candidate_rows_updated": 25,
                "instruction_parity_pass_rows": 9,
                "instruction_parity_fail_rows": 16,
                "new_terminal_instruction_parity_exclusions": 16,
                "screening_after": 1005,
                "excluded_after": 118,
                "selected_after": 7,
            },
        )
        self.assertEqual(len(application["mutations"]), 25)
        for mutation in application["mutations"]:
            candidate = by_id[mutation["candidate_id"]]
            self.assertEqual(
                candidate["screening"]["instruction_parity"],
                mutation["instruction_parity"],
            )
            self.assertEqual(
                candidate["decision"],
                self._current_decision_after_rank7(
                    mutation["candidate_id"], mutation["decision"]
                ),
            )

    def test_rank7_semantics_reproduction_and_application_are_bound(self) -> None:
        semantic = json.loads(RANK7_SEMANTIC_PATH.read_text(encoding="utf-8"))
        reproduction = json.loads(
            RANK7_REPRODUCTION_PATH.read_text(encoding="utf-8")
        )
        application = json.loads(
            RANK7_APPLICATION_PATH.read_text(encoding="utf-8")
        )
        by_id = {
            candidate["candidate_id"]: candidate
            for candidate in self.ledger["candidates"]
        }
        semantic_by_id = {
            row["candidate_id"]: row for row in semantic["assessments"]
        }
        reproduction_by_id = {
            row["candidate_id"]: row for row in reproduction["results"]
        }

        self.assertFalse(semantic["agent_results_observed"])
        self.assertFalse(semantic["design_change_required"])
        self.assertEqual(
            semantic["input_artifacts"][0]["sha256"], PRE_RANK7_LEDGER_SHA256
        )
        self.assertEqual(
            semantic["summary"],
            {
                "candidate_count": 10,
                "translation_only_terminal_rows": 3,
                "multiple_coupled_issues_terminal_rows": 1,
                "terminal_exclusion_rows": 4,
                "advance_agent_free_reproduction_rows": 6,
                "selected_rows_created": 0,
            },
        )
        self.assertEqual(len(semantic_by_id), 10)
        self.assertEqual(
            set(semantic["next_queues"]["advance_agent_free_reproduction"]),
            {
                "ghko-hissinger--small-village-issue-54",
                "ghmix-genonai--doc_parser-issue-288",
                "ghmix-Sungho-pk42ac--agentguard-issue-687",
                "ghmix-Sungho-pk42ac--agentguard-issue-591",
                "ghmix-KoreaNirsa--prompt-booster-issue-3",
                "ghmix-joshua-jingu-lee--ante-issue-2398",
            },
        )
        self.assertEqual(
            {
                row["candidate_id"]: row["terminal_exclusion_ids"]
                for row in semantic["assessments"]
                if row["terminal_exclusion_ids"]
            },
            {
                "ghko-yvshdjcsldhdjt--ChunChuGwan-issue-403": [
                    "multiple-coupled-issues"
                ],
                "ghmix-jeongsk--daily_stock_analysis-issue-3": [
                    "translation-only"
                ],
                "ghmix-JeremyDev87--kratos-issue-64": ["translation-only"],
                "ghmix-MTGVim--telltale-issue-11": ["translation-only"],
            },
        )
        for candidate_id, row in semantic_by_id.items():
            candidate = by_id[candidate_id]
            self.assertEqual(
                row["task_statement_sha256"], candidate["task_statement_hash"]
            )
            self.assertEqual(
                row["source_snapshot_task_statement_sha256"],
                candidate["task_statement_hash"],
            )
            self.assertEqual(row["base_revision"], candidate["base_revision"])
            self.assertEqual(row["base_tree_hash"], candidate["base_tree_hash"])
            self.assertEqual(row["solution_revision"], candidate["solution_revision"])

        self.assertFalse(reproduction["agent_results_observed"])
        self.assertEqual(
            reproduction["input_artifacts"][1],
            {
                "path": "experiments/phase2b-rank7-semantic-prefilter-2026-07-24.json",
                "sha256": hashlib.sha256(RANK7_SEMANTIC_PATH.read_bytes()).hexdigest(),
            },
        )
        self.assertEqual(
            reproduction["summary"],
            {
                "candidate_count": 6,
                "base_negative_intended_rows": 6,
                "solution_positive_rows": 6,
                "reproducible_within_budget_pass_rows": 6,
                "small_bucket_rows": 4,
                "medium_bucket_rows": 2,
                "selected_for_task_authoring_routes": 6,
                "candidate_agent_executions": 0,
            },
        )
        self.assertEqual(
            set(reproduction_by_id),
            set(semantic["next_queues"]["advance_agent_free_reproduction"]),
        )
        self.assertEqual(
            Counter(row["bucket"] for row in reproduction["results"]),
            {"small": 4, "medium": 2},
        )
        for candidate_id, row in reproduction_by_id.items():
            candidate = by_id[candidate_id]
            for field in (
                "base_revision",
                "base_tree_hash",
                "solution_revision",
                "solution_tree_hash",
            ):
                self.assertEqual(row[field], candidate[field])
            self.assertTrue(row["exact_tree_matches_ledger"])
            self.assertTrue(row["negative_control_intended"])
            self.assertTrue(row["base_tracked_tree_clean_after_control"])
            self.assertTrue(row["solution_tracked_tree_clean_after_control"])
            self.assertEqual(row["reproducible_within_budget"], "pass")
            self.assertEqual(row["next_route"], "selected_for_task_authoring")
            for protected in row["protected_artifacts"]:
                self.assertRegex(protected["sha256"], r"^[0-9a-f]{64}$")
        self.assertTrue(
            any(
                "small-village final validity reviewer" in limitation
                for limitation in reproduction["known_limitations"]
            )
        )

        self.assertFalse(application["agent_results_observed"])
        self.assertEqual(
            application["input_artifacts"],
            [
                {
                    "path": "experiments/phase2b-candidate-ledger-v1.json",
                    "sha256": PRE_RANK7_LEDGER_SHA256,
                    "state": "pre-rank7 Git-tracked working snapshot",
                },
                {
                    "path": "experiments/phase2b-rank7-semantic-prefilter-2026-07-24.json",
                    "sha256": hashlib.sha256(RANK7_SEMANTIC_PATH.read_bytes()).hexdigest(),
                },
                {
                    "path": "experiments/phase2b-rank7-agent-free-reproduction-2026-07-24.json",
                    "sha256": hashlib.sha256(
                        RANK7_REPRODUCTION_PATH.read_bytes()
                    ).hexdigest(),
                },
            ],
        )
        self.assertEqual(
            application["summary"],
            {
                "candidate_rows_updated": 10,
                "terminal_source_exclusions": 4,
                "new_selected_for_task_authoring_rows": 6,
                "screening_after": 995,
                "excluded_after": 122,
                "selected_after": 13,
            },
        )
        self.assertEqual(
            application["output_artifact"]["sha256"],
            hashlib.sha256(LEDGER_PATH.read_bytes()).hexdigest(),
        )
        self.assertEqual(application["output_artifact"]["summary"], self.ledger["summary"])
        self.assertEqual(len(application["mutations"]), 10)
        for mutation in application["mutations"]:
            candidate = by_id[mutation["candidate_id"]]
            self.assertEqual(candidate["decision"], mutation["after_decision"])
            self.assertEqual(
                candidate["exclusion_rule_ids_triggered"],
                mutation["exclusion_rule_ids_triggered"],
            )
            self.assertEqual(
                candidate["provisional_classification"],
                mutation["provisional_classification"],
            )
            for field, value in mutation["screening_updates"].items():
                self.assertEqual(candidate["screening"][field], value)
            if mutation["after_decision"] == "selected-for-task-authoring":
                self.assertEqual(Counter(candidate["screening"].values()), {"pass": 12})

    def test_screening_cascade_is_nonterminal_and_cost_ordered(self) -> None:
        artifact = json.loads(SCREENING_CASCADE_PATH.read_text(encoding="utf-8"))
        stages = artifact["stage_sequence"]

        self.assertFalse(artifact["terminal_status"])
        self.assertFalse(artifact["agent_results_observed"])
        self.assertFalse(artifact["design_change_required"])
        self.assertEqual(
            artifact["protocol_version"], "phase2b-pilot-prereg-v1.1"
        )
        self.assertEqual([stage["rank"] for stage in stages], list(range(8)))
        self.assertEqual(
            [stage["stage_id"] for stage in stages],
            [
                "ledger-integrity-and-prior-state",
                "source-identity-presence",
                "repository-license-signal",
                "license-type-classification",
                "linked-solution-and-test-scope",
                "exact-base-and-pinned-license",
                "exact-tree-instruction-inventory",
                "boundedness-evaluator-and-reproduction",
            ],
        )
        self.assertTrue(all(not stage["terminal"] for stage in stages[:5]))
        self.assertTrue(all(stage["terminal"] for stage in stages[5:]))
        self.assertEqual(
            [stage["rank"] for stage in stages if stage["manual_semantic_review_required"]],
            [3, 6, 7],
        )

        expected_hashes = {
            "experiments/phase2b-candidate-ledger-v1.json": PRE_RANK5_LEDGER_SHA256,
            "experiments/phase2b-license-probe-2026-07-19.json": hashlib.sha256(
                LICENSE_PROBE_PATH.read_bytes()
            ).hexdigest(),
            "experiments/phase2b-license-priority-2026-07-24.json": hashlib.sha256(
                LICENSE_PRIORITY_PATH.read_bytes()
            ).hexdigest(),
            "experiments/phase2b-license-file-classification-2026-07-24.json": hashlib.sha256(
                LICENSE_CLASSIFICATION_PATH.read_bytes()
            ).hexdigest(),
            "experiments/phase2b-linked-solution-prefilter-2026-07-24.json": hashlib.sha256(
                LINKED_SOLUTION_PREFILTER_PATH.read_bytes()
            ).hexdigest(),
            "experiments/phase2b-exact-revision-license-2026-07-24.json": hashlib.sha256(
                EXACT_REVISION_LICENSE_PATH.read_bytes()
            ).hexdigest(),
            "experiments/phase2b-rank5-ledger-application-2026-07-24.json": hashlib.sha256(
                RANK5_APPLICATION_PATH.read_bytes()
            ).hexdigest(),
            "experiments/phase2b-rank6-instruction-parity-2026-07-24.json": hashlib.sha256(
                RANK6_PARITY_PATH.read_bytes()
            ).hexdigest(),
            "experiments/phase2b-rank6-ledger-application-2026-07-24.json": hashlib.sha256(
                RANK6_APPLICATION_PATH.read_bytes()
            ).hexdigest(),
            "experiments/phase2b-rank7-semantic-prefilter-2026-07-24.json": hashlib.sha256(
                RANK7_SEMANTIC_PATH.read_bytes()
            ).hexdigest(),
            "experiments/phase2b-rank7-agent-free-reproduction-2026-07-24.json": hashlib.sha256(
                RANK7_REPRODUCTION_PATH.read_bytes()
            ).hexdigest(),
            "experiments/phase2b-rank7-ledger-application-2026-07-24.json": hashlib.sha256(
                RANK7_APPLICATION_PATH.read_bytes()
            ).hexdigest(),
            "experiments/phase2b-mechanical-prefilter-2026-07-19.json": hashlib.sha256(
                (
                    ROOT
                    / "experiments"
                    / "phase2b-mechanical-prefilter-2026-07-19.json"
                ).read_bytes()
            ).hexdigest(),
        }
        self.assertEqual(
            {
                entry["path"]: entry["sha256"]
                for entry in artifact["input_artifacts"]
            },
            expected_hashes,
        )

    def test_screening_cascade_routes_current_pools_before_deep_review(self) -> None:
        cascade = json.loads(SCREENING_CASCADE_PATH.read_text(encoding="utf-8"))
        priority = json.loads(LICENSE_PRIORITY_PATH.read_text(encoding="utf-8"))
        classification = json.loads(
            LICENSE_CLASSIFICATION_PATH.read_text(encoding="utf-8")
        )
        linked_solution = json.loads(
            LINKED_SOLUTION_PREFILTER_PATH.read_text(encoding="utf-8")
        )
        exact = json.loads(EXACT_REVISION_LICENSE_PATH.read_text(encoding="utf-8"))
        exact_ids = {row["candidate_id"] for row in exact["observations"]}
        screening = [
            candidate
            for candidate in self.ledger["candidates"]
            if candidate["decision"] == "screening"
            or candidate["candidate_id"] in exact_ids
        ]
        by_pool = Counter(candidate["source_pool_id"] for candidate in screening)
        routes = cascade["pool_routes"]

        self.assertEqual(len(screening), 1025)
        self.assertEqual(
            routes["aao-local-history-through-0e32241"]["screening_rows"],
            by_pool["aao-local-history-through-0e32241"],
        )
        self.assertEqual(
            routes["swebench-multilingual-at-2b7aced"]["screening_rows"],
            by_pool["swebench-multilingual-at-2b7aced"],
        )
        github_count = sum(
            count
            for pool_id, count in by_pool.items()
            if pool_id.startswith("github-")
        )
        self.assertEqual(routes["github-current-screening"]["screening_rows"], 691)
        self.assertEqual(routes["github-current-screening"]["screening_rows"], github_count)
        self.assertEqual(
            routes["github-current-screening"][
                "deep_review_queue_after_current_head_classification"
            ],
            classification["summary"][
                "github_deep_review_queue_after_current_head_classification"
            ],
        )
        self.assertEqual(
            routes["github-current-screening"][
                "suspected_ineligible_requiring_exact_revision_confirmation"
            ],
            classification["summary"][
                "github_suspected_ineligible_exact_revision_queue"
            ],
        )
        self.assertEqual(
            routes["github-current-screening"][
                "exact_revision_queue_after_linked_solution_prefilter"
            ],
            linked_solution["summary"][
                "advance_exact_base_and_pinned_license_rows"
            ]
            + linked_solution["summary"][
                "suspected_ineligible_exact_confirmation_count"
            ],
        )
        self.assertEqual(
            routes["github-current-screening"]["deferred_none_observed"],
            priority["summary"]["github_none_observed_deferred"],
        )

        stages = {stage["stage_id"]: stage for stage in cascade["stage_sequence"]}
        self.assertEqual(
            stages["ledger-integrity-and-prior-state"]["observed"],
            {
                "screening": 1005,
                "excluded": 118,
                "selected_for_task_authoring": 7,
            },
        )
        self.assertEqual(
            stages["source-identity-presence"]["observed"],
            {
                "external_statement_and_hash_present": 991,
                "local_history_without_native_task_statement": 34,
            },
        )
        self.assertEqual(
            stages["license-type-classification"]["observed"],
            {
                "pinned_permissive_pass": 2,
                "permissive_classifier_signal": 36,
                "file_only_repositories_classified": 33,
                "file_only_candidate_rows_classified": 66,
                "file_only_eligible_permissive_current_head": 64,
                "file_only_suspected_ineligible_copyleft_current_head": 1,
                "file_only_suspected_ineligible_noncommercial_current_head": 1,
                "existing_ineligible_copyleft_classifier_signal": 2,
                "unknown_after_current_head_classification": 0,
            },
        )
        self.assertEqual(
            stages["linked-solution-and-test-scope"]["observed"],
            {
                "eligible_current_head_priority_rows": 102,
                "suspected_ineligible_exact_confirmation_rows": 4,
                "issue_html_200_and_parsed": 106,
                "unique_pull_request_html_and_diff_200": 107,
                "single_merged_closing_pr_rows": 103,
                "multiple_closing_pr_rows": 3,
                "eligible_single_pr_test_touch_rows": 37,
                "advance_exact_base_and_pinned_license_rows": 27,
                "advance_suspected_ineligible_confirmation_rows": 4,
                "needs_solution_scope_review_rows": 18,
                "deferred_no_test_touch_single_scope_rows": 57,
            },
        )
        self.assertEqual(
            stages["exact-base-and-pinned-license"]["observed"],
            {
                "github_exact_base_already_known_before_stage": 1,
                "github_new_exact_bases_resolved": 30,
                "github_eligible_priority_rows": 27,
                "github_suspected_ineligible_confirmation_rows": 4,
                "exact_license_pass_rows": 27,
                "exact_license_fail_rows": 4,
                "advance_remaining_rule_review_rows": 26,
                "return_to_solution_scope_review_rows": 1,
                "swebench_rows_with_recorded_base_but_missing_tree_and_upstream_license": 300,
                "swebench_upstream_repositories": 41,
            },
        )
        self.assertEqual(
            stages["exact-tree-instruction-inventory"]["observed"],
            {
                "instruction_parity_already_passed_before_stage": 1,
                "new_exact_tree_instruction_inventories_completed": 25,
                "new_instruction_parity_pass_rows": 9,
                "new_instruction_parity_fail_rows": 16,
                "advance_boundedness_evaluator_reproduction_rows": 10,
            },
        )
        self.assertEqual(
            stages["boundedness-evaluator-and-reproduction"]["observed"],
            {
                "source_semantic_rows_completed": 10,
                "translation_only_terminal_rows": 3,
                "multiple_coupled_issues_terminal_rows": 1,
                "advance_agent_free_reproduction_rows": 6,
                "intended_base_negative_rows": 6,
                "solution_positive_rows": 6,
                "reproducible_within_budget_pass_rows": 6,
                "small_bucket_rows": 4,
                "medium_bucket_rows": 2,
                "new_selected_for_task_authoring_rows": 6,
                "boundedness_evaluator_reproduction_pending": 0,
            },
        )
        self.assertEqual(
            stages["boundedness-evaluator-and-reproduction"]["input_rows"], 10
        )
        self.assertIn(
            "exact pre-solution revision and tree",
            cascade["terminal_or_pass_evidence_boundaries"],
        )

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

        self.assertEqual(len(rows), 25)
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
            and candidate["candidate_id"] not in self.rank7_mutations
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
        self.assertEqual(advancing["decision"], "selected-for-task-authoring")
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
        self.assertEqual(unresolved, set())
        self.assertEqual(
            Counter(advancing["screening"].values()),
            {"pass": 12},
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
        rank6 = json.loads(RANK6_PARITY_PATH.read_text(encoding="utf-8"))
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
        passing.update(
            row["candidate_id"]
            for row in rank6["assessments"]
            if row["result"] == "pass"
        )
        failing.update(
            row["candidate_id"]
            for row in rank6["assessments"]
            if row["result"] == "fail"
        )

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
