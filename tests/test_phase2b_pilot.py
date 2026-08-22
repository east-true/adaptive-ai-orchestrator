from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.execution.verification import (
    evaluator_content_version,
    hash_evaluator_artifacts,
)
from adaptive_orchestrator.core.domain import ExecutionStatus
from adaptive_orchestrator.execution.process_runner import ProcessResult
from adaptive_orchestrator.experiments.phase2b_pilot import (
    AUTHENTICATED_ISOLATED_AGENT_HOME_RESOLUTION,
    CATEGORY_QUOTA,
    EMPTY_EFFECTIVE_INSTRUCTION_SHA256,
    ISOLATED_AGENT_CREDENTIAL_PATHS,
    ISOLATED_AGENT_HOME_ENVIRONMENT_VARIABLES,
    LANGUAGE_QUOTA,
    Phase2bPilotError,
    load_phase2b_manifest,
    load_run_authorization,
    phase2b_manifest_from_dict,
    plan_phase2b_workspaces,
    prepare_phase2b_workspaces,
    validate_phase2b_environment,
    validate_phase2b_dry_run_record,
    validate_phase2b_execution_workspaces,
)
from adaptive_orchestrator.experiments.phase2b_runner import (
    Phase2bExecutionError,
    Phase2bPilotRunner,
)


def instruction_inventory(
    *,
    resolution: str = "semantically-equivalent",
    claude_hash: str = "c" * 64,
    codex_hash: str = "d" * 64,
) -> dict[str, object]:
    isolated = resolution in {
        "isolated-empty-agent-homes",
        AUTHENTICATED_ISOLATED_AGENT_HOME_RESOLUTION,
    }
    authenticated = resolution == AUTHENTICATED_ISOLATED_AGENT_HOME_RESOLUTION
    return {
        "schema_version": "phase2b-global-instruction-inventory-v1",
        "resolution": resolution,
        "verified_at": "2026-08-20T00:00:00Z",
        "claude_effective_instruction_sha256": claude_hash,
        "codex_effective_instruction_sha256": codex_hash,
        "codex_project_doc_fallback_filenames": [],
        "semantic_equivalence_review_completed": not isolated,
        "isolated_agent_home_contract": (
            {
                "fresh_per_attempt": True,
                "inherited_user_home": False,
                "initial_file_count": 1 if authenticated else 0,
                "environment_variables": list(
                    ISOLATED_AGENT_HOME_ENVIRONMENT_VARIABLES
                ),
                **(
                    {
                        "credential_binding": {
                            "strategy": "read-write-symlink",
                            "source_home_relative_paths_by_agent_base": (
                                ISOLATED_AGENT_CREDENTIAL_PATHS
                            ),
                            "cleanup_after_agent_invocation": True,
                            "credential_contents_recorded": False,
                        }
                    }
                    if authenticated
                    else {}
                ),
            }
            if isolated
            else None
        ),
    }


def git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ("git", "-C", str(repository), *arguments),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def build_phase2b_fixture(root: Path) -> dict[str, object]:
    source = root / "source"
    source.mkdir()
    (source / "fixture.txt").write_text("stable fixture\n")
    (source / "app.py").write_text("VALUE = 1\n")
    git(source, "init", "-q")
    git(source, "add", "fixture.txt", "app.py")
    git(
        source,
        "-c", "user.name=Test", "-c", "user.email=test@example.com",
        "commit", "-qm", "base",
    )
    commit = git(source, "rev-parse", "HEAD")
    tree = git(source, "rev-parse", "HEAD^{tree}")

    evaluator_root = root / "evaluators"
    evaluator_root.mkdir()
    evaluator = evaluator_root / "quality.py"
    evaluator.write_text("# protected objective evaluator\n")
    evaluator.chmod(0o444)
    artifact_hash = hash_evaluator_artifacts((str(evaluator),))
    evaluator_version = evaluator_content_version(
        ("python3", "quality.py"),
        (str(evaluator),),
    )

    inventory = root / "instruction-inventory.json"
    inventory.write_text(json.dumps(instruction_inventory(), indent=2) + "\n")
    inventory_hash = hashlib.sha256(inventory.read_bytes()).hexdigest()
    fixture_hash = hash_evaluator_artifacts((str(source / "fixture.txt"),))
    languages = [language for language, count in LANGUAGE_QUOTA.items() for _ in range(count)]
    categories = [category for category, count in CATEGORY_QUOTA.items() for _ in range(count)]
    tasks = []
    for index in range(60):
        criterion = f"criterion-{index + 1}"
        language = languages[index]
        tasks.append({
            "task_id": f"task-{index + 1:02d}",
            "task_set_version": "phase2b-test-set-v1",
            "source_provenance": {
                "source_kind": "synthetic-fixture",
                "source_reference": f"fixture-{index + 1}",
                "source_revision": commit,
                "selection_rationale": "Fixed result-blind quota fixture.",
                "origin_language": language,
                "native_task": True,
                "translation_relationship_id": None,
                "adaptation_history": [],
                "license_or_use_basis": "Apache-2.0 test fixture",
                "selected_by_role_id": "task-author-1",
                "selected_at": "2026-08-20T00:00:00Z",
            },
            "description": f"Synthetic task {index + 1}",
            "objective": "Pass the protected evaluator.",
            "constraints": ["Do not use the network."],
            "acceptance_criteria": [criterion],
            "instruction_language": language,
            "repository_code_language": "python",
            "repository_doc_language": language,
            "task_category": categories[index],
            "required_capabilities": ["code_generation"],
            "risk": "low",
            "mutation_scope": "isolated-checkout-only",
            "read_only": False,
            "repository_id": "repo-1",
            "fixture_paths": ["fixture.txt"],
            "fixture_hash": fixture_hash,
            "estimated_resource_bucket": "small",
            "modified_file_allowlist": ["app.py"],
            "task_author_role_ids": ["task-author-1"],
            "confirmatory_reuse_allowed": False,
            "evaluator": {
                "evaluator_id": f"quality-{index + 1:02d}",
                "version": evaluator_version,
                "role": "objective_quality",
                "evaluation_mode": "deterministic-acceptance-test",
                "aggregation": "binary-single-v1",
                "command": ["python3", "quality.py"],
                "artifact_paths": ["quality.py"],
                "artifact_hash": artifact_hash,
                "timeout_seconds": 30,
                "agent_blind": True,
                "protected_read_only": True,
                "evaluator_author_role_id": "evaluator-author-1",
                "validity_reviewer_role_id": "validity-reviewer-1",
                "assertion_inventory_complete": True,
                "assertion_contracts": [{
                    "assertion_id": f"assertion-{index + 1:02d}",
                    "evaluator_requirement": "Check the declared criterion.",
                    "task_contract_field": "acceptance_criteria",
                    "task_contract_text": criterion,
                }],
                "negative_control": {
                    "control_id": f"negative-{index + 1:02d}",
                    "description": "Base fixture lacks the requested behavior.",
                    "expected_quality": 0,
                    "observed_quality": 0,
                    "artifact_hash": "a" * 64,
                    "completed_at": "2026-08-20T00:00:00Z",
                },
                "positive_control": {
                    "control_id": f"positive-{index + 1:02d}",
                    "description": "Known solution satisfies the requested behavior.",
                    "expected_quality": 1,
                    "observed_quality": 1,
                    "artifact_hash": "b" * 64,
                    "completed_at": "2026-08-20T00:00:00Z",
                },
                "validity_review_completed": True,
                "validity_reviewed_at": "2026-08-20T00:00:00Z",
            },
        })

    raw = {
        "schema_version": "paired-pilot-manifest-v1",
        "protocol_version": "phase2b-pilot-prereg-v1.1",
        "study_phase": "phase2b-variance-pilot",
        "pilot_purpose": "pipeline-discordance-variance-missingness-and-confirmatory-sizing",
        "experiment_id": "phase2b-test-v1",
        "task_set_version": "phase2b-test-set-v1",
        "construction_roles": {
            "task_author_role_ids": ["task-author-1"],
            "evaluator_author_role_ids": ["evaluator-author-1"],
            "validity_reviewer_role_ids": ["validity-reviewer-1"],
            "run_operator_role_ids": ["run-operator-1"],
            "analyst_role_ids": ["analyst-1"],
            "construction_role_sets_disjoint_attested": True,
            "task_selection_frozen_before_agent_results": True,
            "evaluator_authors_blind_to_agent_identity": True,
            "validity_reviewers_blind_to_agent_results": True,
            "conflict_policy": "Stop and amend before combining construction roles.",
        },
        "repositories": [{
            "repository_id": "repo-1",
            "source": "local-test-fixture",
            "base_revision": commit,
            "base_tree_hash": tree,
            "license_or_use_basis": "Apache-2.0 test fixture",
        }],
        "environment": {
            "environment_epoch": "phase2b-test-env-v1",
            "global_instruction_context": {
                "resolution": "semantically-equivalent",
                "inventory_artifact_hash": inventory_hash,
                "claude_effective_instruction_hash": "c" * 64,
                "codex_effective_instruction_hash": "d" * 64,
                "codex_project_doc_fallback_filenames": [],
                "verified_at": "2026-08-20T00:00:00Z",
            },
            "workspace_isolation": "independent-exact-base-checkouts",
            "protected_control_state": "outside-agent-workspace-read-write-by-runner-only",
            "protected_evaluators": "outside-agent-workspace-read-only",
            "protected_evaluator_root_id": "test-evaluator-root-v1",
            "network_access": "forbidden",
            "secret_access": "forbidden",
            "push_access": "forbidden",
            "production_mutation": "forbidden",
        },
        "agents": [{
            "agent_id": "claude-code:opus",
            "base_id": "claude-code",
            "model": "opus",
            "reasoning_tier": None,
            "cli_version": "2.1.236",
            "permission_mode": "acceptEdits",
            "time_limit_seconds": 300,
        }, {
            "agent_id": "codex:gpt-5.6:high",
            "base_id": "codex",
            "model": "gpt-5.6",
            "reasoning_tier": "high",
            "cli_version": "0.144.5",
            "permission_mode": "workspace-write",
            "time_limit_seconds": 300,
        }],
        "assignment": {
            "random_seed": 23,
            "order_assignment_rule": "seeded-balanced-sha256-v1",
            "stable_identity_rule": "uuidv5-experiment-task-agent-v1",
            "balanced_first_position": True,
            "agent_result_isolation": True,
        },
        "tasks": tasks,
        "analysis_plan": {
            "primary_estimand": "paired-objective-quality-risk-difference",
            "primary_population": "experimental-quota-by-preregistered-stratum",
            "reporting_strata": ["instruction_language", "task_category"],
            "minimum_reporting_cell_size": 4,
            "pilot_inference_scope": "variance-discordance-missingness-and-confirmatory-sizing-not-agent-ranking",
            "binary_interval_method": "exact-mcnemar-binomial-and-paired-risk-difference-v1",
            "continuous_interval_method": "seeded-paired-bootstrap-v1",
            "confidence_level": 0.95,
            "decision_margins": [{
                "metric": "evaluator-coverage",
                "scope": "overall",
                "value": 0.8,
                "rationale": "Coverage gate for confirmatory sizing.",
                "frozen_before_pilot": True,
            }],
            "secondary_metrics": [
                "reliability",
                "constraint-and-safety-violations",
                "agent-evaluator-and-experiment-time",
                "comparable-resource-units-with-raw-token-caveat",
                "cost-when-observed-for-both-agents",
                "modified-file-scope",
                "evaluator-coverage-and-missingness",
            ],
            "missingness": {
                "quality": "missing-never-impute-zero-or-pass",
                "cost": "unknown-never-impute-zero",
                "terminal": "incomplete-until-reconciled",
                "subjective_disagreement": "not-applicable-primary-objective-evaluators-only",
            },
            "target_workload_aggregate": "not-estimable-without-independent-representative-intake-weights",
        },
        "maximum_resource_budget": {
            "maximum_executions": 120,
            "maximum_agent_execution_count": 120,
            "maximum_evaluator_execution_count": 120,
            "maximum_active_wall_time_seconds": 36_000,
        },
        "rules": {
            "stopping": ["Stop on source, evaluator, secret, network, push, or production drift."],
            "pause": ["Pause after infrastructure or evaluator failure."],
            "exclusion": ["Exclude only a broken fixture before either agent runs."],
            "resume": {
                "retain_finalized_prefix": True,
                "run_only_untouched_suffix": True,
                "preserve_missing_failure_rows": True,
                "reject_duplicate_attempt_ids": True,
            },
        },
        "confirmatory_holdout": {
            "pilot_tasks_reusable": False,
            "new_tasks_required": True,
            "sample_size_method": "conservative-discordance-bound",
            "sample_size_frozen_before_confirmatory_execution": True,
        },
        "authorization": {
            "manifest_must_be_committed_before_results": True,
            "agent_free_validation_required": True,
            "separate_run_authorization_required": True,
            "agent_execution_authorized_by_this_manifest": False,
        },
    }
    manifest_path = root / "phase2b-manifest.json"
    manifest_path.write_text(json.dumps(raw, indent=2) + "\n")
    return {
        "raw": raw,
        "manifest_path": manifest_path,
        "source": source,
        "evaluator_root": evaluator_root,
        "inventory": inventory,
    }


class RecordingProcessRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], Path, float | None]] = []

    def run(self, command, cwd, timeout_seconds):
        command = tuple(command)
        self.calls.append((command, cwd, timeout_seconds))
        return ProcessResult(
            command,
            ExecutionStatus.COMPLETED,
            '{"type":"result","subtype":"success","is_error":false,"result":"ok"}\n',
            "",
            0,
            1.0,
        )


class EnvironmentRecordingProcessRunner(RecordingProcessRunner):
    def __init__(self, *, write_agent_state: bool = False) -> None:
        super().__init__()
        self.write_agent_state = write_agent_state
        self.environments: list[
            tuple[dict[str, str], tuple[str, ...], tuple[tuple[str, bool, bool], ...]]
        ] = []

    def run_with_environment(
        self,
        command,
        cwd,
        timeout_seconds,
        *,
        environment,
        unset_environment=(),
    ):
        home = Path(environment["HOME"])
        initial_entries = tuple(
            (str(path.relative_to(home)), path.is_symlink(), path.is_dir())
            for path in home.rglob("*")
        )
        self.environments.append(
            (dict(environment), tuple(unset_environment), initial_entries)
        )
        if self.write_agent_state:
            (home / "session-state.json").write_text("ephemeral agent state\n")
        return self.run(command, cwd, timeout_seconds)


class Phase2bManifestTests(unittest.TestCase):
    def test_semantic_validator_enforces_exact_quota_roles_and_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = build_phase2b_fixture(Path(directory))
            manifest = phase2b_manifest_from_dict(fixture["raw"])

        self.assertEqual(len(manifest.tasks), 60)
        self.assertEqual(len(manifest.agents), 2)
        self.assertEqual(set(manifest.task_repository_ids.values()), {"repo-1"})
        self.assertEqual(
            {key: sum(task.instruction_language == key for task in manifest.tasks) for key in LANGUAGE_QUOTA},
            LANGUAGE_QUOTA,
        )
        self.assertEqual(
            {key: sum(task.task_category == key for task in manifest.tasks) for key in CATEGORY_QUOTA},
            CATEGORY_QUOTA,
        )

    def test_rejects_quota_role_assertion_and_unknown_field_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw = build_phase2b_fixture(Path(directory))["raw"]

            quota = copy.deepcopy(raw)
            quota["tasks"][0]["instruction_language"] = "en"
            quota["tasks"][0]["source_provenance"]["origin_language"] = "en"
            with self.assertRaisesRegex(Phase2bPilotError, "fixed quotas"):
                phase2b_manifest_from_dict(quota)

            roles = copy.deepcopy(raw)
            roles["construction_roles"]["evaluator_author_role_ids"] = ["task-author-1"]
            roles["tasks"][0]["evaluator"]["evaluator_author_role_id"] = "task-author-1"
            with self.assertRaisesRegex(Phase2bPilotError, "role sets must be disjoint"):
                phase2b_manifest_from_dict(roles)

            assertion = copy.deepcopy(raw)
            assertion["tasks"][0]["evaluator"]["assertion_contracts"][0]["task_contract_text"] = "hidden requirement"
            with self.assertRaisesRegex(Phase2bPilotError, "absent from task"):
                phase2b_manifest_from_dict(assertion)

            unknown = copy.deepcopy(raw)
            unknown["tasks"][0]["silent_extra"] = True
            with self.assertRaisesRegex(Phase2bPilotError, "extra=\['silent_extra'\]"):
                phase2b_manifest_from_dict(unknown)

            timeout = copy.deepcopy(raw)
            timeout["tasks"][0]["evaluator"]["timeout_seconds"] = 31
            with self.assertRaisesRegex(Phase2bPilotError, "Small-bucket evaluator timeout"):
                phase2b_manifest_from_dict(timeout)

            medium = copy.deepcopy(raw)
            medium["tasks"][0]["estimated_resource_bucket"] = "medium"
            with self.assertRaisesRegex(Phase2bPilotError, "Medium-bucket evaluator timeout"):
                phase2b_manifest_from_dict(medium)

            controls = copy.deepcopy(raw)
            controls["tasks"][0]["evaluator"]["positive_control"]["control_id"] = (
                controls["tasks"][0]["evaluator"]["negative_control"]["control_id"]
            )
            with self.assertRaisesRegex(Phase2bPilotError, "distinct IDs"):
                phase2b_manifest_from_dict(controls)

            read_only = copy.deepcopy(raw)
            read_only["tasks"][0]["read_only"] = True
            with self.assertRaisesRegex(Phase2bPilotError, "Read-only task"):
                phase2b_manifest_from_dict(read_only)

            unsafe_path = copy.deepcopy(raw)
            unsafe_path["tasks"][0]["modified_file_allowlist"] = ["./app.py"]
            with self.assertRaisesRegex(Phase2bPilotError, "unsafe relative path"):
                phase2b_manifest_from_dict(unsafe_path)

            naive_timestamp = copy.deepcopy(raw)
            naive_timestamp["tasks"][0]["source_provenance"]["selected_at"] = (
                "2026-08-20T00:00:00"
            )
            with self.assertRaisesRegex(Phase2bPilotError, "explicit UTC offset"):
                phase2b_manifest_from_dict(naive_timestamp)

            unsafe_permission = copy.deepcopy(raw)
            unsafe_permission["agents"][1]["permission_mode"] = "danger-full-access"
            with self.assertRaisesRegex(Phase2bPilotError, "workspace-write"):
                phase2b_manifest_from_dict(unsafe_permission)

    def test_plan_is_pure_unique_and_balanced_for_120_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = build_phase2b_fixture(root)
            manifest = phase2b_manifest_from_dict(fixture["raw"])
            workspace_root = root / "not-created"
            before = sorted(str(path) for path in root.rglob("*"))

            first = plan_phase2b_workspaces(manifest, workspace_root)
            second = plan_phase2b_workspaces(manifest, workspace_root)

            self.assertEqual(first, second)
            self.assertEqual(len(first["workspaces"]), 120)
            self.assertEqual(len({item["attempt_id"] for item in first["workspaces"]}), 120)
            self.assertEqual(set(first["first_position_counts"].values()), {30})
            self.assertFalse(workspace_root.exists())
            self.assertEqual(sorted(str(path) for path in root.rglob("*")), before)

    def test_json_and_authorization_boundaries_are_strict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            duplicate = root / "duplicate.json"
            duplicate.write_text('{"schema_version":"one","schema_version":"two"}\n')
            with self.assertRaisesRegex(Phase2bPilotError, "duplicate key"):
                load_phase2b_manifest(duplicate)

            fixture_root = root / "fixture"
            fixture_root.mkdir()
            fixture = build_phase2b_fixture(fixture_root)
            manifest = phase2b_manifest_from_dict(fixture["raw"])
            authorization = {
                "schema_version": "phase2b-pilot-run-authorization-v1",
                "experiment_id": manifest.experiment_id,
                "manifest_sha256": hashlib.sha256(
                    fixture["manifest_path"].read_bytes()
                ).hexdigest(),
                "manifest_commit": "a" * 40,
                "agent_free_dry_run_sha256": "b" * 64,
                "maximum_executions": 120,
                "agent_execution_authorized": True,
                "approved_by_role_id": "analyst-1",
                "approval_basis": "Wrong construction role.",
                "approved_at": "2026-08-20T00:00:00Z",
            }
            authorization_path = root / "authorization.json"
            authorization_path.write_text(json.dumps(authorization) + "\n")
            with self.assertRaisesRegex(Phase2bPilotError, "declared run operator"):
                load_run_authorization(
                    authorization_path,
                    manifest_path=fixture["manifest_path"],
                    manifest=manifest,
                )


class Phase2bDryRunTests(unittest.TestCase):
    def test_attests_authenticated_instruction_isolation_and_cleans_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = build_phase2b_fixture(root)
            raw = copy.deepcopy(fixture["raw"])
            context = raw["environment"]["global_instruction_context"]
            context["resolution"] = AUTHENTICATED_ISOLATED_AGENT_HOME_RESOLUTION
            context["claude_effective_instruction_hash"] = EMPTY_EFFECTIVE_INSTRUCTION_SHA256
            context["codex_effective_instruction_hash"] = EMPTY_EFFECTIVE_INSTRUCTION_SHA256
            inventory = instruction_inventory(
                resolution=AUTHENTICATED_ISOLATED_AGENT_HOME_RESOLUTION,
                claude_hash=EMPTY_EFFECTIVE_INSTRUCTION_SHA256,
                codex_hash=EMPTY_EFFECTIVE_INSTRUCTION_SHA256,
            )
            fixture["inventory"].write_text(json.dumps(inventory, indent=2) + "\n")
            context["inventory_artifact_hash"] = hashlib.sha256(
                fixture["inventory"].read_bytes()
            ).hexdigest()
            fixture["manifest_path"].write_text(json.dumps(raw, indent=2) + "\n")
            manifest = phase2b_manifest_from_dict(raw)

            credential_home = root / "credential-home"
            for relative in ISOLATED_AGENT_CREDENTIAL_PATHS.values():
                credential = credential_home / relative
                credential.parent.mkdir(parents=True, exist_ok=True)
                credential.write_text("credential fixture\n")
                credential.chmod(0o600)

            validate_phase2b_environment(
                manifest,
                fixture["manifest_path"],
                {"repo-1": fixture["source"]},
                fixture["evaluator_root"],
                fixture["inventory"],
            )
            workspace_root = root / "workspaces"
            delegate = EnvironmentRecordingProcessRunner(write_agent_state=True)
            runner = Phase2bPilotRunner(
                manifest,
                fixture["manifest_path"],
                {"repo-1": fixture["source"]},
                fixture["evaluator_root"],
                fixture["inventory"],
                workspace_root,
                root / "control",
                root / "dry-run.json",
                root / "authorization.json",
                process_runner_factory=lambda: delegate,
                version_resolver=lambda spec: spec.cli_version,
                credential_home=credential_home,
            )

            claude_spec, codex_spec = manifest.agents
            claude_workspace = workspace_root / "task-01" / claude_spec.agent_id
            codex_workspace = workspace_root / "task-01" / codex_spec.agent_id
            claude_workspace.mkdir(parents=True)
            codex_workspace.mkdir(parents=True)
            claude_bound = runner._process_runner_for_attempt(claude_spec, claude_workspace)
            codex_bound = runner._process_runner_for_attempt(codex_spec, codex_workspace)
            claude_result = claude_bound.run(
                ("claude", "--print", "prompt"), claude_workspace, 1
            )
            codex_result = codex_bound.run(
                ("codex", "exec", "--json", "prompt"), codex_workspace, 1
            )

            self.assertEqual(claude_result.status, ExecutionStatus.COMPLETED)
            self.assertEqual(codex_result.status, ExecutionStatus.COMPLETED)
            self.assertEqual(len(delegate.environments), 2)
            for observed, removed, initial_entries in delegate.environments:
                self.assertEqual(set(observed), set(ISOLATED_AGENT_HOME_ENVIRONMENT_VARIABLES))
                self.assertEqual(set(removed), set(ISOLATED_AGENT_HOME_ENVIRONMENT_VARIABLES))
                credential_links = [
                    path for path in initial_entries if path[1]
                ]
                self.assertEqual(len(credential_links), 1)
            self.assertEqual(delegate.calls[0][0][:2], ("claude", "--safe-mode"))
            self.assertEqual(
                delegate.calls[1][0][:6],
                (
                    "codex", "exec", "-c", "project_doc_max_bytes=0",
                    "-c", "project_doc_fallback_filenames=[]",
                ),
            )
            for observed, _, _ in delegate.environments:
                self.assertEqual(tuple(Path(observed["HOME"]).iterdir()), ())
            for relative in ISOLATED_AGENT_CREDENTIAL_PATHS.values():
                self.assertEqual(
                    (credential_home / relative).read_text(),
                    "credential fixture\n",
                )

            consumed_home = Path(delegate.environments[0][0]["HOME"])
            marker = consumed_home / "owned-marker"
            marker.write_text("preserve pre-existing control evidence\n")
            collision = runner._process_runner_for_attempt(
                claude_spec, claude_workspace
            ).run(("claude", "--print", "prompt"), claude_workspace, 1)
            self.assertEqual(collision.status, ExecutionStatus.SPAWN_ERROR)
            self.assertIn("authenticated isolated agent home", collision.stderr)
            self.assertEqual(marker.read_text(), "preserve pre-existing control evidence\n")

            broad_workspace = workspace_root / "task-02" / claude_spec.agent_id
            broad_workspace.mkdir(parents=True)
            claude_credential = credential_home / ISOLATED_AGENT_CREDENTIAL_PATHS["claude-code"]
            if os.name == "posix":
                claude_credential.chmod(0o644)
                broad = runner._process_runner_for_attempt(
                    claude_spec, broad_workspace
                ).run(("claude", "--print", "prompt"), broad_workspace, 1)
                self.assertEqual(broad.status, ExecutionStatus.SPAWN_ERROR)
                self.assertIn("permissions are too broad", broad.stderr)
                claude_credential.chmod(0o600)

            drift_workspace = workspace_root / "task-03" / claude_spec.agent_id
            drift_workspace.mkdir(parents=True)
            drift = runner._process_runner_for_attempt(
                claude_spec, drift_workspace
            ).run(("unexpected-cli", "prompt"), drift_workspace, 1)
            self.assertEqual(drift.status, ExecutionStatus.SPAWN_ERROR)
            self.assertIn("command identity drifted", drift.stderr)
            drift_home = root / "control" / "isolated-agent-homes" / "task-03" / claude_spec.agent_id
            self.assertEqual(tuple(drift_home.iterdir()), ())

    def test_attests_and_enforces_fresh_empty_agent_homes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = build_phase2b_fixture(root)
            raw = copy.deepcopy(fixture["raw"])
            context = raw["environment"]["global_instruction_context"]
            context["resolution"] = "isolated-empty-agent-homes"
            context["claude_effective_instruction_hash"] = EMPTY_EFFECTIVE_INSTRUCTION_SHA256
            context["codex_effective_instruction_hash"] = EMPTY_EFFECTIVE_INSTRUCTION_SHA256
            isolated_inventory = instruction_inventory(
                resolution="isolated-empty-agent-homes",
                claude_hash=EMPTY_EFFECTIVE_INSTRUCTION_SHA256,
                codex_hash=EMPTY_EFFECTIVE_INSTRUCTION_SHA256,
            )
            fixture["inventory"].write_text(
                json.dumps(isolated_inventory, indent=2) + "\n"
            )
            context["inventory_artifact_hash"] = hashlib.sha256(
                fixture["inventory"].read_bytes()
            ).hexdigest()
            fixture["manifest_path"].write_text(json.dumps(raw, indent=2) + "\n")
            manifest = phase2b_manifest_from_dict(raw)

            environment = validate_phase2b_environment(
                manifest,
                fixture["manifest_path"],
                {"repo-1": fixture["source"]},
                fixture["evaluator_root"],
                fixture["inventory"],
            )
            self.assertEqual(
                environment["global_instruction_resolution"],
                "isolated-empty-agent-homes",
            )

            workspace_root = root / "workspaces"
            workspace = workspace_root / manifest.experiment_id / "task-01" / manifest.agents[0].agent_id
            workspace.mkdir(parents=True)
            delegate = EnvironmentRecordingProcessRunner()
            runner = Phase2bPilotRunner(
                manifest,
                fixture["manifest_path"],
                {"repo-1": fixture["source"]},
                fixture["evaluator_root"],
                fixture["inventory"],
                workspace_root,
                root / "control",
                root / "dry-run.json",
                root / "authorization.json",
                process_runner_factory=lambda: delegate,
                version_resolver=lambda spec: spec.cli_version,
            )
            bound = runner._process_runner_for_attempt(manifest.agents[0], workspace)
            agent_result = bound.run(("agent",), workspace, 1)
            evaluator_result = bound.run(("evaluator",), workspace, 1)

            self.assertEqual(agent_result.status, ExecutionStatus.COMPLETED)
            self.assertEqual(evaluator_result.status, ExecutionStatus.COMPLETED)
            self.assertEqual(len(delegate.environments), 1)
            observed, removed, initial_entries = delegate.environments[0]
            self.assertEqual(initial_entries, ())
            self.assertEqual(set(observed), set(ISOLATED_AGENT_HOME_ENVIRONMENT_VARIABLES))
            self.assertEqual(set(removed), set(ISOLATED_AGENT_HOME_ENVIRONMENT_VARIABLES))
            self.assertEqual(Path(observed["HOME"]).name, manifest.agents[0].agent_id)

            second = runner._process_runner_for_attempt(manifest.agents[0], workspace)
            collision = second.run(("agent",), workspace, 1)
            self.assertEqual(collision.status, ExecutionStatus.SPAWN_ERROR)
            self.assertIn("fresh isolated agent home", collision.stderr)

            if os.name == "posix":
                symlink_target = root / "symlink-control-target"
                symlink_target.mkdir()
                symlink_control = root / "symlink-control"
                symlink_control.symlink_to(symlink_target, target_is_directory=True)
                symlink_runner = Phase2bPilotRunner(
                    manifest,
                    fixture["manifest_path"],
                    {"repo-1": fixture["source"]},
                    fixture["evaluator_root"],
                    fixture["inventory"],
                    workspace_root,
                    symlink_control,
                    root / "dry-run.json",
                    root / "authorization.json",
                    process_runner_factory=lambda: delegate,
                    version_resolver=lambda spec: spec.cli_version,
                )
                with self.assertRaisesRegex(Phase2bExecutionError, "must not be a symlink"):
                    symlink_runner._process_runner_for_attempt(
                        manifest.agents[0], workspace
                    )

            unsupported_workspace = (
                workspace_root
                / manifest.experiment_id
                / "task-02"
                / manifest.agents[0].agent_id
            )
            unsupported_workspace.mkdir(parents=True)
            unsupported_runner = Phase2bPilotRunner(
                manifest,
                fixture["manifest_path"],
                {"repo-1": fixture["source"]},
                fixture["evaluator_root"],
                fixture["inventory"],
                workspace_root,
                root / "unsupported-control",
                root / "dry-run.json",
                root / "authorization.json",
                process_runner_factory=RecordingProcessRunner,
                version_resolver=lambda spec: spec.cli_version,
            )
            unsupported = unsupported_runner._process_runner_for_attempt(
                manifest.agents[0], unsupported_workspace
            ).run(("agent",), unsupported_workspace, 1)
            self.assertEqual(unsupported.status, ExecutionStatus.SPAWN_ERROR)
            self.assertIn("cannot enforce isolated agent homes", unsupported.stderr)

            isolated_inventory["isolated_agent_home_contract"]["initial_file_count"] = 1
            fixture["inventory"].write_text(
                json.dumps(isolated_inventory, indent=2) + "\n"
            )
            context["inventory_artifact_hash"] = hashlib.sha256(
                fixture["inventory"].read_bytes()
            ).hexdigest()
            fixture["manifest_path"].write_text(json.dumps(raw, indent=2) + "\n")
            drifted = phase2b_manifest_from_dict(raw)
            with self.assertRaisesRegex(Phase2bPilotError, "initial_file_count"):
                validate_phase2b_environment(
                    drifted,
                    fixture["manifest_path"],
                    {"repo-1": fixture["source"]},
                    fixture["evaluator_root"],
                    fixture["inventory"],
                )

    def test_materializes_and_cold_revalidates_120_agent_free_checkouts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = build_phase2b_fixture(root)
            manifest = phase2b_manifest_from_dict(fixture["raw"])
            workspace_root = root / "workspaces"

            report = prepare_phase2b_workspaces(
                manifest,
                fixture["manifest_path"],
                {"repo-1": fixture["source"]},
                fixture["evaluator_root"],
                fixture["inventory"],
                workspace_root,
            )
            record_path = root / "dry-run.json"
            record_path.write_text(json.dumps(report, indent=2) + "\n")
            validated = validate_phase2b_dry_run_record(
                record_path,
                manifest=manifest,
                manifest_path=fixture["manifest_path"],
                workspace_root=workspace_root,
            )
            cold = validate_phase2b_execution_workspaces(
                manifest,
                fixture["manifest_path"],
                {"repo-1": fixture["source"]},
                fixture["evaluator_root"],
                fixture["inventory"],
                workspace_root,
            )

            self.assertFalse(report["agent_execution_started"])
            self.assertEqual(report["workspace_count"], 120)
            self.assertEqual(validated["workspace_count"], 120)
            self.assertEqual(cold["remaining_attempt_count"], 120)
            self.assertTrue(all(item["clean"] for item in cold["workspaces"]))

            tampered = copy.deepcopy(report)
            tampered["workspaces"][0]["fixture_hash"] = "0" * 64
            record_path.write_text(json.dumps(tampered, indent=2) + "\n")
            with self.assertRaisesRegex(Phase2bPilotError, "invalid fixture_hash"):
                validate_phase2b_dry_run_record(
                    record_path,
                    manifest=manifest,
                    manifest_path=fixture["manifest_path"],
                    workspace_root=workspace_root,
                )


class Phase2bRunnerTests(unittest.TestCase):
    def test_manifest_never_authorizes_execution_by_itself(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = build_phase2b_fixture(root)
            manifest = phase2b_manifest_from_dict(fixture["raw"])
            process = RecordingProcessRunner()
            runner = Phase2bPilotRunner(
                manifest,
                fixture["manifest_path"],
                {"repo-1": fixture["source"]},
                fixture["evaluator_root"],
                fixture["inventory"],
                root / "missing-workspaces",
                root / "control",
                root / "missing-dry-run.json",
                root / "missing-authorization.json",
                process_runner_factory=lambda: process,
                version_resolver=lambda spec: spec.cli_version,
            )

            with self.assertRaisesRegex(Phase2bExecutionError, "confirm-agent-execution"):
                runner.run()

            self.assertEqual(process.calls, [])
            self.assertFalse((root / "control").exists())

    def test_separately_authorized_run_consumes_exactly_120_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = build_phase2b_fixture(root)
            manifest = phase2b_manifest_from_dict(fixture["raw"])
            workspace_root = root / "workspaces"
            dry_run = prepare_phase2b_workspaces(
                manifest,
                fixture["manifest_path"],
                {"repo-1": fixture["source"]},
                fixture["evaluator_root"],
                fixture["inventory"],
                workspace_root,
            )
            dry_run_path = root / "dry-run.json"
            dry_run_path.write_text(json.dumps(dry_run, indent=2) + "\n")

            git(root, "init", "-q")
            git(root, "add", fixture["manifest_path"].name)
            git(
                root,
                "-c", "user.name=Test", "-c", "user.email=test@example.com",
                "commit", "-qm", "freeze manifest",
            )
            manifest_commit = git(root, "rev-parse", "HEAD")
            authorization = {
                "schema_version": "phase2b-pilot-run-authorization-v1",
                "experiment_id": manifest.experiment_id,
                "manifest_sha256": hashlib.sha256(fixture["manifest_path"].read_bytes()).hexdigest(),
                "manifest_commit": manifest_commit,
                "agent_free_dry_run_sha256": hashlib.sha256(dry_run_path.read_bytes()).hexdigest(),
                "maximum_executions": 120,
                "agent_execution_authorized": True,
                "approved_by_role_id": "run-operator-1",
                "approval_basis": "Explicit synthetic test authorization.",
                "approved_at": "2026-08-20T00:00:00Z",
            }
            authorization_path = root / "authorization.json"
            authorization_path.write_text(json.dumps(authorization, indent=2) + "\n")
            process = RecordingProcessRunner()

            report = Phase2bPilotRunner(
                manifest,
                fixture["manifest_path"],
                {"repo-1": fixture["source"]},
                fixture["evaluator_root"],
                fixture["inventory"],
                workspace_root,
                root / "control",
                dry_run_path,
                authorization_path,
                process_runner_factory=lambda: process,
                version_resolver=lambda spec: f"tool {spec.cli_version}",
            ).run(confirm_agent_execution=True)

            self.assertEqual(report["schema_version"], "phase2b-pilot-run-v1")
            self.assertEqual(report["attempts_started_this_invocation"], 120)
            self.assertEqual(report["materialized_attempts"], 120)
            self.assertEqual(report["completed_attempts"], 120)
            self.assertEqual(len(process.calls), 240)
            self.assertIn("Acceptance criterion: criterion-", process.calls[0][0][-1])
            self.assertFalse(report["analysis"]["promotion_allowed"])
            self.assertIn(
                "Phase 2b estimates",
                report["analysis"]["overall_quota_diagnostic_not_workload_value"][
                    "ranking_withheld_reason"
                ],
            )
            self.assertEqual(
                report["analysis"]["secondary_metrics"]["reliability"]["expected_attempt_count"],
                120,
            )


if __name__ == "__main__":
    unittest.main()
