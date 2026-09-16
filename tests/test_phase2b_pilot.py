from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from time import monotonic
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.execution.verification import (
    evaluator_content_version,
    hash_evaluator_artifacts,
)
from adaptive_orchestrator.core.domain import Capability, ExecutionStatus, Task
from adaptive_orchestrator.execution.process_runner import ProcessResult, SubprocessRunner
from adaptive_orchestrator.execution.resource_supervisor import (
    PHASE2B_RESOURCE_INVOCATION_POLICIES,
    RESOURCE_SUPERVISOR_SCHEMA,
    ResourceCapabilityAttestation,
    SupervisedProcessRunner,
    resource_policy_descriptor,
)
from adaptive_orchestrator.experiments.phase2b_pilot import (
    AUTHENTICATED_ISOLATED_AGENT_HOME_RESOLUTION,
    BUBBLEWRAP_EXECUTABLE,
    CATEGORY_QUOTA,
    EMPTY_EFFECTIVE_INSTRUCTION_SHA256,
    ISOLATED_AGENT_CREDENTIAL_PATHS,
    ISOLATED_AGENT_CREDENTIAL_BINDING_STRATEGY,
    ISOLATED_AGENT_HOME_ENVIRONMENT_VARIABLES,
    LANGUAGE_QUOTA,
    PHASE2B_AUTHORIZATION_SCOPE,
    PHASE2B_PROVIDER_NOTICE_SCHEMA,
    PHASE2B_AGENT_EXECUTION_ISOLATION_POLICY,
    PHASE2B_AGENT_EXECUTION_ISOLATION_POLICY_SHA256,
    PHASE2B_AGENT_EXECUTION_ISOLATION_SCHEMA,
    PHASE2B_AGENT_EXECUTION_ISOLATION_STRATEGY,
    PHASE2B_TASK_RIGHTS_SCHEMA,
    Phase2bPilotError,
    _render_provider_transmission_notice,
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
    _AgentRuntime,
    _BubblewrapIsolatedAgentProcessRunner,
    _CLAUDE_BWRAP_WRAPPER,
    _RuntimeClosure,
    _RuntimeMount,
    attest_phase2b_runtime_closure,
    _codex_isolation_config_arguments,
    _content_tree_sha256,
    _evaluator_native_permission_profile,
    _optional_toolchain_mounts,
    _resolve_agent_runtime,
    _resolve_evaluator_native_helper,
    _resolve_runtime_closure,
    _runtime_metadata_sha256,
)
from adaptive_orchestrator.experiments.paired_experiment import assign_pairs
from adaptive_orchestrator.experiments.paired_runner import (
    PairedSmokeRunner,
    _agent_from_spec,
)
from adaptive_orchestrator.infrastructure.events import (
    JsonlEventStore,
    LifecycleEventType,
)
from adaptive_orchestrator.routing.state import LifecycleRecorder


def exact_agent_command(spec, workspace: Path, prompt: str = "prompt") -> tuple[str, ...]:
    return tuple(_agent_from_spec(spec).build_command(prompt, workspace))


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
                            "strategy": ISOLATED_AGENT_CREDENTIAL_BINDING_STRATEGY,
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
    license_bytes = (
        b"Synthetic MIT test license. Permission is granted for test use.\n"
    )
    (source / "LICENSE").write_bytes(license_bytes)
    git(source, "init", "-q")
    git(source, "add", "fixture.txt", "app.py", "LICENSE")
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
    license_artifact = {
        "path": "LICENSE",
        "artifact_kind": "license",
        "sha256": hashlib.sha256(license_bytes).hexdigest(),
    }
    provider_notice_text = _render_provider_transmission_notice(
        license_spdx="MIT",
        artifacts=((license_artifact, license_bytes),),
    )
    languages = [language for language, count in LANGUAGE_QUOTA.items() for _ in range(count)]
    categories = [category for category, count in CATEGORY_QUOTA.items() for _ in range(count)]
    tasks = []
    for index in range(60):
        criterion = f"criterion-{index + 1}"
        language = languages[index]
        description = f"Synthetic task {index + 1}"
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
                "license_or_use_basis": "MIT test fixture",
                "task_statement_rights": {
                    "schema_version": PHASE2B_TASK_RIGHTS_SCHEMA,
                    "task_statement_sha256": hashlib.sha256(
                        description.encode()
                    ).hexdigest(),
                    "protected_rights_inventory_sha256": "e" * 64,
                    "rights_entry_sha256": hashlib.sha256(
                        f"synthetic-rights-entry-{index + 1}".encode()
                    ).hexdigest(),
                    "license_spdx": "MIT",
                    "rights_basis": "repository-license-via-github-tos-d6",
                    "private_provider_transmission_verified": True,
                    "completed_before_manifest_freeze": True,
                },
                "selected_by_role_id": "task-author-1",
                "selected_at": "2026-08-20T00:00:00Z",
            },
            "description": description,
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

    kernel_security_record = {
        "schema": "phase2b-kernel-security-capability-v2",
        "kernel": {
            "system": "Linux",
            "release": "test-kernel",
            "machine": "test-machine",
        },
        "landlock": {"status": "observed", "abi": 6, "syscall_number": 444},
        "bubblewrap_user_namespace_probe": {"status": "passed", "return_code": 0},
        "sysctls": {
            "unprivileged_userns_clone": {"status": "observed", "value": "1"},
            "max_user_namespaces": {"status": "observed", "value": "1"},
            "apparmor_restrict_unprivileged_userns": {"status": "observed", "value": "0"},
        },
        "linux_security_modules": {
            "apparmor_enabled": {"status": "observed", "value": "Y"},
            "active": {"status": "observed", "value": "landlock,apparmor"},
        },
        "seccomp": {
            "actions_available": {"status": "observed", "value": "kill_process errno allow"},
            "orchestrator_process_status": {
                "status": "observed",
                "fields": {"NoNewPrivs": "0", "Seccomp": "2", "Seccomp_filters": "1"},
            },
        },
        "runtime_primitives": {
            "memfd_create": True,
            "pidfd_open": True,
            "pidfd_send_signal": True,
            "libseccomp": {"status": "observed", "soname": "libseccomp.so.2"},
        },
    }
    resource_descriptor = resource_policy_descriptor(
        PHASE2B_RESOURCE_INVOCATION_POLICIES,
        ResourceCapabilityAttestation(
            schema_version=RESOURCE_SUPERVISOR_SCHEMA,
            enforcement_backend="inherited-rlimits-plus-host-procfs-watchdog",
            platform="linux-posix-procfs",
            procfs_observations=("stat", "status", "io", "root/tmp", "task/children"),
            inherited_rlimits=(
                "RLIMIT_NPROC", "RLIMIT_AS", "RLIMIT_FSIZE", "RLIMIT_NOFILE",
                "RLIMIT_CORE", "RLIMIT_CPU", "RLIMIT_MSGQUEUE", "RLIMIT_RTPRIO",
                "RLIMIT_MEMLOCK",
            ),
            child_environment="empty",
            child_stdin="devnull",
            child_nice_increment=10,
            process_identity_guard="pid-start-ticks-plus-pidfd-signaling",
            namespace_tmp_accounting=(
                "bubblewrap-pre-exec-block-fd-barrier-plus-pinned-directory-fd"
            ),
            final_usage_scan="required-after-process-tree-cleanup-before-result",
            cgroup_v2_mounted=True,
            cgroup_delegated=False,
            cgroup_enforced=False,
            cgroup_unavailable_reason="synthetic-test-attestation",
            hard_aggregate_kernel_enforcement=False,
            limitations=("synthetic test descriptor; production compares observed host attestation",),
        ),
    )
    raw = {
        "schema_version": "paired-pilot-manifest-v1",
        "protocol_version": "phase2b-pilot-prereg-v1.3",
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
            "role_conflict_mitigation": None,
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
            "license_or_use_basis": "MIT test fixture",
            "provider_transmission_notice": {
                "schema_version": PHASE2B_PROVIDER_NOTICE_SCHEMA,
                "license_spdx": "MIT",
                "artifacts": [license_artifact],
                "transmission_text": provider_notice_text,
                "transmission_text_sha256": hashlib.sha256(
                    provider_notice_text.encode()
                ).hexdigest(),
                "transmit_to_each_agent_prompt": True,
                "data_only_not_task_requirement": True,
            },
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
            "agent_execution_isolation": {
                "schema_version": PHASE2B_AGENT_EXECUTION_ISOLATION_SCHEMA,
                "strategy": PHASE2B_AGENT_EXECUTION_ISOLATION_STRATEGY,
                "bubblewrap_binary_sha256": hashlib.sha256(
                    BUBBLEWRAP_EXECUTABLE.read_bytes()
                ).hexdigest(),
                "policy_sha256": PHASE2B_AGENT_EXECUTION_ISOLATION_POLICY_SHA256,
                "runtime_closure_schema_version": "phase2b-runtime-closure-v2",
                "agent_runtime_sha256_by_base": {
                    "claude-code": "e" * 64,
                    "codex": "f" * 64,
                },
                "mounted_toolchain_inventory_sha256": "a" * 64,
                "system_runtime_inventory_sha256": "b" * 64,
                "isolation_enforcer_inventory_sha256": "c" * 64,
                "runtime_closure_metadata_sha256": _runtime_metadata_sha256(()),
                "kernel_security_capability_record": kernel_security_record,
                "kernel_security_capability_sha256": hashlib.sha256(
                    json.dumps(
                        kernel_security_record,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
                "resource_supervisor": resource_descriptor,
            },
            "network_access": "forbidden",
            "secret_access": "forbidden",
            "push_access": "forbidden",
            "production_mutation": "forbidden",
        },
        "agents": [{
            "agent_id": "claude-code:claude-opus-5",
            "base_id": "claude-code",
            "model": "claude-opus-5",
            "reasoning_tier": None,
            "cli_version": "2.1.236",
            "permission_mode": "acceptEdits",
            "time_limit_seconds": 300,
        }, {
            "agent_id": "codex:gpt-5.6-sol:medium",
            "base_id": "codex",
            "model": "gpt-5.6-sol",
            "reasoning_tier": "medium",
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
            "analysis_contract_schema_version": "phase2b-exact60-v2-analysis-contract-v1",
            "analysis_contract_sha256": "a" * 64,
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


class _RenderedObservation:
    def __init__(self, policy, status: ExecutionStatus) -> None:
        self._policy = policy
        self._status = status

    def as_dict(self):
        policy_sha256 = hashlib.sha256(
            json.dumps(
                self._policy.as_dict(), sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        return {
            "schema_version": RESOURCE_SUPERVISOR_SCHEMA,
            "invocation_name": self._policy.name,
            "invocation_policy_sha256": policy_sha256,
            "outcome_status": self._status.value,
            "reason": "wall-timeout" if self._status is ExecutionStatus.TIMED_OUT else None,
            "cleanup_succeeded": True,
            "cleanup_status": "succeeded",
            "final_usage_scan_completed": True,
            "final_usage_scan_status": "completed",
            "namespace_tmp_pinned_before_exec": True,
            "peak_processes": 1,
            "peak_aggregate_rss_bytes": 1,
            "observed_aggregate_cpu_seconds": 0.0,
            "observed_aggregate_write_bytes": 0,
            "stdout_bytes_seen": 0,
            "stderr_bytes_seen": 0,
            "stdout_truncated": False,
            "stderr_truncated": False,
        }


class PolicyObservationProcessRunner(RecordingProcessRunner):
    def __init__(
        self,
        policy,
        *,
        status: ExecutionStatus = ExecutionStatus.COMPLETED,
        raised: BaseException | None = None,
    ) -> None:
        super().__init__()
        self.policy = policy
        self.status = status
        self.raised = raised
        self.last_observation = None

    def run(self, command, cwd, timeout_seconds):
        command = tuple(command)
        self.calls.append((command, cwd, timeout_seconds))
        self.last_observation = _RenderedObservation(self.policy, self.status)
        if self.raised is not None:
            raise self.raised
        return ProcessResult(
            command,
            self.status,
            "",
            "",
            None if self.status is ExecutionStatus.TIMED_OUT else 0,
            1.0,
        )


class EnvironmentRecordingProcessRunner(RecordingProcessRunner):
    def __init__(self, *, write_agent_state: bool = False) -> None:
        super().__init__()
        self.write_agent_state = write_agent_state
        self.environments: list[
            tuple[dict[str, str], tuple[str, ...], tuple[tuple[str, bool, bool], ...]]
        ] = []

    def run(self, command, cwd, timeout_seconds):
        command = tuple(command)
        if command and command[0] == str(BUBBLEWRAP_EXECUTABLE):
            environment = {}
            mounts = []
            for index, token in enumerate(command):
                if token == "--setenv":
                    environment[command[index + 1]] = command[index + 2]
                elif token in {"--bind", "--ro-bind"}:
                    mounts.append((command[index + 1], command[index + 2]))
            home_source = next(
                (
                    Path(source)
                    for source, target in mounts
                    if target == "/agent-home"
                ),
                None,
            )
            if home_source is not None:
                initial_entries = tuple(
                    (
                        str(path.relative_to(home_source)),
                        path.is_symlink(),
                        path.is_dir(),
                    )
                    for path in home_source.rglob("*")
                )
                self.environments.append(
                    (environment, ("--clearenv",), initial_entries)
                )
                if self.write_agent_state:
                    (home_source / "session-state.json").write_text(
                        "ephemeral agent state\n"
                    )
        return super().run(command, cwd, timeout_seconds)


class CredentialMutationProcessRunner(RecordingProcessRunner):
    def __init__(
        self,
        relative_credential: str,
        mutation,
        *,
        status: ExecutionStatus = ExecutionStatus.COMPLETED,
        raised: BaseException | None = None,
    ) -> None:
        super().__init__()
        self.relative_credential = relative_credential
        self.mutation = mutation
        self.status = status
        self.raised = raised

    def run(self, command, cwd, timeout_seconds):
        command = tuple(command)
        home = next(
            Path(command[index + 1])
            for index, token in enumerate(command)
            if token == "--bind" and command[index + 2] == "/agent-home"
        )
        self.mutation(home / self.relative_credential)
        self.calls.append((command, cwd, timeout_seconds))
        if self.raised is not None:
            raise self.raised
        return ProcessResult(
            command,
            self.status,
            "",
            "synthetic nonzero" if self.status is ExecutionStatus.FAILED else "",
            7 if self.status is ExecutionStatus.FAILED else 0,
            1.0,
        )


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

            floating_claude_model = copy.deepcopy(raw)
            floating_claude_model["agents"][0]["model"] = "opus"
            with self.assertRaisesRegex(Phase2bPilotError, "pinned full model ID"):
                phase2b_manifest_from_dict(floating_claude_model)

            floating_codex_model = copy.deepcopy(raw)
            floating_codex_model["agents"][1]["model"] = "codex-current"
            with self.assertRaisesRegex(Phase2bPilotError, "pinned full model ID"):
                phase2b_manifest_from_dict(floating_codex_model)

            unbound_agent_id = copy.deepcopy(raw)
            unbound_agent_id["agents"][0]["agent_id"] = "claude-code:other"
            with self.assertRaisesRegex(Phase2bPilotError, "must bind model"):
                phase2b_manifest_from_dict(unbound_agent_id)

            isolation_policy_drift = copy.deepcopy(raw)
            isolation_policy_drift["environment"]["agent_execution_isolation"][
                "policy_sha256"
            ] = "0" * 64
            with self.assertRaisesRegex(Phase2bPilotError, "policy_sha256"):
                phase2b_manifest_from_dict(isolation_policy_drift)

            task_rights_hash = copy.deepcopy(raw)
            task_rights_hash["tasks"][0]["source_provenance"][
                "task_statement_rights"
            ]["task_statement_sha256"] = "0" * 64
            with self.assertRaisesRegex(Phase2bPilotError, "exact task description"):
                phase2b_manifest_from_dict(task_rights_hash)

            task_rights_license = copy.deepcopy(raw)
            task_rights_license["tasks"][0]["source_provenance"][
                "task_statement_rights"
            ]["license_spdx"] = "Apache-2.0"
            with self.assertRaisesRegex(Phase2bPilotError, "must equal 'MIT'"):
                phase2b_manifest_from_dict(task_rights_license)

            task_rights_pending = copy.deepcopy(raw)
            task_rights_pending["tasks"][0]["source_provenance"][
                "task_statement_rights"
            ]["private_provider_transmission_verified"] = False
            with self.assertRaisesRegex(Phase2bPilotError, "must equal True"):
                phase2b_manifest_from_dict(task_rights_pending)

            direct_author_grant = copy.deepcopy(raw)
            direct_author_grant["tasks"][0]["source_provenance"][
                "task_statement_rights"
            ]["rights_basis"] = (
                "direct-author-contemporaneous-mit-grant-and-incorporation"
            )
            phase2b_manifest_from_dict(direct_author_grant)

            unknown_rights_basis = copy.deepcopy(raw)
            unknown_rights_basis["tasks"][0]["source_provenance"][
                "task_statement_rights"
            ]["rights_basis"] = "unsupported-rights-theory"
            with self.assertRaisesRegex(Phase2bPilotError, "rights_basis"):
                phase2b_manifest_from_dict(unknown_rights_basis)

    def test_approved_role_conflict_mitigation_is_strict_and_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw = build_phase2b_fixture(Path(directory))["raw"]

            approved = copy.deepcopy(raw)
            roles = approved["construction_roles"]
            roles["construction_role_sets_disjoint_attested"] = False
            roles["evaluator_author_role_ids"] = ["task-author-1"]
            for task in approved["tasks"]:
                task["evaluator"]["evaluator_author_role_id"] = "task-author-1"
            roles["role_conflict_mitigation"] = {
                "schema_version": "approved-conflict-mitigation-v1",
                "exception_scope_experiment_id": approved["experiment_id"],
                "role_conflict_amendment_sha256": "a" * 64,
                "completion_evidence_sha256": "b" * 64,
                "independent_validity_reviewer_role_ids": [
                    "validity-reviewer-1"
                ],
                "review_item_count": 60,
                "assertion_count": 60,
                "review_passed": True,
                "completed_before_manifest_freeze": True,
                "candidate_agent_results_observed_before_completion": False,
            }
            phase2b_manifest_from_dict(approved)

            false_without_mitigation = copy.deepcopy(raw)
            false_without_mitigation["construction_roles"][
                "construction_role_sets_disjoint_attested"
            ] = False
            with self.assertRaisesRegex(
                Phase2bPilotError, "role_conflict_mitigation must be an object"
            ):
                phase2b_manifest_from_dict(false_without_mitigation)

            true_with_mitigation = copy.deepcopy(approved)
            true_with_mitigation["construction_roles"][
                "construction_role_sets_disjoint_attested"
            ] = True
            with self.assertRaisesRegex(
                Phase2bPilotError, "requires role_conflict_mitigation=null"
            ):
                phase2b_manifest_from_dict(true_with_mitigation)

            overlapping_reviewer = copy.deepcopy(approved)
            overlapping_reviewer["construction_roles"][
                "validity_reviewer_role_ids"
            ] = ["task-author-1"]
            overlapping_reviewer["construction_roles"][
                "role_conflict_mitigation"
            ]["independent_validity_reviewer_role_ids"] = ["task-author-1"]
            for task in overlapping_reviewer["tasks"]:
                task["evaluator"]["validity_reviewer_role_id"] = "task-author-1"
            with self.assertRaisesRegex(
                Phase2bPilotError, "requires independent validity reviewers"
            ):
                phase2b_manifest_from_dict(overlapping_reviewer)

            reviewer_mismatch = copy.deepcopy(approved)
            reviewer_mismatch["construction_roles"][
                "role_conflict_mitigation"
            ]["independent_validity_reviewer_role_ids"] = ["other-reviewer"]
            with self.assertRaisesRegex(
                Phase2bPilotError, "reviewer roles must equal"
            ):
                phase2b_manifest_from_dict(reviewer_mismatch)

            wrong_scope = copy.deepcopy(approved)
            wrong_scope["construction_roles"]["role_conflict_mitigation"][
                "exception_scope_experiment_id"
            ] = "different-experiment"
            with self.assertRaisesRegex(Phase2bPilotError, "different experiment"):
                phase2b_manifest_from_dict(wrong_scope)

            short_hash = copy.deepcopy(approved)
            short_hash["construction_roles"]["role_conflict_mitigation"][
                "completion_evidence_sha256"
            ] = "c" * 40
            with self.assertRaisesRegex(Phase2bPilotError, "lowercase SHA-256"):
                phase2b_manifest_from_dict(short_hash)

            count_drift = copy.deepcopy(approved)
            count_drift["construction_roles"]["role_conflict_mitigation"][
                "assertion_count"
            ] = 59
            with self.assertRaisesRegex(Phase2bPilotError, "assertion_count"):
                phase2b_manifest_from_dict(count_drift)

            unknown = copy.deepcopy(approved)
            unknown["construction_roles"]["role_conflict_mitigation"][
                "silent_extra"
            ] = True
            with self.assertRaisesRegex(Phase2bPilotError, "fields mismatch"):
                phase2b_manifest_from_dict(unknown)

    def test_provider_notice_context_is_exact_and_fails_closed_on_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = build_phase2b_fixture(Path(directory))
            raw = fixture["raw"]

            wrong_text_hash = copy.deepcopy(raw)
            wrong_text_hash["repositories"][0]["provider_transmission_notice"][
                "transmission_text_sha256"
            ] = "0" * 64
            with self.assertRaisesRegex(Phase2bPilotError, "text hash mismatch"):
                phase2b_manifest_from_dict(wrong_text_hash)

            wrong_artifact_hash = copy.deepcopy(raw)
            wrong_artifact_hash["repositories"][0]["provider_transmission_notice"][
                "artifacts"
            ][0]["sha256"] = "0" * 64
            wrong_artifact_manifest = phase2b_manifest_from_dict(wrong_artifact_hash)
            fixture["manifest_path"].write_text(
                json.dumps(wrong_artifact_hash, indent=2) + "\n"
            )
            with self.assertRaisesRegex(Phase2bPilotError, "artifact hash changed"):
                validate_phase2b_environment(
                    wrong_artifact_manifest,
                    fixture["manifest_path"],
                    {"repo-1": fixture["source"]},
                    fixture["evaluator_root"],
                    fixture["inventory"],
                )

            wrong_rendered_text = copy.deepcopy(raw)
            notice = wrong_rendered_text["repositories"][0][
                "provider_transmission_notice"
            ]
            notice["transmission_text"] += "not present in the source artifact\n"
            notice["transmission_text_sha256"] = hashlib.sha256(
                notice["transmission_text"].encode()
            ).hexdigest()
            wrong_text_manifest = phase2b_manifest_from_dict(wrong_rendered_text)
            fixture["manifest_path"].write_text(
                json.dumps(wrong_rendered_text, indent=2) + "\n"
            )
            with self.assertRaisesRegex(Phase2bPilotError, "notice text changed"):
                validate_phase2b_environment(
                    wrong_text_manifest,
                    fixture["manifest_path"],
                    {"repo-1": fixture["source"]},
                    fixture["evaluator_root"],
                    fixture["inventory"],
                )

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
                "schema_version": "phase2b-pilot-run-authorization-v2",
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
                "approval_message_sha256": "c" * 64,
                "authorization_scope": PHASE2B_AUTHORIZATION_SCOPE,
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
            authorization["approved_by_role_id"] = "run-operator-1"
            for field, bad_value, expected in (
                ("approval_message_sha256", "not-a-hash", "lowercase SHA-256"),
                ("authorization_scope", "run whatever remains", "authorization_scope"),
            ):
                with self.subTest(field=field):
                    invalid = copy.deepcopy(authorization)
                    invalid[field] = bad_value
                    authorization_path.write_text(json.dumps(invalid) + "\n")
                    with self.assertRaisesRegex(Phase2bPilotError, expected):
                        load_run_authorization(
                            authorization_path,
                            manifest_path=fixture["manifest_path"],
                            manifest=manifest,
                        )


class Phase2bDryRunTests(unittest.TestCase):
    def _credential_runner(
        self,
        root: Path,
        delegate,
        *,
        payload: str = '{"token":"first"}\n',
        home_name: str = "isolated-home",
    ):
        fixture = build_phase2b_fixture(root)
        manifest = phase2b_manifest_from_dict(fixture["raw"])
        spec = next(item for item in manifest.agents if item.base_id == "codex")
        workspace = root / "workspace"
        workspace.mkdir(exist_ok=True)
        if not (workspace / ".git").exists():
            git(workspace, "init", "-q")
        credential_home = root / "credential-home"
        credential_home.mkdir(mode=0o700, exist_ok=True)
        provider_home = credential_home / ".codex"
        provider_home.mkdir(mode=0o700, exist_ok=True)
        credential = provider_home / "auth.json"
        if not credential.exists():
            credential.write_text(payload)
            credential.chmod(0o600)
        isolated = _BubblewrapIsolatedAgentProcessRunner(
            delegate,
            root / home_name,
            workspace,
            agent_spec=spec,
            credential_home=credential_home,
            toolchain_home=root,
            evaluator_root=fixture["evaluator_root"],
            evaluator_native_helper=fixture["evaluator_root"] / "quality.py",
            expected_bubblewrap_sha256=str(
                manifest.agent_execution_isolation["bubblewrap_binary_sha256"]
            ),
            runtime_resolver=lambda _base, _exe: _AgentRuntime(
                command_prefix=("/phase2b-bin/codex",), mounts=()
            ),
        )
        return isolated, spec, workspace, credential

    def test_runtime_content_hash_two_close_interruptions_preserve_ki_without_fd_leak(
        self,
    ) -> None:
        real_open = os.open
        real_close = os.close
        opened_descriptor: int | None = None
        close_interruptions = 0

        def remember_open(*args, **kwargs):
            nonlocal opened_descriptor
            opened_descriptor = real_open(*args, **kwargs)
            return opened_descriptor

        def interrupt_two_closes(descriptor: int) -> None:
            nonlocal close_interruptions
            if descriptor == opened_descriptor and close_interruptions < 2:
                close_interruptions += 1
                raise KeyboardInterrupt()
            real_close(descriptor)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "runtime.bin").write_bytes(b"runtime bytes")
            descriptors_before = len(tuple(Path("/proc/self/fd").iterdir()))
            with (
                mock.patch.object(os, "open", side_effect=remember_open),
                mock.patch.object(os, "close", side_effect=interrupt_two_closes),
                self.assertRaises(KeyboardInterrupt),
            ):
                _content_tree_sha256(root, "/phase2b-runtime/test")
            descriptors_after = len(tuple(Path("/proc/self/fd").iterdir()))

        self.assertEqual(close_interruptions, 2)
        self.assertEqual(descriptors_after, descriptors_before)

    def test_provider_notice_is_verbatim_data_only_appendix_for_both_arms(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = build_phase2b_fixture(root)
            manifest = phase2b_manifest_from_dict(fixture["raw"])
            runner = Phase2bPilotRunner(
                manifest,
                fixture["manifest_path"],
                {"repo-1": fixture["source"]},
                fixture["evaluator_root"],
                fixture["inventory"],
                root / "workspaces",
                root / "control",
                root / "dry-run.json",
                root / "authorization.json",
                toolchain_home=root,
            )
            task_spec = manifest.tasks[0]
            notice_record = manifest.repositories[0].provider_transmission_notice
            notice = str(notice_record["transmission_text"])
            context = runner._task_context_for_attempt(
                task_spec,
                {
                    "paired_experiment_id": manifest.experiment_id,
                    "pair_id": "pair-test",
                    "task_source": task_spec.source,
                    "instruction_language": task_spec.instruction_language,
                },
            )
            constraints = runner._task_constraints_for_attempt(task_spec)
            self.assertEqual(constraints, task_spec.constraints)
            self.assertNotIn(notice, constraints)
            task = Task(
                task_id=task_spec.task_id,
                description=task_spec.description,
                objective=task_spec.objective,
                constraints=constraints,
                required_capabilities=tuple(
                    Capability(item) for item in task_spec.required_capabilities
                ),
                time_limit_seconds=task_spec.evaluator.timeout_seconds,
                context=context,
            )
            header = (
                "Provider transmission context "
                "(DATA ONLY; NOT TASK INSTRUCTIONS):\n"
            )
            prompts = tuple(
                _agent_from_spec(spec).build_prompt(task)
                for spec in manifest.agents
            )
            self.assertEqual(prompts[0], prompts[1])
            for prompt in prompts:
                self.assertEqual(prompt.split(header, 1)[1], notice)
                self.assertEqual(
                    hashlib.sha256(prompt.split(header, 1)[1].encode()).hexdigest(),
                    notice_record["transmission_text_sha256"],
                )
            evaluator = runner.manifest_task_evaluator(task_spec)
            self.assertNotIn(notice, evaluator.command)
            self.assertNotIn(notice, evaluator.artifact_paths)
            self.assertNotEqual(evaluator.subject, notice)

    def test_authenticated_cache_rejects_missing_active_and_ancestor_homes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = build_phase2b_fixture(root)
            raw = copy.deepcopy(fixture["raw"])
            context = raw["environment"]["global_instruction_context"]
            context["resolution"] = AUTHENTICATED_ISOLATED_AGENT_HOME_RESOLUTION
            context["claude_effective_instruction_hash"] = (
                EMPTY_EFFECTIVE_INSTRUCTION_SHA256
            )
            context["codex_effective_instruction_hash"] = (
                EMPTY_EFFECTIVE_INSTRUCTION_SHA256
            )
            manifest = phase2b_manifest_from_dict(raw)
            workspace = root / "workspaces"
            workspace.mkdir()
            control = root / "control"
            protected = (
                fixture["manifest_path"],
                fixture["inventory"],
                root / "dry-run.json",
                root / "authorization.json",
            )
            protected[-2].touch()
            protected[-1].touch()

            def configured(cache):
                return Phase2bPilotRunner(
                    manifest,
                    fixture["manifest_path"],
                    {"repo-1": fixture["source"]},
                    fixture["evaluator_root"],
                    fixture["inventory"],
                    workspace,
                    control,
                    protected[-2],
                    protected[-1],
                    credential_home=cache,
                )

            missing = configured(None)
            with self.assertRaisesRegex(
                Phase2bExecutionError, "explicit private credential cache"
            ):
                missing._validate_credential_cache_boundaries(
                    source_roots={"repo-1": fixture["source"]},
                    workspace_root=workspace,
                    evaluator_root=fixture["evaluator_root"],
                    control=control,
                    protected_inputs=protected,
                )
            for cache, message in (
                (Path.home(), "active home"),
                (root, "outside sources"),
            ):
                with self.subTest(cache=cache):
                    runner = configured(cache)
                    with self.assertRaisesRegex(Phase2bExecutionError, message):
                        runner._validate_credential_cache_boundaries(
                            source_roots={"repo-1": fixture["source"]},
                            workspace_root=workspace,
                            evaluator_root=fixture["evaluator_root"],
                            control=control,
                            protected_inputs=protected,
                        )
            dedicated = root / "private-credential-cache"
            dedicated.mkdir(mode=0o700)
            configured(dedicated)._validate_credential_cache_boundaries(
                source_roots={"repo-1": fixture["source"]},
                workspace_root=workspace,
                evaluator_root=fixture["evaluator_root"],
                control=control,
                protected_inputs=protected,
            )

    def test_credential_refresh_rotates_serially_through_private_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, spec, workspace, credential = self._credential_runner(
                root, RecordingProcessRunner()
            )
            _, first_target = first._prepare_home()
            assert first_target is not None
            first_target.write_text('{"token":"second"}\n')
            self.assertIsNone(first._finalize_credential_lease())
            self.assertIsNone(first._clear_home())
            self.assertEqual(credential.read_text(), '{"token":"second"}\n')
            self.assertEqual(first._credential_refresh_status, "refreshed")

            second = _BubblewrapIsolatedAgentProcessRunner(
                RecordingProcessRunner(),
                root / "isolated-home-2",
                workspace,
                agent_spec=spec,
                credential_home=root / "credential-home",
                toolchain_home=root,
                evaluator_root=root / "evaluators",
                evaluator_native_helper=root / "evaluators" / "quality.py",
                expected_bubblewrap_sha256=first._expected_bubblewrap_sha256,
                runtime_resolver=lambda _base, _exe: _AgentRuntime(
                    command_prefix=("/phase2b-bin/codex",), mounts=()
                ),
            )
            _, second_target = second._prepare_home()
            assert second_target is not None
            self.assertEqual(second_target.read_text(), '{"token":"second"}\n')
            second_target.write_text('{"token":"third"}\n')
            self.assertIsNone(second._finalize_credential_lease())
            self.assertIsNone(second._clear_home())
            self.assertEqual(credential.read_text(), '{"token":"third"}\n')

    def test_credential_refresh_persists_on_nonzero_and_agent_interrupt(self) -> None:
        cases = (
            (ExecutionStatus.FAILED, None, '{"token":"nonzero"}\n'),
            (ExecutionStatus.COMPLETED, KeyboardInterrupt(), '{"token":"interrupt"}\n'),
        )
        for index, (status, raised, refreshed) in enumerate(cases):
            with self.subTest(raised=type(raised).__name__ if raised else "none"):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    delegate = CredentialMutationProcessRunner(
                        ".codex/auth.json",
                        lambda path, value=refreshed: path.write_text(value),
                        status=status,
                        raised=raised,
                    )
                    isolated, spec, workspace, credential = self._credential_runner(
                        root, delegate, home_name=f"isolated-home-{index}"
                    )
                    command = exact_agent_command(spec, workspace)
                    if raised is None:
                        result = isolated.run(command, workspace, 2)
                        self.assertEqual(result.status, ExecutionStatus.FAILED)
                    else:
                        with self.assertRaises(KeyboardInterrupt):
                            isolated.run(command, workspace, 2)
                    self.assertEqual(credential.read_text(), refreshed)
                    self.assertEqual(
                        isolated._credential_refresh_status, "refreshed"
                    )
                    self.assertEqual(tuple(isolated._home.iterdir()), ())
                    agent_record = isolated.resource_observations()[0]
                    self.assertEqual(
                        agent_record["credential_refresh_status"], "refreshed"
                    )

    def test_credential_refresh_rejects_target_drift_and_preserves_source(self) -> None:
        mutations = {
            "symlink": lambda target, root: (
                target.unlink(),
                target.symlink_to(root / "outside-secret"),
            ),
            "hardlink": lambda target, root: os.link(
                target, root / "credential-hardlink"
            ),
            "mode": lambda target, _root: target.chmod(0o644),
            "oversize": lambda target, _root: target.write_bytes(
                b"{" + b"x" * (1024 * 1024) + b"}"
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    (root / "outside-secret").write_text('{"outside":true}\n')
                    isolated, _, _, credential = self._credential_runner(
                        root, RecordingProcessRunner()
                    )
                    _, target = isolated._prepare_home()
                    assert target is not None
                    mutate(target, root)
                    self.assertIn(
                        "credential refresh validation",
                        isolated._finalize_credential_lease() or "",
                    )
                    self.assertEqual(
                        credential.read_text(), '{"token":"first"}\n'
                    )
                    self.assertEqual(isolated._credential_refresh_status, "invalid")
                    self.assertIsNone(isolated._clear_home())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            isolated, _, _, credential = self._credential_runner(
                root, RecordingProcessRunner()
            )
            _, target = isolated._prepare_home()
            assert target is not None
            credential.write_text('{"token":"concurrent-drift"}\n')
            target.write_text('{"token":"must-not-overwrite-drift"}\n')
            self.assertIn(
                "credential refresh validation",
                isolated._finalize_credential_lease() or "",
            )
            self.assertEqual(
                credential.read_text(), '{"token":"concurrent-drift"}\n'
            )
            self.assertIsNone(isolated._clear_home())

        for renamed_level in ("provider", "cache"):
            with self.subTest(renamed_level=renamed_level):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    isolated, _, _, _ = self._credential_runner(
                        root, RecordingProcessRunner()
                    )
                    _, target = isolated._prepare_home()
                    assert target is not None
                    cache = root / "credential-home"
                    if renamed_level == "provider":
                        original = cache / ".codex"
                        moved = cache / ".codex-moved"
                        original.rename(moved)
                        original.mkdir(mode=0o700)
                        replacement = original / "auth.json"
                    else:
                        original = cache
                        moved = root / "credential-home-moved"
                        original.rename(moved)
                        original.mkdir(mode=0o700)
                        (original / ".codex").mkdir(mode=0o700)
                        replacement = original / ".codex" / "auth.json"
                    replacement.write_text('{"token":"replacement"}\n')
                    replacement.chmod(0o600)
                    target.write_text('{"token":"refreshed"}\n')
                    self.assertIn(
                        "credential refresh validation",
                        isolated._finalize_credential_lease() or "",
                    )
                    self.assertEqual(
                        replacement.read_text(), '{"token":"replacement"}\n'
                    )
                    self.assertIsNone(isolated._clear_home())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            isolated, _, _, _ = self._credential_runner(
                root, RecordingProcessRunner()
            )
            _, target = isolated._prepare_home()
            assert target is not None
            target.write_text('{"token":"refreshed-during-race"}\n')
            provider = root / "credential-home" / ".codex"
            moved = root / "credential-home" / ".codex-moved"
            real_replace = os.replace

            def replace_after_provider_swap(
                source,
                destination,
                *,
                src_dir_fd=None,
                dst_dir_fd=None,
            ):
                provider.rename(moved)
                provider.mkdir(mode=0o700)
                canonical = provider / "auth.json"
                canonical.write_text('{"token":"canonical-replacement"}\n')
                canonical.chmod(0o600)
                return real_replace(
                    source,
                    destination,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                )

            with mock.patch(
                "adaptive_orchestrator.experiments.phase2b_runner.os.replace",
                side_effect=replace_after_provider_swap,
            ):
                self.assertIn(
                    "credential refresh validation",
                    isolated._finalize_credential_lease() or "",
                )
            self.assertEqual(
                (provider / "auth.json").read_text(),
                '{"token":"canonical-replacement"}\n',
            )
            self.assertEqual(
                (moved / "auth.json").read_text(),
                '{"token":"refreshed-during-race"}\n',
            )
            self.assertEqual(isolated._credential_refresh_status, "invalid")
            self.assertIsNone(isolated._clear_home())

    def test_agent_adapter_command_shape_rejects_late_security_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = build_phase2b_fixture(root)
            manifest = phase2b_manifest_from_dict(fixture["raw"])
            workspace = root / "workspace"
            workspace.mkdir()
            git(workspace, "init", "-q")
            runtime = _AgentRuntime(command_prefix=("/phase2b-bin/agent",), mounts=())
            override_tokens = {
                "claude-code": (
                    "--settings", "{}", "--mcp-config", '{"mcpServers":{"x":{}}}',
                    "--dangerously-skip-permissions", "--add-dir", "/", "--resume",
                ),
                "codex": (
                    "-c", 'approval_policy="on-request"', "--enable", "web_search",
                    "--search", "--dangerously-bypass-approvals-and-sandbox",
                ),
            }
            for spec in manifest.agents:
                isolated = _BubblewrapIsolatedAgentProcessRunner(
                    RecordingProcessRunner(),
                    root / f"home-{spec.base_id}",
                    workspace,
                    agent_spec=spec,
                    credential_home=None,
                    toolchain_home=root,
                    evaluator_root=fixture["evaluator_root"],
                    evaluator_native_helper=fixture["evaluator_root"] / "quality.py",
                    expected_bubblewrap_sha256=hashlib.sha256(
                        BUBBLEWRAP_EXECUTABLE.read_bytes()
                    ).hexdigest(),
                    runtime_resolver=lambda _base, _executable: runtime,
                )
                exact = exact_agent_command(spec, workspace, "safe prompt")
                hardened = isolated._isolated_agent_command(exact, runtime)
                self.assertEqual(hardened[-1], "safe prompt")
                for token in override_tokens[spec.base_id]:
                    injected = (*exact[:-1], token, exact[-1])
                    with self.assertRaisesRegex(ValueError, "command shape drifted"):
                        isolated._isolated_agent_command(injected, runtime)
                with self.assertRaisesRegex(ValueError, "safe positional"):
                    isolated._isolated_agent_command(
                        (*exact[:-1], "--settings"), runtime
                    )
                with self.assertRaisesRegex(ValueError, "command shape drifted"):
                    isolated._isolated_agent_command(
                        (f"/untrusted/{exact[0]}", *exact[1:]), runtime
                    )

    def test_agent_free_attestation_builds_exact_manifest_isolation_field(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = build_phase2b_fixture(root)
            expected = fixture["raw"]["environment"][
                "agent_execution_isolation"
            ]
            runtime_keys = (
                "runtime_closure_schema_version",
                "agent_runtime_sha256_by_base",
                "mounted_toolchain_inventory_sha256",
                "system_runtime_inventory_sha256",
                "isolation_enforcer_inventory_sha256",
                "runtime_closure_metadata_sha256",
                "kernel_security_capability_record",
                "kernel_security_capability_sha256",
            )
            closure = _RuntimeClosure(
                agent_runtimes={},
                toolchain_mounts=(),
                observed_evidence={key: expected[key] for key in runtime_keys},
                metadata_mounts=(),
                attested_metadata_sha256=expected[
                    "runtime_closure_metadata_sha256"
                ],
            )
            module = "adaptive_orchestrator.experiments.phase2b_runner"
            with (
                mock.patch(f"{module}._resolve_runtime_closure", return_value=closure),
                mock.patch(
                    f"{module}._phase2b_resource_supervisor_descriptor",
                    return_value=expected["resource_supervisor"],
                ),
            ):
                observed = attest_phase2b_runtime_closure(root)
            self.assertEqual(observed, expected)
            raw = copy.deepcopy(fixture["raw"])
            raw["environment"]["agent_execution_isolation"] = observed
            parsed = phase2b_manifest_from_dict(raw)
            self.assertEqual(parsed.agent_execution_isolation, expected)

    def test_role_specific_resource_supervisors_survive_agent_preflight_rejection(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = build_phase2b_fixture(root)
            manifest = phase2b_manifest_from_dict(fixture["raw"])
            agent_spec = manifest.agents[0]
            workspace_root = root / "workspaces"
            workspace = workspace_root / "task-01" / agent_spec.agent_id
            workspace.mkdir(parents=True)
            git(workspace, "init", "-q")
            created: list[PolicyObservationProcessRunner] = []

            def supervisor_factory(policies, _roots):
                self.assertEqual(len(policies), 1)
                status = (
                    ExecutionStatus.COMPLETED
                    if policies[0].name == "agent"
                    else ExecutionStatus.TIMED_OUT
                )
                runner = PolicyObservationProcessRunner(
                    policies[0], status=status
                )
                created.append(runner)
                return runner

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
                resource_supervisor_factory=supervisor_factory,
                evaluator_native_helper_resolver=lambda: (
                    fixture["evaluator_root"] / "quality.py"
                ),
                _test_only_allow_enforcement_injection=True,
            )
            bound = runner._process_runner_for_attempt(agent_spec, workspace)
            rejected = bound.run(
                exact_agent_command(agent_spec, workspace),
                root,
                1,
            )
            self.assertEqual(rejected.status, ExecutionStatus.SPAWN_ERROR)
            evaluator = bound.run(
                (str(fixture["evaluator_root"] / "quality.py"),),
                workspace,
                1,
            )
            self.assertEqual(evaluator.status, ExecutionStatus.TIMED_OUT)
            self.assertEqual([item.policy.name for item in created], ["agent", "evaluator"])
            self.assertEqual(created[0].calls, [])
            self.assertEqual(len(created[1].calls), 1)
            observations = bound.resource_observations()
            self.assertEqual(
                [item["invocation_name"] for item in observations],
                ["agent", "evaluator"],
            )
            self.assertEqual(
                observations[0]["reason"], "not-invoked-preflight-rejected"
            )
            self.assertEqual(observations[0]["cleanup_status"], "not-required")
            self.assertEqual(
                observations[0]["final_usage_scan_status"], "not-applicable"
            )
            self.assertEqual(
                observations[1]["outcome_status"], ExecutionStatus.TIMED_OUT.value
            )

    def test_evaluator_interruption_still_captures_role_observation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = build_phase2b_fixture(root)
            manifest = phase2b_manifest_from_dict(fixture["raw"])
            agent_spec = manifest.agents[0]
            workspace = root / "workspace"
            workspace.mkdir()
            git(workspace, "init", "-q")
            agent_delegate = PolicyObservationProcessRunner(
                PHASE2B_RESOURCE_INVOCATION_POLICIES[0]
            )
            evaluator_delegate = PolicyObservationProcessRunner(
                PHASE2B_RESOURCE_INVOCATION_POLICIES[1],
                status=ExecutionStatus.FAILED,
                raised=KeyboardInterrupt(),
            )
            bound = _BubblewrapIsolatedAgentProcessRunner(
                agent_delegate,
                root / "home",
                workspace,
                agent_spec=agent_spec,
                credential_home=None,
                toolchain_home=root,
                evaluator_root=fixture["evaluator_root"],
                evaluator_native_helper=fixture["evaluator_root"] / "quality.py",
                expected_bubblewrap_sha256=hashlib.sha256(
                    BUBBLEWRAP_EXECUTABLE.read_bytes()
                ).hexdigest(),
                runtime_resolver=lambda _base, _executable: _AgentRuntime((), ()),
                evaluator_delegate=evaluator_delegate,
                require_resource_observation=True,
            )
            rejected = bound.run(
                exact_agent_command(agent_spec, workspace), root, 1
            )
            self.assertEqual(rejected.status, ExecutionStatus.SPAWN_ERROR)
            with self.assertRaises(KeyboardInterrupt):
                bound.run(
                    (str(fixture["evaluator_root"] / "quality.py"),),
                    workspace,
                    1,
                )
            observations = bound.resource_observations()
            self.assertEqual(len(observations), 2)
            self.assertEqual(observations[1]["invocation_name"], "evaluator")
            self.assertEqual(
                observations[1]["outcome_status"], ExecutionStatus.FAILED.value
            )

    def test_delegate_baseexception_preserved_while_all_terminal_cleanup_is_visited(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = build_phase2b_fixture(root)
            manifest = phase2b_manifest_from_dict(fixture["raw"])
            workspace = root / "workspace"
            workspace.mkdir()
            git(workspace, "init", "-q")

            for role in ("agent", "evaluator"):
                with self.subTest(role=role):
                    original = KeyboardInterrupt(f"original-{role}")
                    delegate = mock.Mock()
                    delegate.run.side_effect = original
                    delegate.last_observation = None
                    bound = _BubblewrapIsolatedAgentProcessRunner(
                        delegate,
                        root / f"home-{role}",
                        workspace,
                        agent_spec=manifest.agents[0],
                        credential_home=None,
                        toolchain_home=root,
                        evaluator_root=fixture["evaluator_root"],
                        evaluator_native_helper=(
                            fixture["evaluator_root"] / "quality.py"
                        ),
                        expected_bubblewrap_sha256="a" * 64,
                        runtime_resolver=lambda _base, _executable: _AgentRuntime(
                            (), ()
                        ),
                        evaluator_delegate=delegate,
                    )
                    visited: list[str] = []

                    def fail_observation(*_args):
                        visited.append("observation")
                        raise RuntimeError("observation cleanup failed")

                    def fail_credential():
                        visited.append("credential")
                        raise SystemExit(23)

                    def fail_home():
                        visited.append("home")
                        raise GeneratorExit()

                    if role == "evaluator":
                        bound._agent_invocation_consumed = True
                    preflight_patches = (
                        mock.patch.object(bound, "_validate_bubblewrap"),
                        mock.patch.object(
                            bound,
                            "_isolated_evaluator_command"
                            if role == "evaluator"
                            else "_isolated_agent_command",
                            return_value=("isolated",),
                        ),
                        mock.patch.object(
                            bound,
                            "_evaluator_bubblewrap_command"
                            if role == "evaluator"
                            else "_bubblewrap_command",
                            return_value=("bwrap",),
                        ),
                        mock.patch.object(
                            bound,
                            "_capture_resource_observation",
                            side_effect=fail_observation,
                        ),
                        mock.patch.object(
                            bound, "_clear_home", side_effect=fail_home
                        ),
                    )
                    with (
                        preflight_patches[0],
                        preflight_patches[1],
                        preflight_patches[2],
                        preflight_patches[3],
                        preflight_patches[4],
                        mock.patch.object(
                            bound,
                            "_prepare_home",
                            return_value=(None, None),
                        ),
                        mock.patch.object(
                            bound,
                            "_finalize_credential_lease",
                            side_effect=fail_credential,
                        ),
                    ):
                        with self.assertRaises(KeyboardInterrupt) as raised:
                            bound.run(("candidate",), workspace, 1)

                    self.assertIs(raised.exception, original)
                    self.assertEqual(
                        visited,
                        (
                            ["observation", "home"]
                            if role == "evaluator"
                            else ["observation", "credential", "home"]
                        ),
                    )

    def test_successful_delegate_fails_closed_on_terminal_cleanup_exception(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = build_phase2b_fixture(root)
            manifest = phase2b_manifest_from_dict(fixture["raw"])
            workspace = root / "workspace"
            workspace.mkdir()
            git(workspace, "init", "-q")
            delegate = mock.Mock()
            delegate.run.return_value = ProcessResult(
                ("bwrap",), ExecutionStatus.COMPLETED, "", "", 0, 1.0
            )
            bound = _BubblewrapIsolatedAgentProcessRunner(
                delegate,
                root / "home",
                workspace,
                agent_spec=manifest.agents[0],
                credential_home=None,
                toolchain_home=root,
                evaluator_root=fixture["evaluator_root"],
                evaluator_native_helper=fixture["evaluator_root"] / "quality.py",
                expected_bubblewrap_sha256="a" * 64,
                runtime_resolver=lambda _base, _executable: _AgentRuntime((), ()),
            )
            with (
                mock.patch.object(bound, "_validate_bubblewrap"),
                mock.patch.object(
                    bound, "_prepare_home", return_value=(None, None)
                ),
                mock.patch.object(
                    bound, "_isolated_agent_command", return_value=("isolated",)
                ),
                mock.patch.object(
                    bound, "_bubblewrap_command", return_value=("bwrap",)
                ),
                mock.patch.object(
                    bound,
                    "_capture_resource_observation",
                    side_effect=RuntimeError("terminal observation failed"),
                ),
                mock.patch.object(
                    bound, "_finalize_credential_lease", return_value=None
                ),
                mock.patch.object(bound, "_clear_home", return_value=None),
            ):
                result = bound.run(("candidate",), workspace, 1)
            self.assertEqual(result.status, ExecutionStatus.SPAWN_ERROR)
            self.assertIn("terminal cleanup failed", result.stderr)

    def test_agent_interruptions_finalize_once_with_two_role_resource_records(
        self,
    ) -> None:
        for interruption in (KeyboardInterrupt(), SystemExit(17)):
            with self.subTest(interruption=type(interruption).__name__), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                fixture = build_phase2b_fixture(root)
                manifest = phase2b_manifest_from_dict(fixture["raw"])
                agent_spec = manifest.agents[0]
                assignment = assign_pairs(manifest.paired)[0]
                workspace = root / "workspace"
                workspace.mkdir()
                git(workspace, "init", "-q")
                delegate = PolicyObservationProcessRunner(
                    PHASE2B_RESOURCE_INVOCATION_POLICIES[0],
                    status=ExecutionStatus.FAILED,
                    raised=interruption,
                )
                evaluator_delegate = PolicyObservationProcessRunner(
                    PHASE2B_RESOURCE_INVOCATION_POLICIES[1]
                )
                bound = _BubblewrapIsolatedAgentProcessRunner(
                    delegate,
                    root / "home",
                    workspace,
                    agent_spec=agent_spec,
                    credential_home=None,
                    toolchain_home=root,
                    evaluator_root=fixture["evaluator_root"],
                    evaluator_native_helper=(
                        fixture["evaluator_root"] / "quality.py"
                    ),
                    expected_bubblewrap_sha256=hashlib.sha256(
                        BUBBLEWRAP_EXECUTABLE.read_bytes()
                    ).hexdigest(),
                    runtime_resolver=lambda _base, _executable: _AgentRuntime(
                        ("/phase2b-bin/agent",), ()
                    ),
                    evaluator_delegate=evaluator_delegate,
                    require_resource_observation=True,
                )
                smoke = PairedSmokeRunner(
                    manifest.paired,
                    fixture["manifest_path"],
                    fixture["source"],
                    root / "unused-workspace-root",
                    root / "control",
                )
                smoke._process_runner_for_attempt = (  # type: ignore[method-assign]
                    lambda _spec, _workspace: bound
                )
                event_store = JsonlEventStore(root / "events.jsonl")
                recorder = LifecycleRecorder(event_store)
                started = monotonic()
                with self.assertRaises(type(interruption)):
                    smoke._run_attempt(
                        recorder,
                        _agent_from_spec(agent_spec),
                        agent_spec,
                        manifest.tasks[0],
                        assignment,
                        workspace,
                        "c" * 64,
                        started,
                        started + 100,
                        0.0,
                    )
                events = event_store.read()
                self.assertEqual(
                    [event.event_type for event in events],
                    [
                        LifecycleEventType.SELECTION_MADE,
                        LifecycleEventType.EXECUTION_STARTED,
                        LifecycleEventType.EXECUTION_TERMINAL,
                        LifecycleEventType.OUTCOME_FINALIZED,
                    ],
                )
                outcomes = [
                    event
                    for event in events
                    if event.event_type is LifecycleEventType.OUTCOME_FINALIZED
                ]
                self.assertEqual(len(outcomes), 1)
                self.assertEqual(outcomes[0].payload["status"], "interrupted")
                self.assertEqual(
                    outcomes[0].payload["error_type"],
                    type(interruption).__name__,
                )
                invocations = outcomes[0].payload["resource_observation"][
                    "resource_supervisor_invocations"
                ]
                self.assertEqual(
                    [item["invocation_name"] for item in invocations],
                    ["agent", "evaluator"],
                )
                self.assertEqual(
                    invocations[0]["outcome_status"],
                    ExecutionStatus.FAILED.value,
                )
                self.assertEqual(
                    invocations[1]["reason"],
                    "not-invoked-agent-interrupted",
                )
                self.assertEqual(evaluator_delegate.calls, [])

    def test_evaluator_recorder_failure_preserves_original_interruption(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = build_phase2b_fixture(root)
            manifest = phase2b_manifest_from_dict(fixture["raw"])
            agent_spec = manifest.agents[0]
            assignment = assign_pairs(manifest.paired)[0]
            workspace = root / "workspace"
            workspace.mkdir()
            git(workspace, "init", "-q")
            agent_delegate = PolicyObservationProcessRunner(
                PHASE2B_RESOURCE_INVOCATION_POLICIES[0]
            )
            evaluator_delegate = PolicyObservationProcessRunner(
                PHASE2B_RESOURCE_INVOCATION_POLICIES[1],
                status=ExecutionStatus.FAILED,
                raised=KeyboardInterrupt(),
            )
            bound = _BubblewrapIsolatedAgentProcessRunner(
                agent_delegate,
                root / "home",
                workspace,
                agent_spec=agent_spec,
                credential_home=None,
                toolchain_home=root,
                evaluator_root=fixture["evaluator_root"],
                evaluator_native_helper=(
                    fixture["evaluator_root"] / "quality.py"
                ),
                expected_bubblewrap_sha256=hashlib.sha256(
                    BUBBLEWRAP_EXECUTABLE.read_bytes()
                ).hexdigest(),
                runtime_resolver=lambda _base, _executable: _AgentRuntime(
                    ("/phase2b-bin/agent",), ()
                ),
                evaluator_delegate=evaluator_delegate,
                require_resource_observation=True,
            )
            smoke = PairedSmokeRunner(
                manifest.paired,
                fixture["evaluator_root"] / "phase2b-manifest.json",
                fixture["source"],
                root / "unused-workspace-root",
                root / "control",
            )
            smoke._process_runner_for_attempt = (  # type: ignore[method-assign]
                lambda _spec, _workspace: bound
            )
            event_store = JsonlEventStore(root / "events.jsonl")
            recorder = LifecycleRecorder(event_store)
            real_record = recorder.record
            outcome_attempted = False

            def fail_terminal_outcome(event_type, **kwargs):
                nonlocal outcome_attempted
                if event_type is LifecycleEventType.OUTCOME_FINALIZED:
                    outcome_attempted = True
                    raise RuntimeError("synthetic durable recorder failure")
                return real_record(event_type, **kwargs)

            recorder.record = fail_terminal_outcome  # type: ignore[method-assign]
            started = monotonic()
            with self.assertRaises(KeyboardInterrupt):
                smoke._run_attempt(
                    recorder,
                    _agent_from_spec(agent_spec),
                    agent_spec,
                    manifest.tasks[0],
                    assignment,
                    workspace,
                    "c" * 64,
                    started,
                    started + 100,
                    0.0,
                )

            self.assertTrue(outcome_attempted)
            self.assertEqual(
                [event.event_type for event in event_store.read()],
                [
                    LifecycleEventType.SELECTION_MADE,
                    LifecycleEventType.EXECUTION_STARTED,
                    LifecycleEventType.EXECUTION_TERMINAL,
                ],
            )

    def test_evaluation_projection_interruption_finalizes_two_role_evidence(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = build_phase2b_fixture(root)
            manifest = phase2b_manifest_from_dict(fixture["raw"])
            agent_spec = manifest.agents[0]
            assignment = assign_pairs(manifest.paired)[0]
            workspace = root / "workspace"
            workspace.mkdir()
            git(workspace, "init", "-q")
            agent_delegate = PolicyObservationProcessRunner(
                PHASE2B_RESOURCE_INVOCATION_POLICIES[0]
            )
            evaluator_delegate = PolicyObservationProcessRunner(
                PHASE2B_RESOURCE_INVOCATION_POLICIES[1]
            )
            bound = _BubblewrapIsolatedAgentProcessRunner(
                agent_delegate,
                root / "home",
                workspace,
                agent_spec=agent_spec,
                credential_home=None,
                toolchain_home=root,
                evaluator_root=fixture["evaluator_root"],
                evaluator_native_helper=(
                    fixture["evaluator_root"] / "quality.py"
                ),
                expected_bubblewrap_sha256=hashlib.sha256(
                    BUBBLEWRAP_EXECUTABLE.read_bytes()
                ).hexdigest(),
                runtime_resolver=lambda _base, _executable: _AgentRuntime(
                    ("/phase2b-bin/agent",), ()
                ),
                evaluator_delegate=evaluator_delegate,
                require_resource_observation=True,
            )
            smoke = PairedSmokeRunner(
                manifest.paired,
                fixture["evaluator_root"] / "phase2b-manifest.json",
                fixture["source"],
                root / "unused-workspace-root",
                root / "control",
            )
            smoke._process_runner_for_attempt = (  # type: ignore[method-assign]
                lambda _spec, _workspace: bound
            )
            event_store = JsonlEventStore(root / "events.jsonl")
            recorder = LifecycleRecorder(event_store)
            started = monotonic()
            with (
                mock.patch(
                    "adaptive_orchestrator.experiments.paired_runner."
                    "evaluation_projection",
                    side_effect=KeyboardInterrupt(),
                ),
                self.assertRaises(KeyboardInterrupt),
            ):
                smoke._run_attempt(
                    recorder,
                    _agent_from_spec(agent_spec),
                    agent_spec,
                    manifest.tasks[0],
                    assignment,
                    workspace,
                    "c" * 64,
                    started,
                    started + 100,
                    0.0,
                )

            events = event_store.read()
            self.assertEqual(
                [event.event_type for event in events],
                [
                    LifecycleEventType.SELECTION_MADE,
                    LifecycleEventType.EXECUTION_STARTED,
                    LifecycleEventType.EXECUTION_TERMINAL,
                    LifecycleEventType.OUTCOME_FINALIZED,
                ],
            )
            outcome = events[-1]
            self.assertEqual(outcome.payload["status"], "evaluation_interrupted")
            self.assertEqual(outcome.payload["error_type"], "KeyboardInterrupt")
            invocations = outcome.payload["resource_observation"][
                "resource_supervisor_invocations"
            ]
            self.assertEqual(
                [item["invocation_name"] for item in invocations],
                ["agent", "evaluator"],
            )
            self.assertEqual(len(evaluator_delegate.calls), 1)

    def test_post_agent_budget_clock_interruption_finalizes_two_roles(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = build_phase2b_fixture(root)
            manifest = phase2b_manifest_from_dict(fixture["raw"])
            agent_spec = manifest.agents[0]
            assignment = assign_pairs(manifest.paired)[0]
            workspace = root / "workspace"
            workspace.mkdir()
            git(workspace, "init", "-q")
            agent_delegate = PolicyObservationProcessRunner(
                PHASE2B_RESOURCE_INVOCATION_POLICIES[0]
            )
            evaluator_delegate = PolicyObservationProcessRunner(
                PHASE2B_RESOURCE_INVOCATION_POLICIES[1]
            )
            bound = _BubblewrapIsolatedAgentProcessRunner(
                agent_delegate,
                root / "home",
                workspace,
                agent_spec=agent_spec,
                credential_home=None,
                toolchain_home=root,
                evaluator_root=fixture["evaluator_root"],
                evaluator_native_helper=(
                    fixture["evaluator_root"] / "quality.py"
                ),
                expected_bubblewrap_sha256=hashlib.sha256(
                    BUBBLEWRAP_EXECUTABLE.read_bytes()
                ).hexdigest(),
                runtime_resolver=lambda _base, _executable: _AgentRuntime(
                    ("/phase2b-bin/agent",), ()
                ),
                evaluator_delegate=evaluator_delegate,
                require_resource_observation=True,
            )
            smoke = PairedSmokeRunner(
                manifest.paired,
                fixture["evaluator_root"] / "phase2b-manifest.json",
                fixture["source"],
                root / "unused-workspace-root",
                root / "control",
            )
            smoke._process_runner_for_attempt = (  # type: ignore[method-assign]
                lambda _spec, _workspace: bound
            )
            clock_calls = 0

            def interrupt_second_clock() -> float:
                nonlocal clock_calls
                clock_calls += 1
                if clock_calls == 2:
                    raise KeyboardInterrupt()
                return 10.0

            smoke.clock = interrupt_second_clock
            event_store = JsonlEventStore(root / "events.jsonl")
            recorder = LifecycleRecorder(event_store)
            with self.assertRaises(KeyboardInterrupt):
                smoke._run_attempt(
                    recorder,
                    _agent_from_spec(agent_spec),
                    agent_spec,
                    manifest.tasks[0],
                    assignment,
                    workspace,
                    "c" * 64,
                    10.0,
                    110.0,
                    0.0,
                )

            events = event_store.read()
            self.assertEqual(
                [event.event_type for event in events],
                [
                    LifecycleEventType.SELECTION_MADE,
                    LifecycleEventType.EXECUTION_STARTED,
                    LifecycleEventType.EXECUTION_TERMINAL,
                    LifecycleEventType.OUTCOME_FINALIZED,
                ],
            )
            invocations = events[-1].payload["resource_observation"][
                "resource_supervisor_invocations"
            ]
            self.assertEqual(
                [item["invocation_name"] for item in invocations],
                ["agent", "evaluator"],
            )
            self.assertEqual(
                invocations[1]["reason"],
                "not-invoked-evaluator-budget-clock-interrupted",
            )
            self.assertEqual(evaluator_delegate.calls, [])

    def test_invalid_resource_role_or_policy_is_not_rewritten_as_not_invoked(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = build_phase2b_fixture(root)
            manifest = phase2b_manifest_from_dict(fixture["raw"])
            workspace = root / "workspace"
            workspace.mkdir()
            git(workspace, "init", "-q")
            expected_policy = PHASE2B_RESOURCE_INVOCATION_POLICIES[0]
            expected_hash = hashlib.sha256(
                json.dumps(
                    expected_policy.as_dict(),
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            for rendered, expected_reason in (
                (
                    {
                        "invocation_name": "evaluator",
                        "invocation_policy_sha256": expected_hash,
                    },
                    "invoked-resource-observation-role-mismatch",
                ),
                (
                    {
                        "invocation_name": "agent",
                        "invocation_policy_sha256": "0" * 64,
                    },
                    "invoked-resource-observation-policy-mismatch",
                ),
            ):
                with self.subTest(reason=expected_reason):
                    delegate = RecordingProcessRunner()
                    observation = mock.Mock()
                    observation.as_dict.return_value = rendered
                    delegate.last_observation = observation
                    bound = _BubblewrapIsolatedAgentProcessRunner(
                        delegate,
                        root / f"home-{expected_reason}",
                        workspace,
                        agent_spec=manifest.agents[0],
                        credential_home=None,
                        toolchain_home=root,
                        evaluator_root=fixture["evaluator_root"],
                        evaluator_native_helper=(
                            fixture["evaluator_root"] / "quality.py"
                        ),
                        expected_bubblewrap_sha256=hashlib.sha256(
                            BUBBLEWRAP_EXECUTABLE.read_bytes()
                        ).hexdigest(),
                        runtime_resolver=lambda _base, _executable: _AgentRuntime(
                            (), ()
                        ),
                    )
                    error = bound._capture_resource_observation(
                        "agent", delegate
                    )
                    self.assertIsNotNone(error)
                    bound.finalize_resource_observations(
                        "not-invoked-before-normal-finalization"
                    )
                    observations = bound.resource_observations()
                    self.assertEqual(
                        observations[0]["outcome_status"],
                        "observation-invalid",
                    )
                    self.assertEqual(observations[0]["reason"], expected_reason)
                    self.assertEqual(
                        observations[0]["invocation_policy_sha256"],
                        expected_hash,
                    )

    def test_paired_terminal_provider_falls_back_to_two_canonical_roles(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = build_phase2b_fixture(root)
            manifest = phase2b_manifest_from_dict(fixture["raw"])
            workspace = root / "workspace"
            workspace.mkdir()
            git(workspace, "init", "-q")
            bound = _BubblewrapIsolatedAgentProcessRunner(
                RecordingProcessRunner(),
                root / "home",
                workspace,
                agent_spec=manifest.agents[0],
                credential_home=None,
                toolchain_home=root,
                evaluator_root=fixture["evaluator_root"],
                evaluator_native_helper=fixture["evaluator_root"] / "quality.py",
                expected_bubblewrap_sha256=hashlib.sha256(
                    BUBBLEWRAP_EXECUTABLE.read_bytes()
                ).hexdigest(),
                runtime_resolver=lambda _base, _executable: _AgentRuntime((), ()),
            )

            def broken_observations():
                raise RuntimeError("synthetic renderer failure")

            bound.resource_observations = broken_observations  # type: ignore[method-assign]
            smoke = PairedSmokeRunner(
                manifest.paired,
                fixture["manifest_path"],
                fixture["source"],
                root / "unused-workspace-root",
                root / "control",
            )
            provider, fallback = smoke._terminal_outcome_payload_provider(bound)
            self.assertIsNotNone(provider)
            self.assertIsNotNone(fallback)
            assert provider is not None
            self.assertEqual(provider(), fallback)
            invocations = fallback["resource_observation"][
                "resource_supervisor_invocations"
            ]
            self.assertEqual(
                [item["invocation_name"] for item in invocations],
                ["agent", "evaluator"],
            )

    def test_runtime_closure_hashes_observed_content_and_rejects_post_hash_drift(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            claude = root / "claude"
            codex = root / "codex"
            toolchain = root / "toolchain"
            system = root / "system"
            enforcer = root / "enforcer.py"
            for path, value in (
                (claude, "claude-v1"),
                (codex, "codex-v1"),
                (toolchain, "toolchain-v1"),
                (system, "system-v1"),
                (enforcer, "enforcer-v1"),
            ):
                path.write_text(value)

            def resolver(base_id, _executable):
                source = claude if base_id == "claude-code" else codex
                return _AgentRuntime(
                    command_prefix=(f"/phase2b-bin/{base_id}",),
                    mounts=(_RuntimeMount(source, f"/runtime/{base_id}"),),
                )

            kernel_record = {
                "schema": "phase2b-kernel-security-capability-v2",
                "kernel": {"system": "Linux", "release": "test", "machine": "x86_64"},
                "landlock": {"status": "observed", "abi": 6, "syscall_number": 444},
                "bubblewrap_user_namespace_probe": {"status": "passed", "return_code": 0},
                "sysctls": {},
                "linux_security_modules": {},
                "seccomp": {},
                "runtime_primitives": {},
            }
            module = "adaptive_orchestrator.experiments.phase2b_runner"
            with (
                mock.patch(
                    f"{module}._optional_toolchain_mounts",
                    return_value=(_RuntimeMount(toolchain, "/toolchain"),),
                ),
                mock.patch(
                    f"{module}._system_runtime_mounts",
                    return_value=(_RuntimeMount(system, "/system"),),
                ),
                mock.patch(
                    f"{module}._isolation_enforcer_mounts",
                    return_value=(_RuntimeMount(enforcer, "enforcer:test"),),
                ),
                mock.patch(
                    f"{module}._kernel_security_capability_record",
                    return_value=kernel_record,
                ),
            ):
                closure = _resolve_runtime_closure(resolver, root)

            self.assertEqual(
                closure.observed_evidence["kernel_security_capability_record"],
                kernel_record,
            )
            self.assertEqual(
                closure.observed_evidence["kernel_security_capability_sha256"],
                hashlib.sha256(
                    json.dumps(
                        kernel_record, sort_keys=True, separators=(",", ":")
                    ).encode()
                ).hexdigest(),
            )
            self.assertRegex(
                str(closure.observed_evidence["isolation_enforcer_inventory_sha256"]),
                r"^[0-9a-f]{64}$",
            )
            self.assertEqual(
                _runtime_metadata_sha256(closure.metadata_mounts),
                closure.attested_metadata_sha256,
            )
            self.assertEqual(
                closure.observed_evidence["runtime_closure_metadata_sha256"],
                closure.attested_metadata_sha256,
            )
            enforcer.write_text("enforcer-v2")
            self.assertNotEqual(
                _runtime_metadata_sha256(closure.metadata_mounts),
                closure.attested_metadata_sha256,
            )
            runner = object.__new__(Phase2bPilotRunner)
            runner._runtime_closure = closure
            with self.assertRaisesRegex(
                Phase2bExecutionError, "changed after content attestation"
            ):
                runner._checked_runtime_metadata_sha256()

    def test_real_claude_bwrap_wrapper_forces_proc_free_seccomp_boundary_without_model(
        self,
    ) -> None:
        if os.name != "posix" or not BUBBLEWRAP_EXECUTABLE.is_file():
            self.skipTest("Claude bubblewrap wrapper probe requires bubblewrap")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            git(workspace, "init", "-q")
            trusted_home = root / "trusted-home"
            trusted_home.mkdir()
            (trusted_home / "credential-secret").write_text("must-not-be-visible\n")
            toolchain_mounts = _optional_toolchain_mounts(Path.home())
            mounted_targets = {mount.target for mount in toolchain_mounts}
            toolchain_checks: list[str] = []
            if "/phase2b-runtime/node/bin/node" in mounted_targets:
                toolchain_checks.extend((
                    "test \"$(command -v node)\" = /phase2b-runtime/node/bin/node",
                    "node --version >/dev/null",
                ))
            if "/phase2b-runtime/node/lib/node_modules/npm" in mounted_targets:
                toolchain_checks.extend((
                    "test \"$(command -v npm)\" = /phase2b-runtime/node/bin/npm",
                    "npm --version >/dev/null",
                    "test \"$(command -v npx)\" = /phase2b-runtime/node/bin/npx",
                    "npx --version >/dev/null",
                ))
            if "/phase2b-runtime/go" in mounted_targets:
                toolchain_checks.extend((
                    "test \"$(command -v go)\" = /phase2b-runtime/go/bin/go",
                    "go version >/dev/null",
                ))
            if "/phase2b-runtime/rust-toolchain" in mounted_targets:
                toolchain_checks.extend((
                    "test \"$(command -v cargo)\" = /phase2b-runtime/rust-toolchain/bin/cargo",
                    "cargo --version >/dev/null",
                    "test \"$(command -v rustc)\" = /phase2b-runtime/rust-toolchain/bin/rustc",
                    "rustc --version >/dev/null",
                ))
            probe = workspace / "probe.sh"
            probe.write_text(
                "#!/bin/sh\n"
                "set -eu\n"
                "test ! -e /proc/self/mountinfo\n"
                "test ! -e /proc/1/cmdline\n"
                "if printf bad >/proc/hidden-write 2>/dev/null; then exit 61; fi\n"
                "test ! -e /tmp/srt-hidden-overlay\n"
                "ln -s /proc/self/mountinfo /workspace/claude-proc-link\n"
                "test ! -r /workspace/claude-proc-link\n"
                "if cat /agent-home/credential-secret >/dev/null 2>&1; then exit 56; fi\n"
                "if printf bad >/agent-home/model-write 2>/dev/null; then exit 57; fi\n"
                "if printf bad >/flood 2>/dev/null; then exit 58; fi\n"
                "if printf bad >/run/flood 2>/dev/null; then exit 59; fi\n"
                "if [ -d /dev/shm ] && printf bad >/dev/shm/flood 2>/dev/null; then exit 60; fi\n"
                "printf tmp-ok >/tmp/accounted-write\n"
                "printf workspace-ok >/workspace/accounted-write\n"
                "if bwrap --unshare-all --proc /proc -- /bin/true >/dev/null 2>&1; then exit 51; fi\n"
                "if unshare --mount /bin/true >/dev/null 2>&1; then exit 52; fi\n"
                "if python3 -c \"import socket; socket.socketpair()\" >/dev/null 2>&1; then exit 55; fi\n"
                "python3 -c \"import socket; s=socket.socket(socket.AF_INET); assert s.connect_ex(('198.51.100.1', 9)) != 0\"\n"
                "node -e \"const n=require('net'),s=n.createServer();s.once('error',e=>process.exit(e.code==='EPERM'?0:53));s.listen('/tmp/phase2b.sock',()=>process.exit(54))\"\n"
                "/bin/sh -c true\n"
                "node -e \"require('child_process').spawnSync('/bin/true')\"\n"
                + "".join(f"{line}\n" for line in toolchain_checks)
                + "printf claude-proc-boundary-ok\n"
            )
            probe.chmod(0o700)
            srt_command = [
                str(_CLAUDE_BWRAP_WRAPPER),
                "--die-with-parent",
                "--new-session",
                "--unshare-user",
                "--unshare-pid",
                "--unshare-ipc",
                "--unshare-uts",
                "--unshare-cgroup",
                "--unshare-net",
                "--cap-drop",
                "ALL",
                "--hostname",
                "phase2b",
                "--dev",
                "/dev",
                "--proc",
                "/proc",
                "--tmpfs",
                "/tmp",
                "--dir",
                "/tmp/srt-hidden-overlay",
                "--tmpfs",
                "/tmp/srt-hidden-overlay",
                "--dir",
                "/etc",
                "--dir",
                "/run",
                "--bind",
                str(trusted_home),
                "/agent-home",
            ]
            for system_path in ("/usr", "/bin", "/sbin", "/lib", "/lib64"):
                if Path(system_path).exists():
                    srt_command.extend(("--ro-bind", system_path, system_path))
            srt_command.extend((
                "--bind",
                str(workspace),
                "/workspace",
                "--ro-bind",
                str(workspace / ".git"),
                "/workspace/.git",
                "--chdir",
                "/workspace",
                "--",
                "bash",
                "-c",
                "exec /workspace/probe.sh",
            ))
            command = [
                str(BUBBLEWRAP_EXECUTABLE),
                "--die-with-parent",
                "--new-session",
                "--unshare-all",
                "--clearenv",
                "--dev",
                "/dev",
                "--proc",
                "/proc",
                "--tmpfs",
                "/tmp",
                "--dir",
                "/run",
                "--dir",
                "/phase2b-runtime",
                "--dir",
                "/phase2b-runtime/node",
                "--dir",
                "/phase2b-runtime/node/bin",
                "--dir",
                "/phase2b-runtime/node/lib",
                "--dir",
                "/phase2b-runtime/node/lib/node_modules",
                "--ro-bind",
                "/etc",
                "/etc",
            ]
            for system_path in ("/usr", "/bin", "/sbin", "/lib", "/lib64"):
                if Path(system_path).exists():
                    command.extend(("--ro-bind", system_path, system_path))
            for mount in toolchain_mounts:
                command.extend(("--ro-bind", str(mount.source), mount.target))
            command.extend((
                "--bind",
                str(workspace),
                "/workspace",
                "--ro-bind",
                str(workspace / ".git"),
                "/workspace/.git",
                "--bind",
                str(trusted_home),
                "/agent-home",
                "--ro-bind",
                str(_CLAUDE_BWRAP_WRAPPER),
                "/phase2b-claude-wrapper",
                "--remount-ro",
                "/",
                "--remount-ro",
                "/dev",
                "--chdir",
                "/workspace",
                "--",
                "/phase2b-claude-wrapper",
                *srt_command[1:],
            ))
            result = SubprocessRunner().run(command, workspace, 10)
            self.assertEqual(
                result.status,
                ExecutionStatus.COMPLETED,
                f"exit={result.exit_code} stderr={result.stderr!r}",
            )
            self.assertEqual(result.stdout, "claude-proc-boundary-ok")

            flood = workspace / "flood.sh"
            flood.write_text(
                "#!/bin/sh\n"
                "set -eu\n"
                "mkdir -p /tmp/srt-hidden-overlay\n"
                "dd if=/dev/zero of=/tmp/srt-hidden-overlay/flood "
                "bs=1048576 count=2 status=none\n"
            )
            flood.chmod(0o700)
            flood_command = list(command)
            flood_command[-1] = "exec /workspace/flood.sh"
            base_policy = PHASE2B_RESOURCE_INVOCATION_POLICIES[0]
            assert base_policy.namespace_tmp_policy is not None
            tiny_policy = replace(
                base_policy,
                namespace_tmp_policy=replace(
                    base_policy.namespace_tmp_policy,
                    max_allocated_byte_growth=64 * 1024,
                    max_file_count_growth=32,
                ),
            )
            supervised = SupervisedProcessRunner(
                (tiny_policy,),
                {"workspace": workspace, "agent-home": trusted_home},
            )
            flood_result = supervised.run(flood_command, workspace, 10)
            self.assertEqual(flood_result.status, ExecutionStatus.FAILED)
            self.assertIn("namespace-tmp", flood_result.stderr)
            self.assertTrue(
                supervised.last_observation.final_usage_scan_completed
            )

            benign = list(command)
            benign[-1] = "test ! -e /workspace/proxy.py; exec /bin/true"
            benign_result = SubprocessRunner().run(benign, workspace, 5)
            self.assertEqual(
                benign_result.status,
                ExecutionStatus.COMPLETED,
                benign_result.stderr,
            )

            rejected = SubprocessRunner().run(
                (
                    str(_CLAUDE_BWRAP_WRAPPER),
                    "--die-with-parent",
                    "--new-session",
                    "--unshare-user",
                    "--unshare-pid",
                    "--unshare-net",
                    "--cap-drop",
                    "ALL",
                    "--proc",
                    "/proc",
                    "--tmpfs",
                    "/tmp",
                    "--",
                    "bash",
                    "-c",
                    "ARGV0=apply-seccomp; exec /bin/true",
                ),
                workspace,
                5,
            )
            self.assertEqual(rejected.status, ExecutionStatus.FAILED)
            self.assertIn("seccomp/proxy helper", rejected.stderr)

            newline = list(command)
            newline[-1] = "exec /bin/true\nprintf impossible"
            newline_result = SubprocessRunner().run(newline, workspace, 5)
            self.assertEqual(newline_result.status, ExecutionStatus.FAILED)
            self.assertIn("contains a newline", newline_result.stderr)

    def test_real_codex_permission_profile_exposes_mounted_toolchains_without_model(
        self,
    ) -> None:
        if (
            os.name != "posix"
            or not BUBBLEWRAP_EXECUTABLE.is_file()
            or shutil.which("codex") is None
        ):
            self.skipTest("Codex/bubblewrap sandbox probe is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = build_phase2b_fixture(root)
            manifest = phase2b_manifest_from_dict(fixture["raw"])
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "tracked.txt").write_text("tracked\n")
            git(workspace, "init", "-q")
            git(workspace, "add", "tracked.txt")
            git(
                workspace,
                "-c", "user.name=Test", "-c", "user.email=test@example.com",
                "commit", "-qm", "base",
            )
            credential_home = root / "credential-home"
            credential_home.mkdir(mode=0o700)
            credential = credential_home / ".codex" / "auth.json"
            credential.parent.mkdir(mode=0o700)
            credential.write_text('{"sentinel":"must-stay-private"}\n')
            credential.chmod(0o600)

            mounted_targets = {
                mount.target for mount in _optional_toolchain_mounts(Path.home())
            }
            probe_lines = [
                "#!/bin/sh",
                "set -eu",
                "test \"$(command -v node)\" = /phase2b-runtime/node/bin/node",
                "node --version >/dev/null",
                "test \"$(command -v npm)\" = /phase2b-runtime/node/bin/npm",
                "npm --version >/dev/null",
                "test \"$(command -v npx)\" = /phase2b-runtime/node/bin/npx",
                "npx --version >/dev/null",
                "test ! -e /phase2b-runtime/node/bin/codex",
                "test ! -e /phase2b-runtime/node/lib/node_modules/@openai/codex",
                "test ! -r /phase2b-runtime/codex/package.json",
                "if cat /proc/self/mountinfo >/dev/null 2>&1; then exit 31; fi",
                "if cat /proc/1/cmdline >/dev/null 2>&1; then exit 32; fi",
                "ln -s /proc/self/mountinfo /workspace/proc-mountinfo-link",
                "if cat /workspace/proc-mountinfo-link >/dev/null 2>&1; then exit 33; fi",
                "if bwrap --unshare-all --proc /proc -- /bin/true >/dev/null 2>&1; then exit 43; fi",
                "if cat /agent-home/.codex/auth.json >/dev/null 2>&1; then exit 34; fi",
                "if printf bad >>/agent-home/.codex/auth.json 2>/dev/null; then exit 35; fi",
                "if cat /agent-home/model-visible.txt >/dev/null 2>&1; then exit 44; fi",
                "if printf bad > /agent-home/model-write.txt 2>/dev/null; then exit 45; fi",
                "if printf bad > /flood 2>/dev/null; then exit 46; fi",
                "if printf bad > /run/flood 2>/dev/null; then exit 47; fi",
                "if [ -d /dev/shm ] && printf bad > /dev/shm/flood 2>/dev/null; then exit 48; fi",
                "printf ok > /tmp/accounted-write",
                "printf ok > /workspace/tool-write.txt",
                "test -r /workspace/.git/HEAD",
                "if printf bad > /workspace/.git/must-not-write 2>/dev/null; then exit 36; fi",
                "node -e \"const n=require('net'),s=n.createServer();s.once('error',e=>process.exit(e.code==='EPERM'?0:41));s.listen(0,'127.0.0.1',()=>process.exit(42))\"",
            ]
            if "/phase2b-runtime/go" in mounted_targets:
                probe_lines.extend((
                    "test \"$(command -v go)\" = /phase2b-runtime/go/bin/go",
                    "go version >/dev/null",
                ))
            if "/phase2b-runtime/rust-toolchain" in mounted_targets:
                probe_lines.extend((
                    "test \"$(command -v cargo)\" = /phase2b-runtime/rust-toolchain/bin/cargo",
                    "cargo --version >/dev/null",
                    "test \"$(command -v rustc)\" = /phase2b-runtime/rust-toolchain/bin/rustc",
                    "rustc --version >/dev/null",
                ))
            probe_lines.append("printf codex-inner-profile-ok")
            probe = workspace / "probe.sh"
            probe.write_text("\n".join(probe_lines) + "\n")
            probe.chmod(0o700)

            isolated = _BubblewrapIsolatedAgentProcessRunner(
                SubprocessRunner(),
                root / "isolated-home",
                workspace,
                agent_spec=next(
                    spec for spec in manifest.agents if spec.base_id == "codex"
                ),
                credential_home=credential_home,
                toolchain_home=Path.home(),
                evaluator_root=fixture["evaluator_root"],
                evaluator_native_helper=next(
                    mount.source
                    for mount in _resolve_agent_runtime("codex", "codex").mounts
                    if mount.target.endswith("/codex-linux-sandbox")
                    and "native-helper" in mount.target
                ),
                expected_bubblewrap_sha256=str(
                    manifest.agent_execution_isolation[
                        "bubblewrap_binary_sha256"
                    ]
                ),
                runtime_resolver=_resolve_agent_runtime,
            )
            isolated._validate_bubblewrap()
            credential_source, credential_target = isolated._prepare_home()
            (isolated._home / "model-visible.txt").write_text("must stay core-only\n")
            try:
                runtime = _resolve_agent_runtime("codex", "codex")
                sandbox_command = (
                    *runtime.command_prefix,
                    "sandbox",
                    *_codex_isolation_config_arguments(),
                    "--permission-profile",
                    "phase2b-isolated",
                    "--cd",
                    "/workspace",
                    "--",
                    "/workspace/probe.sh",
                )
                outer = isolated._bubblewrap_command(
                    sandbox_command,
                    runtime,
                    credential_source=credential_source,
                    credential_target=credential_target,
                )
                result = SubprocessRunner().run(outer, workspace, 30)
            finally:
                credential_error = isolated._finalize_credential_lease()
                cleanup_error = isolated._clear_home()

            self.assertIsNone(credential_error)
            self.assertIsNone(cleanup_error)
            self.assertEqual(
                result.status,
                ExecutionStatus.COMPLETED,
                f"exit={result.exit_code} stdout={result.stdout!r} stderr={result.stderr!r}",
            )
            self.assertEqual(result.stdout, "codex-inner-profile-ok")
            self.assertEqual(
                credential.read_text(), '{"sentinel":"must-stay-private"}\n'
            )
            self.assertEqual((workspace / "tool-write.txt").read_text(), "ok")
            self.assertFalse((workspace / ".git" / "must-not-write").exists())

    def test_real_codex_exec_help_parses_isolated_command_without_model(self) -> None:
        if (
            os.name != "posix"
            or not BUBBLEWRAP_EXECUTABLE.is_file()
            or shutil.which("codex") is None
        ):
            self.skipTest("Codex/bubblewrap parse probe is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = build_phase2b_fixture(root)
            manifest = phase2b_manifest_from_dict(fixture["raw"])
            codex_spec = next(
                spec for spec in manifest.agents if spec.base_id == "codex"
            )
            workspace_root = root / "workspaces"
            workspace = workspace_root / "task-01" / codex_spec.agent_id
            workspace.mkdir(parents=True)
            git(workspace, "init", "-q")
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
                process_runner_factory=SubprocessRunner,
                resource_supervisor_factory=(
                    lambda _policies, _roots: SubprocessRunner()
                ),
                version_resolver=lambda spec: spec.cli_version,
                _test_only_allow_enforcement_injection=True,
            )
            bound = runner._process_runner_for_attempt(codex_spec, workspace)
            self.assertIsInstance(bound, _BubblewrapIsolatedAgentProcessRunner)
            bound._validate_bubblewrap()
            credential_source, credential_target = bound._prepare_home()
            try:
                runtime = _resolve_agent_runtime("codex", "codex")
                exact = exact_agent_command(codex_spec, workspace, "safe prompt")
                isolated = bound._isolated_agent_command(exact, runtime)
                help_command = (*isolated[:-1], "--help")
                outer = bound._bubblewrap_command(
                    help_command,
                    runtime,
                    credential_source=credential_source,
                    credential_target=credential_target,
                )
                result = SubprocessRunner().run(outer, workspace, 10)
            finally:
                credential_error = bound._finalize_credential_lease()
                cleanup_error = bound._clear_home()
            self.assertIsNone(credential_error)
            self.assertIsNone(cleanup_error)
            self.assertEqual(result.status, ExecutionStatus.COMPLETED, result.stderr)
            self.assertIn("Run Codex non-interactively", result.stdout)

    def test_environment_rejects_bubblewrap_binary_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = build_phase2b_fixture(root)
            raw = copy.deepcopy(fixture["raw"])
            raw["environment"]["agent_execution_isolation"][
                "bubblewrap_binary_sha256"
            ] = "0" * 64
            fixture["manifest_path"].write_text(json.dumps(raw, indent=2) + "\n")
            manifest = phase2b_manifest_from_dict(raw)
            with self.assertRaisesRegex(Phase2bPilotError, "binary hash changed"):
                validate_phase2b_environment(
                    manifest,
                    fixture["manifest_path"],
                    {"repo-1": fixture["source"]},
                    fixture["evaluator_root"],
                    fixture["inventory"],
                )

    def test_real_bubblewrap_namespace_hides_host_and_protects_git_metadata(self) -> None:
        if os.name != "posix" or not BUBBLEWRAP_EXECUTABLE.is_file():
            self.skipTest("bubblewrap smoke test requires a POSIX bubblewrap host")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = build_phase2b_fixture(root)
            manifest = phase2b_manifest_from_dict(fixture["raw"])
            workspace_root = root / "workspaces"
            workspace = workspace_root / "task-01" / manifest.agents[0].agent_id
            workspace.mkdir(parents=True)
            (workspace / "tracked.txt").write_text("visible attempt input\n")
            git(workspace, "init", "-q")
            git(workspace, "add", "tracked.txt")
            git(
                workspace,
                "-c", "user.name=Test", "-c", "user.email=test@example.com",
                "commit", "-qm", "isolated base",
            )

            sibling = workspace_root / "sibling-attempt" / "private-marker"
            sibling.parent.mkdir(parents=True)
            sibling.write_text("must stay hidden\n")
            control_marker = root / "control" / "private-marker"
            control_marker.parent.mkdir(parents=True)
            control_marker.write_text("must stay hidden\n")
            source_marker = fixture["source"] / "fixture.txt"
            host_tmp_marker = root / "host-tmp-marker"
            host_tmp_marker.write_text("host tmp must stay hidden\n")
            hidden_paths = [
                str(sibling),
                str(control_marker),
                str(source_marker),
                str(host_tmp_marker),
                str(workspace),
            ]

            fake_agent = root / "fake-claude"
            fake_agent.write_text(
                "#!/usr/bin/python3\n"
                "import json, os, sys\n"
                f"hidden = {json.dumps(hidden_paths)}\n"
                "assert os.getcwd() == '/workspace'\n"
                "assert sys.stdin.read() == ''\n"
                "assert os.environ.get('PHASE2B_SECRET_SENTINEL') is None\n"
                "assert all(not os.path.exists(path) for path in hidden)\n"
                "assert open('/workspace/.git/HEAD', encoding='utf-8').read().strip()\n"
                "open('/workspace/agent-write.txt', 'w', encoding='utf-8').write('ok\\n')\n"
                "try:\n"
                "    open('/workspace/.git/must-not-write', 'w').write('bad')\n"
                "except OSError:\n"
                "    pass\n"
                "else:\n"
                "    raise AssertionError('Git metadata was writable')\n"
                "print(json.dumps({'isolated': True}))\n"
            )
            fake_agent.chmod(0o700)
            evaluator_probe = fixture["evaluator_root"] / "namespace-probe.py"
            evaluator_probe.write_text(
                "import json, os, socket, subprocess, sys\n"
                f"hidden = {json.dumps([*hidden_paths, str(evaluator_probe), str(Path.home() / '.codex' / 'auth.json'), str(Path.home() / '.claude' / '.credentials.json')])}\n"
                "assert os.getcwd() == '/workspace'\n"
                "assert sys.stdin.read() == ''\n"
                "assert os.environ.get('PHASE2B_SECRET_SENTINEL') is None\n"
                "assert os.environ['HOME'] == '/evaluator-home'\n"
                "assert os.listdir('/evaluator-home') == []\n"
                "open('/evaluator-home/cache', 'w', encoding='utf-8').write('ephemeral')\n"
                "assert socket.gethostname() == 'phase2b-evaluator'\n"
                "assert all(not os.path.exists(path) for path in hidden)\n"
                "assert not os.path.exists('/proc/self/mountinfo')\n"
                "assert not os.path.exists('/proc/1/cmdline')\n"
                "assert not os.path.exists('/etc/passwd')\n"
                "assert not os.path.exists('/etc/group')\n"
                "assert not os.path.exists('/etc/hosts')\n"
                "assert open('/workspace/.git/HEAD', encoding='utf-8').read().strip()\n"
                "open('/workspace/evaluator-write.txt', 'w', encoding='utf-8').write('ok\\n')\n"
                "try:\n"
                "    open('/workspace/.git/evaluator-must-not-write', 'w').write('bad')\n"
                "except OSError:\n"
                "    pass\n"
                "else:\n"
                "    raise AssertionError('evaluator could write Git metadata')\n"
                "assert subprocess.run(['bwrap', '--unshare-all', '--proc', '/proc', '--', '/bin/true'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0\n"
                "try:\n"
                "    probe = socket.socket()\n"
                "except PermissionError:\n"
                "    pass\n"
                "else:\n"
                "    probe.settimeout(0.2)\n"
                "    assert probe.connect_ex(('198.51.100.1', 9)) != 0\n"
                "print(json.dumps({'evaluator_isolated': True}))\n"
            )
            evaluator_probe.chmod(0o444)

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
                process_runner_factory=SubprocessRunner,
                resource_supervisor_factory=(
                    lambda _policies, _roots: SubprocessRunner()
                ),
                version_resolver=lambda spec: spec.cli_version,
                runtime_resolver=lambda _base, _executable: _AgentRuntime(
                    command_prefix=("/phase2b-bin/fake-claude",),
                    mounts=(
                        _RuntimeMount(fake_agent, "/phase2b-bin/fake-claude"),
                    ),
                ),
                _test_only_allow_enforcement_injection=True,
            )
            previous = os.environ.get("PHASE2B_SECRET_SENTINEL")
            os.environ["PHASE2B_SECRET_SENTINEL"] = "must-not-cross-clearenv"
            try:
                bound = runner._process_runner_for_attempt(
                    manifest.agents[0], workspace
                )
                result = bound.run(
                    exact_agent_command(manifest.agents[0], workspace, "ignored"),
                    workspace,
                    10,
                )
                evaluator_result = bound.run(
                    ("python3", str(evaluator_probe)), workspace, 10
                )
            finally:
                if previous is None:
                    os.environ.pop("PHASE2B_SECRET_SENTINEL", None)
                else:
                    os.environ["PHASE2B_SECRET_SENTINEL"] = previous

            self.assertEqual(result.status, ExecutionStatus.COMPLETED, result.stderr)
            self.assertEqual(json.loads(result.stdout), {"isolated": True})
            self.assertEqual(
                evaluator_result.status,
                ExecutionStatus.COMPLETED,
                evaluator_result.stderr,
            )
            self.assertEqual(
                json.loads(evaluator_result.stdout),
                {"evaluator_isolated": True},
            )
            self.assertEqual((workspace / "agent-write.txt").read_text(), "ok\n")
            self.assertEqual(
                (workspace / "evaluator-write.txt").read_text(), "ok\n"
            )
            self.assertFalse((workspace / ".git" / "must-not-write").exists())
            self.assertFalse(
                (workspace / ".git" / "evaluator-must-not-write").exists()
            )
            self.assertEqual(tuple(bound._home.iterdir()), ())

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
            credential_home.mkdir(mode=0o700)
            for relative in ISOLATED_AGENT_CREDENTIAL_PATHS.values():
                credential = credential_home / relative
                credential.parent.mkdir(mode=0o700, exist_ok=True)
                credential.write_text('{"credential":"fixture"}\n')
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
                resource_supervisor_factory=lambda _policies, _roots: delegate,
                version_resolver=lambda spec: spec.cli_version,
                credential_home=credential_home,
                _test_only_allow_enforcement_injection=True,
            )

            claude_spec, codex_spec = manifest.agents
            claude_workspace = workspace_root / "task-01" / claude_spec.agent_id
            codex_workspace = workspace_root / "task-01" / codex_spec.agent_id
            claude_workspace.mkdir(parents=True)
            codex_workspace.mkdir(parents=True)
            git(claude_workspace, "init", "-q")
            git(codex_workspace, "init", "-q")
            claude_bound = runner._process_runner_for_attempt(claude_spec, claude_workspace)
            codex_bound = runner._process_runner_for_attempt(codex_spec, codex_workspace)
            claude_result = claude_bound.run(
                exact_agent_command(claude_spec, claude_workspace),
                claude_workspace,
                1,
            )
            codex_result = codex_bound.run(
                exact_agent_command(codex_spec, codex_workspace),
                codex_workspace,
                1,
            )

            self.assertEqual(
                claude_result.status, ExecutionStatus.COMPLETED, claude_result.stderr
            )
            self.assertEqual(
                codex_result.status, ExecutionStatus.COMPLETED, codex_result.stderr
            )
            self.assertEqual(len(delegate.environments), 2)
            for observed, removed, initial_entries in delegate.environments:
                self.assertEqual(
                    set(observed),
                    set(
                        PHASE2B_AGENT_EXECUTION_ISOLATION_POLICY["environment"][
                            "allowlist"
                        ]
                    ),
                )
                self.assertEqual(removed, ("--clearenv",))
                credential_files = [path for path in initial_entries if not path[2]]
                self.assertEqual(len(credential_files), 1)
                self.assertFalse(credential_files[0][1])
            claude_bwrap = delegate.calls[0][0]
            codex_bwrap = delegate.calls[1][0]
            for outer in (claude_bwrap, codex_bwrap):
                self.assertEqual(outer[0], str(BUBBLEWRAP_EXECUTABLE))
                self.assertIn("--clearenv", outer)
                self.assertIn("--unshare-all", outer)
                self.assertIn("--share-net", outer)
                self.assertIn("--tmpfs", outer)
            claude_agent = claude_bwrap[claude_bwrap.index("--") + 1:]
            codex_agent = codex_bwrap[codex_bwrap.index("--") + 1:]
            self.assertIn("--safe-mode", claude_agent)
            self.assertIn("--restricted", claude_agent)
            self.assertIn("--no-session-persistence", claude_agent)
            self.assertEqual(
                claude_agent[claude_agent.index("--permission-prompts") + 1],
                "none",
            )
            self.assertIn("--strict-mcp-config", claude_agent)
            self.assertEqual(
                json.loads(claude_agent[claude_agent.index("--mcp-config") + 1]),
                {"mcpServers": {}},
            )
            claude_settings = json.loads(
                claude_agent[claude_agent.index("--settings") + 1]
            )
            self.assertTrue(claude_settings["sandbox"]["enabled"])
            self.assertEqual(
                claude_settings["sandbox"]["bwrapPath"],
                "/phase2b-helper-bin/phase2b-claude-bwrap",
            )
            self.assertTrue(claude_settings["sandbox"]["failIfUnavailable"])
            self.assertFalse(
                claude_settings["sandbox"]["allowUnsandboxedCommands"]
            )
            self.assertEqual(
                claude_settings["sandbox"]["network"]["allowedDomains"], []
            )
            self.assertTrue(
                claude_settings["sandbox"]["network"]["strictAllowlist"]
            )
            self.assertTrue(
                claude_settings["sandbox"]["network"]["allowAllUnixSockets"]
            )
            self.assertIn(
                "/agent-home",
                claude_settings["sandbox"]["filesystem"]["denyRead"],
            )
            self.assertIn(
                "/agent-home",
                claude_settings["sandbox"]["filesystem"]["denyWrite"],
            )
            self.assertIn(
                "/proc",
                claude_settings["sandbox"]["filesystem"]["denyRead"],
            )
            self.assertIn(
                "/proc",
                claude_settings["sandbox"]["filesystem"]["denyWrite"],
            )
            self.assertIn(
                "/phase2b-runtime/node",
                claude_settings["sandbox"]["filesystem"]["denyRead"],
            )
            self.assertEqual(
                claude_settings["sandbox"]["filesystem"]["allowRead"],
                [
                    "/phase2b-runtime/node/bin/node",
                    "/phase2b-runtime/node/bin/npm",
                    "/phase2b-runtime/node/bin/npx",
                    "/phase2b-runtime/node/lib/node_modules/npm",
                ],
            )
            self.assertIn(
                "Read(//proc/**)", claude_settings["permissions"]["deny"]
            )
            self.assertIn(
                "Edit(//agent-home/**)",
                claude_settings["permissions"]["deny"],
            )
            self.assertNotIn(
                "Write(//agent-home/**)",
                claude_settings["permissions"]["deny"],
            )
            self.assertEqual(
                claude_agent[claude_agent.index("--disallowedTools") + 1],
                "WebFetch,WebSearch,Agent",
            )
            self.assertIn("exec", codex_agent)
            self.assertNotIn("--sandbox", codex_agent)
            self.assertIn("--ignore-user-config", codex_agent)
            self.assertIn("--ignore-rules", codex_agent)
            self.assertIn("--ephemeral", codex_agent)
            self.assertIn("--strict-config", codex_agent)
            self.assertNotIn("--ask-for-approval", codex_agent)
            codex_config = {
                codex_agent[index + 1]
                for index, token in enumerate(codex_agent)
                if token == "-c"
            }
            self.assertIn('default_permissions="phase2b-isolated"', codex_config)
            permission_profile = next(
                value for value in codex_config if value.startswith("permissions={")
            )
            self.assertIn('":root"="deny"', permission_profile)
            self.assertIn('":minimal"="read"', permission_profile)
            self.assertIn('":workspace_roots"={"."="write"}', permission_profile)
            self.assertIn('"/tmp"="write"', permission_profile)
            self.assertIn(
                '"/phase2b-native-helper"="read"', permission_profile
            )
            self.assertIn(
                '"/agent-home"="deny"', permission_profile
            )
            self.assertIn(
                '"/phase2b-runtime/node"="read"', permission_profile
            )
            for node_path in (
                "bin/node",
                "bin/npm",
                "bin/npx",
                "lib/node_modules/npm",
            ):
                self.assertIn(
                    f'"/phase2b-runtime/node/{node_path}"="read"',
                    permission_profile,
                )
            self.assertIn(
                '"/phase2b-runtime/node/bin"="read"', permission_profile
            )
            for toolchain in ("go", "cargo", "rustup", "rust-toolchain"):
                self.assertIn(
                    f'"/phase2b-runtime/{toolchain}"="read"',
                    permission_profile,
                )
            self.assertIn(
                '"/phase2b-runtime/codex"="deny"', permission_profile
            )
            self.assertIn("network={enabled=false}", permission_profile)
            self.assertIn('shell_environment_policy.inherit="none"', codex_config)
            self.assertIn('approval_policy="never"', codex_config)
            self.assertIn('web_search="disabled"', codex_config)
            self.assertIn("tools.web_search=false", codex_config)
            self.assertIn("features.apps=false", codex_config)

            for outer, exact_workspace in (
                (claude_bwrap, claude_workspace),
                (codex_bwrap, codex_workspace),
            ):
                mounts = [
                    (outer[index + 1], outer[index + 2])
                    for index, token in enumerate(outer)
                    if token in {"--bind", "--ro-bind"}
                ]
                self.assertIn((str(exact_workspace), "/workspace"), mounts)
                self.assertIn(
                    (str(exact_workspace / ".git"), "/workspace/.git"),
                    mounts,
                )
                self.assertNotIn(str(workspace_root), {source for source, _ in mounts})
                targets = {target for _, target in mounts}
                self.assertNotIn(str(fixture["source"]), targets)
                self.assertNotIn(str(fixture["evaluator_root"]), targets)
                self.assertNotIn(str(root / "control"), targets)
                self.assertNotIn(str(workspace_root), targets)
                self.assertNotIn("/etc/passwd", targets)
                self.assertNotIn("/etc/group", targets)
                self.assertNotIn("/etc/hosts", targets)
                self.assertNotIn("/phase2b-runtime/node", targets)
                self.assertIn("/phase2b-runtime/node/bin/node", targets)

            for outer in (claude_bwrap, codex_bwrap):
                home_source = next(
                    Path(outer[index + 1])
                    for index, token in enumerate(outer)
                    if token == "--bind" and outer[index + 2] == "/agent-home"
                )
                self.assertEqual(tuple(home_source.iterdir()), ())
            for relative in ISOLATED_AGENT_CREDENTIAL_PATHS.values():
                self.assertEqual(
                    (credential_home / relative).read_text(),
                    '{"credential":"fixture"}\n',
                )
            for outer, spec in (
                (claude_bwrap, claude_spec),
                (codex_bwrap, codex_spec),
            ):
                credential_source = str(
                    credential_home / ISOLATED_AGENT_CREDENTIAL_PATHS[spec.base_id]
                )
                self.assertNotIn(credential_source, outer)

            consumed_home = next(
                Path(claude_bwrap[index + 1])
                for index, token in enumerate(claude_bwrap)
                if token == "--bind" and claude_bwrap[index + 2] == "/agent-home"
            )
            marker = consumed_home / "owned-marker"
            marker.write_text("preserve pre-existing control evidence\n")
            collision = runner._process_runner_for_attempt(
                claude_spec, claude_workspace
            ).run(
                exact_agent_command(claude_spec, claude_workspace),
                claude_workspace,
                1,
            )
            self.assertEqual(collision.status, ExecutionStatus.SPAWN_ERROR)
            self.assertIn("bubblewrap-isolated agent invocation", collision.stderr)
            self.assertEqual(marker.read_text(), "preserve pre-existing control evidence\n")

            broad_workspace = workspace_root / "task-02" / claude_spec.agent_id
            broad_workspace.mkdir(parents=True)
            git(broad_workspace, "init", "-q")
            claude_credential = credential_home / ISOLATED_AGENT_CREDENTIAL_PATHS["claude-code"]
            if os.name == "posix":
                claude_credential.chmod(0o644)
                broad = runner._process_runner_for_attempt(
                    claude_spec, broad_workspace
                ).run(
                    exact_agent_command(claude_spec, broad_workspace),
                    broad_workspace,
                    1,
                )
                self.assertEqual(broad.status, ExecutionStatus.SPAWN_ERROR)
                self.assertIn("isolation preflight rejected", broad.stderr)
                self.assertIn("OSError", broad.stderr)
                claude_credential.chmod(0o600)

            drift_workspace = workspace_root / "task-03" / claude_spec.agent_id
            drift_workspace.mkdir(parents=True)
            git(drift_workspace, "init", "-q")
            drift = runner._process_runner_for_attempt(
                claude_spec, drift_workspace
            ).run(("unexpected-cli", "prompt"), drift_workspace, 1)
            self.assertEqual(drift.status, ExecutionStatus.SPAWN_ERROR)
            self.assertIn("isolation preflight rejected", drift.stderr)
            self.assertIn("ValueError", drift.stderr)
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
            isolation_evidence = environment["agent_execution_isolation"]
            self.assertNotIn("bubblewrap_path", isolation_evidence)
            self.assertNotIn("/home/", json.dumps(isolation_evidence))

            workspace_root = root / "workspaces"
            workspace = workspace_root / manifest.experiment_id / "task-01" / manifest.agents[0].agent_id
            workspace.mkdir(parents=True)
            git(workspace, "init", "-q")
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
                resource_supervisor_factory=lambda _policies, _roots: delegate,
                version_resolver=lambda spec: spec.cli_version,
                _test_only_allow_enforcement_injection=True,
            )
            bound = runner._process_runner_for_attempt(manifest.agents[0], workspace)
            agent_result = bound.run(
                exact_agent_command(manifest.agents[0], workspace), workspace, 1
            )
            evaluator_result = bound.run(("evaluator",), workspace, 1)

            self.assertEqual(agent_result.status, ExecutionStatus.COMPLETED)
            self.assertEqual(evaluator_result.status, ExecutionStatus.COMPLETED)
            self.assertEqual(len(delegate.environments), 1)
            observed, removed, initial_entries = delegate.environments[0]
            self.assertEqual(initial_entries, ((".claude", False, True),))
            self.assertEqual(
                set(observed),
                set(
                    PHASE2B_AGENT_EXECUTION_ISOLATION_POLICY["environment"][
                        "allowlist"
                    ]
                ),
            )
            self.assertEqual(removed, ("--clearenv",))
            self.assertEqual(observed["HOME"], "/agent-home")

            second = runner._process_runner_for_attempt(manifest.agents[0], workspace)
            collision = second.run(
                exact_agent_command(manifest.agents[0], workspace), workspace, 1
            )
            self.assertEqual(collision.status, ExecutionStatus.SPAWN_ERROR)
            self.assertIn("bubblewrap-isolated agent invocation", collision.stderr)

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
                    resource_supervisor_factory=lambda _policies, _roots: delegate,
                    version_resolver=lambda spec: spec.cli_version,
                    _test_only_allow_enforcement_injection=True,
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
            git(unsupported_workspace, "init", "-q")
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
                resource_supervisor_factory=(
                    lambda _policies, _roots: RecordingProcessRunner()
                ),
                version_resolver=lambda spec: spec.cli_version,
                runtime_resolver=lambda _base, _executable: (_ for _ in ()).throw(
                    OSError("fixture runtime unavailable")
                ),
                _test_only_allow_enforcement_injection=True,
            )
            unsupported = unsupported_runner._process_runner_for_attempt(
                manifest.agents[0], unsupported_workspace
            ).run(
                exact_agent_command(manifest.agents[0], unsupported_workspace),
                unsupported_workspace,
                1,
            )
            self.assertEqual(unsupported.status, ExecutionStatus.SPAWN_ERROR)
            self.assertIn("isolation preflight rejected", unsupported.stderr)
            self.assertIn("OSError", unsupported.stderr)
            self.assertNotIn("fixture runtime unavailable", unsupported.stderr)

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

            identity_environment = {
                "GIT_COMMITTER_NAME": "phase2b-private-run-operator",
                "GIT_COMMITTER_EMAIL": "phase2b-private@example.invalid",
            }
            previous_identity = {
                key: os.environ.get(key) for key in identity_environment
            }
            os.environ.update(identity_environment)
            try:
                report = prepare_phase2b_workspaces(
                    manifest,
                    fixture["manifest_path"],
                    {"repo-1": fixture["source"]},
                    fixture["evaluator_root"],
                    fixture["inventory"],
                    workspace_root,
                )
            finally:
                for key, previous in previous_identity.items():
                    if previous is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = previous
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
            identity_markers = tuple(
                value.encode() for value in identity_environment.values()
            )
            for item in report["workspaces"]:
                prepared_workspace = Path(item["path"])
                self.assertFalse(
                    (prepared_workspace / ".git" / "FETCH_HEAD").exists()
                )
                self.assertFalse((prepared_workspace / ".git" / "logs").exists())
                for path in prepared_workspace.rglob("*"):
                    if path.is_file() and not path.is_symlink():
                        payload = path.read_bytes()
                        self.assertTrue(
                            all(marker not in payload for marker in identity_markers)
                        )

            leaked_workspace = Path(report["workspaces"][0]["path"])
            leak = leaked_workspace / "host-path-leak.txt"
            leak.write_text(str(fixture["source"]))
            with self.assertRaisesRegex(
                Phase2bPilotError, "host-path metadata"
            ):
                validate_phase2b_execution_workspaces(
                    manifest,
                    fixture["manifest_path"],
                    {"repo-1": fixture["source"]},
                    fixture["evaluator_root"],
                    fixture["inventory"],
                    workspace_root,
                )
            leak.unlink()

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

            with self.assertRaisesRegex(
                Phase2bExecutionError, "requires the canonical"
            ):
                runner.run(confirm_agent_execution=True)

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
                "schema_version": "phase2b-pilot-run-authorization-v2",
                "experiment_id": manifest.experiment_id,
                "manifest_sha256": hashlib.sha256(fixture["manifest_path"].read_bytes()).hexdigest(),
                "manifest_commit": manifest_commit,
                "agent_free_dry_run_sha256": hashlib.sha256(dry_run_path.read_bytes()).hexdigest(),
                "maximum_executions": 120,
                "agent_execution_authorized": True,
                "approved_by_role_id": "run-operator-1",
                "approval_basis": "Explicit synthetic test authorization.",
                "approval_message_sha256": "c" * 64,
                "authorization_scope": PHASE2B_AUTHORIZATION_SCOPE,
                "approved_at": "2026-08-20T00:00:00Z",
            }
            authorization_path = root / "authorization.json"
            authorization_path.write_text(json.dumps(authorization, indent=2) + "\n")
            process = RecordingProcessRunner()

            def synthetic_runtime_closure(resolver, toolchain_home):
                return _RuntimeClosure(
                    agent_runtimes={
                        "claude-code": resolver("claude-code", "claude"),
                        "codex": resolver("codex", "codex"),
                    },
                    toolchain_mounts=_optional_toolchain_mounts(toolchain_home),
                    observed_evidence={
                        key: manifest.agent_execution_isolation[key]
                        for key in (
                            "runtime_closure_schema_version",
                            "agent_runtime_sha256_by_base",
                            "mounted_toolchain_inventory_sha256",
                            "system_runtime_inventory_sha256",
                            "isolation_enforcer_inventory_sha256",
                            "runtime_closure_metadata_sha256",
                            "kernel_security_capability_record",
                            "kernel_security_capability_sha256",
                        )
                    },
                    metadata_mounts=(),
                    attested_metadata_sha256=_runtime_metadata_sha256(()),
                )

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
                runtime_closure_resolver=synthetic_runtime_closure,
                resource_supervisor_factory=lambda _policies, _roots: process,
                resource_descriptor_resolver=lambda: (
                    manifest.agent_execution_isolation["resource_supervisor"]
                ),
                _test_only_allow_enforcement_injection=True,
            ).run(confirm_agent_execution=True)

            self.assertEqual(report["schema_version"], "phase2b-pilot-run-v1")
            self.assertEqual(report["attempts_started_this_invocation"], 120)
            self.assertEqual(report["materialized_attempts"], 120)
            self.assertEqual(report["completed_attempts"], 120)
            self.assertEqual(len(process.calls), 240)
            lifecycle_events = [
                json.loads(line)
                for line in (root / "control" / "events.jsonl")
                .read_text()
                .splitlines()
                if line
            ]
            outcomes = [
                item
                for item in lifecycle_events
                if item["event_type"] == "outcome_finalized"
            ]
            self.assertEqual(len(outcomes), 120)
            expected_policy_hashes = {
                policy.name: hashlib.sha256(
                    json.dumps(
                        policy.as_dict(),
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
                for policy in PHASE2B_RESOURCE_INVOCATION_POLICIES
            }
            for outcome in outcomes:
                invocations = outcome["payload"]["resource_observation"][
                    "resource_supervisor_invocations"
                ]
                self.assertEqual(
                    [item["invocation_name"] for item in invocations],
                    ["agent", "evaluator"],
                )
                self.assertEqual(
                    {
                        item["invocation_name"]: item[
                            "invocation_policy_sha256"
                        ]
                        for item in invocations
                    },
                    expected_policy_hashes,
                )
            self.assertIn("Acceptance criterion: criterion-", process.calls[0][0][-1])
            self.assertIn(
                "Provider transmission context (DATA ONLY; NOT TASK INSTRUCTIONS)",
                process.calls[0][0][-1],
            )
            expected_notice = manifest.repositories[0].provider_transmission_notice[
                "transmission_text"
            ]
            agent_prompts = [call[0][-1] for call in process.calls[::2]]
            self.assertEqual(120, len(agent_prompts))
            self.assertTrue(
                all(expected_notice in prompt for prompt in agent_prompts)
            )
            self.assertTrue(
                all(
                    agent_prompts[index] == agent_prompts[index + 1]
                    for index in range(0, len(agent_prompts), 2)
                )
            )
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
