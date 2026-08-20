from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from adaptive_orchestrator.core.domain import Capability
from adaptive_orchestrator.execution.verification import (
    evaluator_content_version,
    hash_evaluator_artifacts,
    validate_evaluator_artifacts,
)
from adaptive_orchestrator.experiments.paired_experiment import (
    ORDER_ASSIGNMENT_RULE,
    PRIMARY_METRIC,
    PairAssignment,
    PairedAgentSpec,
    PairedEvaluatorAssertionContract,
    PairedEvaluatorSpec,
    PairedExperimentError,
    PairedManifest,
    PairedTaskSpec,
    _create_isolated_checkout,
    _git,
    _path_component,
    _resolve_git_path,
    assign_pairs,
)


PHASE2B_MANIFEST_SCHEMA = "paired-pilot-manifest-v1"
PHASE2B_PROTOCOL_VERSION = "phase2b-pilot-prereg-v1.1"
PHASE2B_PLAN_SCHEMA = "phase2b-pilot-workspace-plan-v1"
PHASE2B_DRY_RUN_SCHEMA = "phase2b-pilot-agent-free-dry-run-v1"
PHASE2B_AUTHORIZATION_SCHEMA = "phase2b-pilot-run-authorization-v1"
PHASE2B_INSTRUCTION_INVENTORY_SCHEMA = "phase2b-global-instruction-inventory-v1"
STABLE_IDENTITY_RULE = "uuidv5-experiment-task-agent-v1"
EMPTY_EFFECTIVE_INSTRUCTION_SHA256 = hashlib.sha256(b"").hexdigest()
ISOLATED_AGENT_HOME_ENVIRONMENT_VARIABLES = (
    "CLAUDE_CONFIG_DIR",
    "CODEX_HOME",
    "HOME",
    "XDG_CACHE_HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
)
INFERENCE_SCOPE = (
    "variance-discordance-missingness-and-confirmatory-sizing-not-agent-ranking"
)
SECONDARY_METRICS = (
    "reliability",
    "constraint-and-safety-violations",
    "agent-evaluator-and-experiment-time",
    "comparable-resource-units-with-raw-token-caveat",
    "cost-when-observed-for-both-agents",
    "modified-file-scope",
    "evaluator-coverage-and-missingness",
)
LANGUAGE_QUOTA = {"ko": 20, "en": 20, "mixed": 20}
CATEGORY_QUOTA = {
    "implementation": 12,
    "debugging": 12,
    "testing": 12,
    "refactoring": 12,
    "repository-analysis-planning": 12,
}

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_HASH = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_VERSION = re.compile(r"^sha256:[0-9a-f]{64}$")


class Phase2bPilotError(PairedExperimentError):
    """The Phase 2b manifest or its execution-free environment is invalid."""


@dataclass(frozen=True, slots=True)
class Phase2bRepositorySpec:
    repository_id: str
    source: str
    base_revision: str
    base_tree_hash: str
    license_or_use_basis: str


@dataclass(frozen=True, slots=True)
class Phase2bPilotManifest:
    raw: Mapping[str, Any]
    paired: PairedManifest
    repositories: tuple[Phase2bRepositorySpec, ...]
    task_repository_ids: Mapping[str, str]
    protected_evaluator_root_id: str
    construction_roles: Mapping[str, tuple[str, ...]]
    global_instruction_context: Mapping[str, Any]

    @property
    def schema_version(self) -> str:
        return self.paired.schema_version

    @property
    def experiment_id(self) -> str:
        return self.paired.experiment_id

    @property
    def tasks(self) -> tuple[PairedTaskSpec, ...]:
        return self.paired.tasks

    @property
    def agents(self) -> tuple[PairedAgentSpec, PairedAgentSpec]:
        return self.paired.agents

    def as_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.raw))


def load_phase2b_manifest(path: Path) -> Phase2bPilotManifest:
    try:
        raw = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_object_keys,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise Phase2bPilotError(f"Unable to read Phase 2b manifest {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise Phase2bPilotError("Phase 2b manifest must be a JSON object.")
    return phase2b_manifest_from_dict(raw)


def phase2b_manifest_from_dict(raw: Mapping[str, Any]) -> Phase2bPilotManifest:
    _exact_keys(raw, {
        "schema_version", "protocol_version", "study_phase", "pilot_purpose",
        "experiment_id", "task_set_version", "construction_roles", "repositories",
        "environment", "agents", "assignment", "tasks", "analysis_plan",
        "maximum_resource_budget", "rules", "confirmatory_holdout", "authorization",
    }, "manifest")
    _const(raw, "schema_version", PHASE2B_MANIFEST_SCHEMA)
    _const(raw, "protocol_version", PHASE2B_PROTOCOL_VERSION)
    _const(raw, "study_phase", "phase2b-variance-pilot")
    _const(
        raw,
        "pilot_purpose",
        "pipeline-discordance-variance-missingness-and-confirmatory-sizing",
    )
    experiment_id = _safe_id(raw, "experiment_id")
    task_set_version = _text(raw, "task_set_version")

    role_sets = _construction_roles(_object(raw, "construction_roles"))
    repositories = _repositories(_array(raw, "repositories"))
    repository_ids = {item.repository_id for item in repositories}
    environment = _environment(_object(raw, "environment"))
    agents = _agents(_array(raw, "agents"))
    assignment = _assignment(_object(raw, "assignment"))
    tasks, task_repository_ids = _tasks(
        _array(raw, "tasks"),
        task_set_version=task_set_version,
        repository_ids=repository_ids,
        role_sets=role_sets,
    )
    analysis = _analysis_plan(_object(raw, "analysis_plan"))
    budget = _resource_budget(_object(raw, "maximum_resource_budget"))
    rules = _rules(_object(raw, "rules"))
    _confirmatory_holdout(_object(raw, "confirmatory_holdout"))
    _authorization(_object(raw, "authorization"))

    first_repository = repositories[0]
    paired = PairedManifest(
        schema_version=PHASE2B_MANIFEST_SCHEMA,
        protocol_version=PHASE2B_PROTOCOL_VERSION,
        experiment_id=experiment_id,
        task_set_version=task_set_version,
        environment_epoch=str(environment["environment_epoch"]),
        base_revision=first_repository.base_revision,
        base_tree_hash=first_repository.base_tree_hash,
        random_seed=int(assignment["random_seed"]),
        order_assignment_rule=ORDER_ASSIGNMENT_RULE,
        agents=agents,
        tasks=tasks,
        primary_metric=PRIMARY_METRIC,
        secondary_metrics=SECONDARY_METRICS,
        reporting_strata=("instruction_language", "task_category"),
        minimum_reporting_cell_size=int(analysis["minimum_reporting_cell_size"]),
        non_inferiority_margin=0.0,
        confidence_level=0.95,
        interval_method=str(analysis["binary_interval_method"]),
        maximum_executions=120,
        maximum_resource_budget={
            "wall_time_seconds": budget["maximum_active_wall_time_seconds"],
            "agent_execution_count": 120,
            "evaluator_execution_count": 120,
        },
        stopping_rules=tuple(rules["stopping"]),
        pause_rules=tuple(rules["pause"]),
        exclusion_rules=tuple(rules["exclusion"]),
    )
    assignments = assign_pairs(paired)
    first_positions = [item.agent_order[0] for item in assignments]
    if any(first_positions.count(agent.agent_id) != 30 for agent in agents):
        raise Phase2bPilotError("Phase 2b assignment must balance first position 30/30.")
    if len({item.attempt_ids[agent_id] for item in assignments for agent_id in item.agent_order}) != 120:
        raise Phase2bPilotError("Phase 2b deterministic attempt identities are not unique.")

    return Phase2bPilotManifest(
        raw=json.loads(json.dumps(raw)),
        paired=paired,
        repositories=repositories,
        task_repository_ids=task_repository_ids,
        protected_evaluator_root_id=str(environment["protected_evaluator_root_id"]),
        construction_roles=role_sets,
        global_instruction_context=dict(environment["global_instruction_context"]),
    )


def plan_phase2b_workspaces(
    manifest: Phase2bPilotManifest,
    workspace_root: Path,
) -> dict[str, Any]:
    """Project all 120 attempt paths without reading or changing the filesystem."""

    root = Path(os.path.abspath(workspace_root.expanduser()))
    experiment_root = root / _path_component(manifest.experiment_id)
    repositories = {item.repository_id: item for item in manifest.repositories}
    assignments = assign_pairs(manifest.paired)
    workspaces: list[dict[str, Any]] = []
    for assignment in assignments:
        repository_id = manifest.task_repository_ids[assignment.task_id]
        repository = repositories[repository_id]
        for position, agent_id in enumerate(assignment.agent_order):
            workspaces.append({
                "task_id": assignment.task_id,
                "repository_id": repository_id,
                "base_revision": repository.base_revision,
                "base_tree_hash": repository.base_tree_hash,
                "pair_id": assignment.pair_id,
                "execution_id": assignment.execution_id,
                "attempt_id": assignment.attempt_ids[agent_id],
                "agent_id": agent_id,
                "agent_order_position": position,
                "path": str(
                    experiment_root
                    / _path_component(assignment.task_id)
                    / _path_component(agent_id)
                ),
            })
    if len(workspaces) != 120 or len({item["path"] for item in workspaces}) != 120:
        raise Phase2bPilotError("Phase 2b workspace plan must contain 120 unique paths.")
    return {
        "schema_version": PHASE2B_PLAN_SCHEMA,
        "manifest_schema_version": manifest.schema_version,
        "experiment_id": manifest.experiment_id,
        "agent_execution_started": False,
        "workspace_creation_started": False,
        "workspace_root": str(root),
        "assignment_rule": ORDER_ASSIGNMENT_RULE,
        "stable_identity_rule": STABLE_IDENTITY_RULE,
        "first_position_counts": {
            agent.agent_id: sum(
                item.agent_order[0] == agent.agent_id for item in assignments
            )
            for agent in manifest.agents
        },
        "assignments": [item.as_dict() for item in assignments],
        "workspaces": workspaces,
    }


def mark_phase2b_analysis_non_promotional(report: dict[str, object]) -> None:
    reason = (
        "Phase 2b estimates pipeline variance, discordance, and missingness; "
        "it does not promote or rank a policy."
    )
    overall = report.get("overall_quota_diagnostic_not_workload_value")
    if isinstance(overall, dict):
        overall["ranking_withheld_reason"] = reason
    strata = report.get("strata")
    if isinstance(strata, dict):
        for values in strata.values():
            if isinstance(values, dict):
                for summary in values.values():
                    if isinstance(summary, dict):
                        summary["ranking_withheld_reason"] = reason
    report["promotion_allowed"] = False
    report["promotion_blockers"] = [
        "phase2b-pilot-estimates-variance-discordance-and-missingness-only",
        "confirmatory-task-set-and-independent-workload-weights-required",
    ]


def validate_phase2b_environment(
    manifest: Phase2bPilotManifest,
    manifest_path: Path,
    repository_roots: Mapping[str, Path],
    evaluator_root: Path,
    instruction_inventory_path: Path,
) -> dict[str, Any]:
    """Validate source, fixture, evaluator, and control pins without invoking an agent."""

    current_manifest = load_phase2b_manifest(
        manifest_path.expanduser().resolve(strict=True)
    )
    if current_manifest.as_dict() != manifest.as_dict():
        raise Phase2bPilotError("Phase 2b manifest object differs from manifest_path.")
    expected_ids = {item.repository_id for item in manifest.repositories}
    if set(repository_roots) != expected_ids:
        raise Phase2bPilotError(
            "Phase 2b repository root IDs must exactly match the manifest: "
            f"expected {sorted(expected_ids)}, got {sorted(repository_roots)}"
        )
    configured_evaluator_root = evaluator_root.expanduser().absolute()
    if configured_evaluator_root.is_symlink():
        raise Phase2bPilotError("Protected evaluator root must not be a symlink.")
    evaluator_root = configured_evaluator_root.resolve(strict=True)
    if not evaluator_root.is_dir():
        raise Phase2bPilotError("Protected evaluator root must be a real directory.")
    configured_inventory = instruction_inventory_path.expanduser().absolute()
    if configured_inventory.is_symlink():
        raise Phase2bPilotError("Global instruction inventory must not be a symlink.")
    instruction_inventory_path = configured_inventory.resolve(strict=True)
    if not instruction_inventory_path.is_file():
        raise Phase2bPilotError("Global instruction inventory must be a regular file.")
    instruction_inventory_sha256 = _sha256(instruction_inventory_path.read_bytes())
    if instruction_inventory_sha256 != manifest.global_instruction_context["inventory_artifact_hash"]:
        raise Phase2bPilotError("Global instruction inventory hash changed.")
    instruction_inventory = _validate_instruction_inventory(
        instruction_inventory_path,
        manifest.global_instruction_context,
    )

    repository_by_id = {item.repository_id: item for item in manifest.repositories}
    resolved_roots: dict[str, Path] = {}
    repository_evidence: dict[str, dict[str, Any]] = {}
    for repository_id, configured in repository_roots.items():
        configured_source = configured.expanduser().absolute()
        if configured_source.is_symlink():
            raise Phase2bPilotError(
                f"Source repository root must not be a symlink: {repository_id}"
            )
        source = configured_source.resolve(strict=True)
        if Path(_git(source, "rev-parse", "--show-toplevel")).resolve(strict=True) != source:
            raise Phase2bPilotError(f"Repository root is not the Git toplevel: {source}")
        if _git(source, "status", "--porcelain", "--untracked-files=all"):
            raise Phase2bPilotError(f"Source repository must be clean: {repository_id}")
        if evaluator_root == source or evaluator_root.is_relative_to(source):
            raise Phase2bPilotError("Protected evaluator root must be outside every source repository.")
        spec = repository_by_id[repository_id]
        commit_hash = _git(source, "rev-parse", f"{spec.base_revision}^{{commit}}")
        tree_hash = _git(source, "rev-parse", f"{commit_hash}^{{tree}}")
        if commit_hash != spec.base_revision or tree_hash != spec.base_tree_hash:
            raise Phase2bPilotError(f"Pinned repository identity changed: {repository_id}")
        resolved_roots[repository_id] = source
        repository_evidence[repository_id] = {
            "commit_hash": commit_hash,
            "tree_hash": tree_hash,
        }

    artifact_hashes: dict[str, str] = {}
    fixture_hashes: dict[str, str] = {}
    for task in manifest.tasks:
        artifact_paths = _protected_artifact_paths(evaluator_root, task.evaluator.artifact_paths)
        for source in resolved_roots.values():
            validate_evaluator_artifacts(tuple(str(path) for path in artifact_paths), source)
        artifact_hash = hash_evaluator_artifacts(tuple(str(path) for path in artifact_paths))
        if artifact_hash != task.evaluator.artifact_hash:
            raise Phase2bPilotError(f"Evaluator artifact hash changed for task {task.task_id}.")
        version = evaluator_content_version(
            task.evaluator.command,
            tuple(str(path) for path in artifact_paths),
        )
        if version != task.evaluator.version:
            raise Phase2bPilotError(f"Evaluator version changed for task {task.task_id}.")
        if not any(token in task.evaluator.artifact_paths for token in task.evaluator.command):
            raise Phase2bPilotError(f"Evaluator command does not reference its protected artifact: {task.task_id}")
        artifact_hashes[task.task_id] = artifact_hash

    tasks_by_repository: dict[str, list[PairedTaskSpec]] = {key: [] for key in expected_ids}
    for task in manifest.tasks:
        tasks_by_repository[manifest.task_repository_ids[task.task_id]].append(task)
    with tempfile.TemporaryDirectory(prefix="phase2b-pilot-base-validation-") as directory:
        temporary = Path(directory)
        for repository_id, tasks in tasks_by_repository.items():
            checkout = temporary / _path_component(repository_id)
            _create_isolated_checkout(
                resolved_roots[repository_id],
                checkout,
                repository_evidence[repository_id]["commit_hash"],
            )
            for task in tasks:
                paths = _fixture_paths(checkout, task.fixture_paths)
                fixture_hash = hash_evaluator_artifacts(tuple(str(path) for path in paths))
                if fixture_hash != task.fixture_hash:
                    raise Phase2bPilotError(f"Fixture hash changed for task {task.task_id}.")
                fixture_hashes[task.task_id] = fixture_hash

    return {
        "manifest_sha256": _sha256(manifest_path.read_bytes()),
        "repository_evidence": repository_evidence,
        "evaluator_artifact_hashes": artifact_hashes,
        "fixture_hashes": fixture_hashes,
        "global_instruction_inventory_sha256": instruction_inventory_sha256,
        "global_instruction_resolution": instruction_inventory["resolution"],
        "isolated_agent_home_contract": instruction_inventory[
            "isolated_agent_home_contract"
        ],
        "task_count": 60,
        "attempt_count": 120,
        "agent_execution_started": False,
    }


def _validate_instruction_inventory(
    path: Path,
    manifest_context: Mapping[str, Any],
) -> Mapping[str, Any]:
    try:
        raw = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_object_keys,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise Phase2bPilotError(f"Unable to read global instruction inventory: {exc}") from exc
    inventory = _mapping(raw, "global_instruction_inventory")
    _exact_keys(inventory, {
        "schema_version", "resolution", "verified_at",
        "claude_effective_instruction_sha256",
        "codex_effective_instruction_sha256",
        "codex_project_doc_fallback_filenames",
        "semantic_equivalence_review_completed",
        "isolated_agent_home_contract",
    }, "global_instruction_inventory")
    _const(inventory, "schema_version", PHASE2B_INSTRUCTION_INVENTORY_SCHEMA)
    for key in ("resolution", "verified_at"):
        if inventory.get(key) != manifest_context.get(key):
            raise Phase2bPilotError(
                f"Global instruction inventory {key} differs from the manifest."
            )
    _timestamp(inventory, "verified_at")
    hash_pairs = (
        ("claude_effective_instruction_sha256", "claude_effective_instruction_hash"),
        ("codex_effective_instruction_sha256", "codex_effective_instruction_hash"),
    )
    for inventory_key, manifest_key in hash_pairs:
        _hash(inventory, inventory_key)
        if inventory[inventory_key] != manifest_context[manifest_key]:
            raise Phase2bPilotError(
                f"Global instruction inventory {inventory_key} differs from the manifest."
            )
    _const(
        inventory,
        "codex_project_doc_fallback_filenames",
        manifest_context["codex_project_doc_fallback_filenames"],
    )

    if inventory["resolution"] == "isolated-empty-agent-homes":
        _const(inventory, "semantic_equivalence_review_completed", False)
        for key, _ in hash_pairs:
            _const(inventory, key, EMPTY_EFFECTIVE_INSTRUCTION_SHA256)
        contract = _object(inventory, "isolated_agent_home_contract")
        _exact_keys(contract, {
            "fresh_per_attempt", "inherited_user_home", "initial_file_count",
            "environment_variables",
        }, "isolated_agent_home_contract")
        _const(contract, "fresh_per_attempt", True)
        _const(contract, "inherited_user_home", False)
        _const(contract, "initial_file_count", 0)
        _const(
            contract,
            "environment_variables",
            list(ISOLATED_AGENT_HOME_ENVIRONMENT_VARIABLES),
        )
    else:
        _const(inventory, "semantic_equivalence_review_completed", True)
        _const(inventory, "isolated_agent_home_contract", None)
    return inventory


def prepare_phase2b_workspaces(
    manifest: Phase2bPilotManifest,
    manifest_path: Path,
    repository_roots: Mapping[str, Path],
    evaluator_root: Path,
    instruction_inventory_path: Path,
    workspace_root: Path,
) -> dict[str, Any]:
    """Materialize and verify all 120 exact-base checkouts without agent execution."""

    configured_root = workspace_root.expanduser().absolute()
    if configured_root.is_symlink():
        raise Phase2bPilotError("Phase 2b workspace root must not be a symlink.")
    root = configured_root.resolve()
    resolved_sources = {
        key: value.expanduser().resolve(strict=True)
        for key, value in repository_roots.items()
    }
    if any(root == source or root.is_relative_to(source) for source in resolved_sources.values()):
        raise Phase2bPilotError("Phase 2b workspace root must be outside every source repository.")
    resolved_evaluator_root = evaluator_root.expanduser().resolve(strict=True)
    if root == resolved_evaluator_root or root.is_relative_to(resolved_evaluator_root):
        raise Phase2bPilotError("Phase 2b workspace root must be outside protected evaluators.")
    root_preexisted = root.exists()
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise Phase2bPilotError("Phase 2b workspace root must be new or empty.")
    environment = validate_phase2b_environment(
        manifest,
        manifest_path,
        resolved_sources,
        evaluator_root,
        instruction_inventory_path,
    )
    plan = plan_phase2b_workspaces(manifest, root)
    task_by_id = {task.task_id: task for task in manifest.tasks}

    created: list[Path] = []
    prepared: list[dict[str, Any]] = []
    try:
        for item in plan["workspaces"]:
            target = Path(item["path"])
            if target.exists():
                raise Phase2bPilotError(f"Phase 2b workspace target already exists: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            _create_isolated_checkout(
                resolved_sources[item["repository_id"]],
                target,
                item["base_revision"],
            )
            created.append(target)
            commit_hash = _git(target, "rev-parse", "HEAD")
            tree_hash = _git(target, "rev-parse", "HEAD^{tree}")
            clean = not bool(_git(target, "status", "--porcelain", "--untracked-files=all"))
            common_dir = _resolve_git_path(
                target, _git(target, "rev-parse", "--git-common-dir")
            )
            visible_refs = tuple(
                line
                for line in _git(target, "for-each-ref", "--format=%(refname)").splitlines()
                if line
            )
            if (
                commit_hash != item["base_revision"]
                or tree_hash != item["base_tree_hash"]
                or not clean
                or common_dir != (target / ".git").resolve()
                or visible_refs
            ):
                raise Phase2bPilotError(f"Prepared Phase 2b workspace failed isolation: {target}")
            task = task_by_id[item["task_id"]]
            fixture_hash = hash_evaluator_artifacts(
                tuple(str(path) for path in _fixture_paths(target, task.fixture_paths))
            )
            if fixture_hash != task.fixture_hash:
                raise Phase2bPilotError(f"Prepared fixture hash changed: {target}")
            prepared.append({
                **item,
                "commit_hash": commit_hash,
                "tree_hash": tree_hash,
                "clean": clean,
                "isolated_git_dir": True,
                "visible_ref_count": 0,
                "fixture_hash": fixture_hash,
                "evaluator_artifact_hash": task.evaluator.artifact_hash,
            })
    except BaseException:
        experiment_root = root / _path_component(manifest.experiment_id)
        shutil.rmtree(experiment_root, ignore_errors=True)
        if not root_preexisted and root.is_dir():
            try:
                root.rmdir()
            except OSError:
                pass
        raise

    return {
        "schema_version": PHASE2B_DRY_RUN_SCHEMA,
        "manifest_schema_version": manifest.schema_version,
        "manifest_sha256": environment["manifest_sha256"],
        "global_instruction_inventory_sha256": environment[
            "global_instruction_inventory_sha256"
        ],
        "experiment_id": manifest.experiment_id,
        "agent_execution_started": False,
        "workspace_creation_started": True,
        "task_count": 60,
        "workspace_count": len(prepared),
        "base_hashes_match_manifest": True,
        "all_workspaces_clean": all(item["clean"] for item in prepared),
        "all_git_directories_isolated": all(item["isolated_git_dir"] for item in prepared),
        "all_visible_ref_counts_zero": all(item["visible_ref_count"] == 0 for item in prepared),
        "first_position_counts": plan["first_position_counts"],
        "assignments": plan["assignments"],
        "workspaces": prepared,
    }


def load_run_authorization(
    path: Path,
    *,
    manifest_path: Path,
    manifest: Phase2bPilotManifest,
) -> Mapping[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_object_keys,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise Phase2bPilotError(f"Unable to read Phase 2b run authorization: {exc}") from exc
    if not isinstance(value, dict):
        raise Phase2bPilotError("Phase 2b run authorization must be an object.")
    _exact_keys(value, {
        "schema_version", "experiment_id", "manifest_sha256", "manifest_commit",
        "agent_free_dry_run_sha256", "maximum_executions",
        "agent_execution_authorized", "approved_by_role_id", "approval_basis",
        "approved_at",
    }, "run authorization")
    _const(value, "schema_version", PHASE2B_AUTHORIZATION_SCHEMA)
    _const(value, "experiment_id", manifest.experiment_id)
    _const(value, "manifest_sha256", _sha256(manifest_path.read_bytes()))
    _hash(value, "manifest_commit")
    _hash(value, "agent_free_dry_run_sha256")
    _const(value, "maximum_executions", 120)
    _const(value, "agent_execution_authorized", True)
    approver = _safe_id(value, "approved_by_role_id")
    if approver not in manifest.construction_roles["run_operator_role_ids"]:
        raise Phase2bPilotError("Run authorization approver is not a declared run operator.")
    _text(value, "approval_basis")
    _timestamp(value, "approved_at")
    return value


def validate_phase2b_dry_run_record(
    path: Path,
    *,
    manifest: Phase2bPilotManifest,
    manifest_path: Path,
    workspace_root: Path,
) -> Mapping[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_object_keys,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise Phase2bPilotError(f"Unable to read Phase 2b dry-run record: {exc}") from exc
    if not isinstance(value, dict):
        raise Phase2bPilotError("Phase 2b dry-run record must be an object.")
    _exact_keys(value, {
        "schema_version", "manifest_schema_version", "manifest_sha256",
        "global_instruction_inventory_sha256", "experiment_id",
        "agent_execution_started", "workspace_creation_started", "task_count",
        "workspace_count", "base_hashes_match_manifest", "all_workspaces_clean",
        "all_git_directories_isolated", "all_visible_ref_counts_zero",
        "first_position_counts", "assignments", "workspaces",
    }, "dry-run record")
    _const(value, "schema_version", PHASE2B_DRY_RUN_SCHEMA)
    _const(value, "manifest_schema_version", manifest.schema_version)
    _const(value, "manifest_sha256", _sha256(manifest_path.read_bytes()))
    _const(value, "experiment_id", manifest.experiment_id)
    _const(value, "agent_execution_started", False)
    _const(value, "workspace_creation_started", True)
    _const(value, "task_count", 60)
    _const(value, "workspace_count", 120)
    for key in (
        "base_hashes_match_manifest", "all_workspaces_clean",
        "all_git_directories_isolated", "all_visible_ref_counts_zero",
    ):
        _const(value, key, True)
    plan = plan_phase2b_workspaces(manifest, workspace_root)
    expected_assignments = json.loads(json.dumps(plan["assignments"]))
    if value["assignments"] != expected_assignments:
        raise Phase2bPilotError("Dry-run assignment projection changed.")
    if value["first_position_counts"] != plan["first_position_counts"]:
        raise Phase2bPilotError("Dry-run first-position balance changed.")
    workspaces = value["workspaces"]
    if not isinstance(workspaces, list) or len(workspaces) != 120:
        raise Phase2bPilotError("Dry-run workspace inventory must contain 120 rows.")
    identity_keys = (
        "task_id", "repository_id", "base_revision", "base_tree_hash", "pair_id",
        "execution_id", "attempt_id", "agent_id", "agent_order_position", "path",
    )
    projected = [{key: row.get(key) for key in identity_keys} for row in workspaces if isinstance(row, dict)]
    expected = [{key: row[key] for key in identity_keys} for row in plan["workspaces"]]
    if projected != expected:
        raise Phase2bPilotError("Dry-run workspace identities changed.")
    task_by_id = {task.task_id: task for task in manifest.tasks}
    row_keys = set(identity_keys) | {
        "commit_hash", "tree_hash", "clean", "isolated_git_dir",
        "visible_ref_count", "fixture_hash", "evaluator_artifact_hash",
    }
    for index, row in enumerate(workspaces):
        if not isinstance(row, dict):
            raise Phase2bPilotError(f"Dry-run workspace row {index} must be an object.")
        _exact_keys(row, row_keys, f"dry-run workspace row {index}")
        task = task_by_id[row["task_id"]]
        expected_values = {
            "commit_hash": row["base_revision"],
            "tree_hash": row["base_tree_hash"],
            "clean": True,
            "isolated_git_dir": True,
            "visible_ref_count": 0,
            "fixture_hash": task.fixture_hash,
            "evaluator_artifact_hash": task.evaluator.artifact_hash,
        }
        for key, expected_value in expected_values.items():
            if row.get(key) != expected_value or (
                isinstance(row.get(key), bool) != isinstance(expected_value, bool)
            ):
                raise Phase2bPilotError(
                    f"Dry-run workspace row {index} has invalid {key}."
                )
    return value


def validate_phase2b_execution_workspaces(
    manifest: Phase2bPilotManifest,
    manifest_path: Path,
    repository_roots: Mapping[str, Path],
    evaluator_root: Path,
    instruction_inventory_path: Path,
    workspace_root: Path,
    *,
    materialized_attempt_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """Revalidate a dry-run tree, preserving dirty finalized attempts on resume."""

    configured_root = workspace_root.expanduser().absolute()
    if configured_root.is_symlink():
        raise Phase2bPilotError("Phase 2b workspace root is symlinked.")
    root = configured_root.resolve(strict=True)
    if not root.is_dir():
        raise Phase2bPilotError("Phase 2b workspace root is missing or symlinked.")
    environment = validate_phase2b_environment(
        manifest,
        manifest_path,
        repository_roots,
        evaluator_root,
        instruction_inventory_path,
    )
    plan = plan_phase2b_workspaces(manifest, root)
    expected_attempt_ids = {row["attempt_id"] for row in plan["workspaces"]}
    materialized = set(materialized_attempt_ids)
    if not materialized.issubset(expected_attempt_ids):
        raise Phase2bPilotError("Execution state contains an unexpected Phase 2b attempt ID.")
    experiment_root = root / _path_component(manifest.experiment_id)
    if experiment_root.is_symlink() or not experiment_root.is_dir():
        raise Phase2bPilotError("Phase 2b experiment workspace root is missing or symlinked.")
    if set(root.iterdir()) != {experiment_root}:
        raise Phase2bPilotError("Phase 2b workspace root contains unexpected entries.")
    expected_task_dirs = {
        experiment_root / _path_component(task.task_id) for task in manifest.tasks
    }
    if set(experiment_root.iterdir()) != expected_task_dirs:
        raise Phase2bPilotError("Phase 2b experiment root contains unexpected task directories.")
    task_by_id = {task.task_id: task for task in manifest.tasks}
    for task_dir in expected_task_dirs:
        if task_dir.is_symlink() or not task_dir.is_dir():
            raise Phase2bPilotError(f"Phase 2b task workspace is missing or symlinked: {task_dir}")
        expected_agent_dirs = {
            Path(row["path"])
            for row in plan["workspaces"]
            if Path(row["path"]).parent == task_dir
        }
        if set(task_dir.iterdir()) != expected_agent_dirs:
            raise Phase2bPilotError(f"Phase 2b task workspace contains unexpected entries: {task_dir}")

    inspected: list[dict[str, Any]] = []
    for row in plan["workspaces"]:
        target = Path(row["path"])
        if target.is_symlink() or not target.is_dir() or target.resolve() != target:
            raise Phase2bPilotError(f"Phase 2b attempt workspace is missing or symlinked: {target}")
        commit_hash = _git(target, "rev-parse", "HEAD")
        tree_hash = _git(target, "rev-parse", "HEAD^{tree}")
        common_dir = _resolve_git_path(target, _git(target, "rev-parse", "--git-common-dir"))
        visible_refs = tuple(
            line
            for line in _git(target, "for-each-ref", "--format=%(refname)").splitlines()
            if line
        )
        clean = not bool(_git(target, "status", "--porcelain", "--untracked-files=all"))
        is_materialized = row["attempt_id"] in materialized
        if (
            commit_hash != row["base_revision"]
            or tree_hash != row["base_tree_hash"]
            or common_dir != (target / ".git").resolve()
            or visible_refs
        ):
            raise Phase2bPilotError(f"Phase 2b attempt workspace identity changed: {target}")
        if not is_materialized:
            if not clean:
                raise Phase2bPilotError(f"Unstarted Phase 2b workspace is not clean: {target}")
            task = task_by_id[row["task_id"]]
            fixture_hash = hash_evaluator_artifacts(
                tuple(str(path) for path in _fixture_paths(target, task.fixture_paths))
            )
            if fixture_hash != task.fixture_hash:
                raise Phase2bPilotError(f"Unstarted Phase 2b fixture changed: {target}")
        inspected.append({
            **row,
            "clean": clean,
            "materialized": is_materialized,
            "isolated_git_dir": True,
            "visible_ref_count": 0,
        })
    return {
        "manifest_sha256": environment["manifest_sha256"],
        "workspace_count": 120,
        "materialized_attempt_count": len(materialized),
        "remaining_attempt_count": 120 - len(materialized),
        "workspaces": inspected,
    }


def audit_committed_manifest(manifest_path: Path, expected_commit: str) -> dict[str, str]:
    path = manifest_path.expanduser().resolve(strict=True)
    repository = Path(_git(path.parent, "rev-parse", "--show-toplevel")).resolve(strict=True)
    relative = path.relative_to(repository).as_posix()
    commit = _git(repository, "rev-parse", f"{expected_commit}^{{commit}}")
    if commit != expected_commit:
        raise Phase2bPilotError("Run authorization manifest_commit is not an exact commit hash.")
    try:
        completed = subprocess.run(
            ("git", "-C", str(repository), "show", f"{commit}:{relative}"),
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise Phase2bPilotError(f"Unable to read committed manifest bytes: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode(errors="replace").strip() or f"exit {completed.returncode}"
        raise Phase2bPilotError(f"Unable to read committed manifest bytes: {detail}")
    committed = completed.stdout
    current = path.read_bytes()
    if committed != current:
        raise Phase2bPilotError("Phase 2b manifest bytes differ from the authorized commit.")
    if _git(repository, "status", "--porcelain", "--", relative):
        raise Phase2bPilotError("Phase 2b manifest has uncommitted changes.")
    return {
        "repository_root": str(repository),
        "manifest_commit": commit,
        "manifest_sha256": _sha256(current),
    }


def _construction_roles(raw: Mapping[str, Any]) -> Mapping[str, tuple[str, ...]]:
    _exact_keys(raw, {
        "task_author_role_ids", "evaluator_author_role_ids",
        "validity_reviewer_role_ids", "run_operator_role_ids", "analyst_role_ids",
        "construction_role_sets_disjoint_attested",
        "task_selection_frozen_before_agent_results",
        "evaluator_authors_blind_to_agent_identity",
        "validity_reviewers_blind_to_agent_results", "conflict_policy",
    }, "construction_roles")
    values = {
        key: _id_tuple(raw, key)
        for key in (
            "task_author_role_ids", "evaluator_author_role_ids",
            "validity_reviewer_role_ids", "run_operator_role_ids", "analyst_role_ids",
        )
    }
    for key in (
        "construction_role_sets_disjoint_attested",
        "task_selection_frozen_before_agent_results",
        "evaluator_authors_blind_to_agent_identity",
        "validity_reviewers_blind_to_agent_results",
    ):
        _const(raw, key, True)
    _text(raw, "conflict_policy")
    construction = (
        set(values["task_author_role_ids"]),
        set(values["evaluator_author_role_ids"]),
        set(values["validity_reviewer_role_ids"]),
    )
    if any(first & second for index, first in enumerate(construction) for second in construction[index + 1:]):
        raise Phase2bPilotError("Task, evaluator, and validity construction role sets must be disjoint.")
    return values


def _repositories(values: Sequence[Any]) -> tuple[Phase2bRepositorySpec, ...]:
    if not values:
        raise Phase2bPilotError("Phase 2b repositories cannot be empty.")
    result = []
    for index, item in enumerate(values):
        raw = _mapping(item, f"repositories[{index}]")
        _exact_keys(raw, {
            "repository_id", "source", "base_revision", "base_tree_hash",
            "license_or_use_basis",
        }, f"repositories[{index}]")
        result.append(Phase2bRepositorySpec(
            repository_id=_safe_id(raw, "repository_id"),
            source=_text(raw, "source"),
            base_revision=_hash(raw, "base_revision"),
            base_tree_hash=_hash(raw, "base_tree_hash"),
            license_or_use_basis=_text(raw, "license_or_use_basis"),
        ))
    if len({item.repository_id for item in result}) != len(result):
        raise Phase2bPilotError("Phase 2b repository IDs must be unique.")
    return tuple(result)


def _environment(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    _exact_keys(raw, {
        "environment_epoch", "global_instruction_context", "workspace_isolation",
        "protected_control_state", "protected_evaluators", "protected_evaluator_root_id",
        "network_access", "secret_access", "push_access", "production_mutation",
    }, "environment")
    _text(raw, "environment_epoch")
    global_context = _object(raw, "global_instruction_context")
    _exact_keys(global_context, {
        "resolution", "inventory_artifact_hash", "claude_effective_instruction_hash",
        "codex_effective_instruction_hash", "codex_project_doc_fallback_filenames",
        "verified_at",
    }, "global_instruction_context")
    if global_context.get("resolution") not in {
        "semantically-equivalent", "isolated-empty-agent-homes"
    }:
        raise Phase2bPilotError("Global instruction context is unresolved.")
    for key in (
        "inventory_artifact_hash", "claude_effective_instruction_hash",
        "codex_effective_instruction_hash",
    ):
        _hash(global_context, key)
    _const(global_context, "codex_project_doc_fallback_filenames", [])
    _timestamp(global_context, "verified_at")
    _const(raw, "workspace_isolation", "independent-exact-base-checkouts")
    _const(raw, "protected_control_state", "outside-agent-workspace-read-write-by-runner-only")
    _const(raw, "protected_evaluators", "outside-agent-workspace-read-only")
    _safe_id(raw, "protected_evaluator_root_id")
    for key in ("network_access", "secret_access", "push_access", "production_mutation"):
        _const(raw, key, "forbidden")
    return raw


def _agents(values: Sequence[Any]) -> tuple[PairedAgentSpec, PairedAgentSpec]:
    if len(values) != 2:
        raise Phase2bPilotError("Phase 2b requires exactly two agents.")
    result = []
    for index, item in enumerate(values):
        raw = _mapping(item, f"agents[{index}]")
        _exact_keys(raw, {
            "agent_id", "base_id", "model", "reasoning_tier", "cli_version",
            "permission_mode", "time_limit_seconds",
        }, f"agents[{index}]")
        base_id = _enum(raw, "base_id", {"claude-code", "codex"})
        reasoning = raw.get("reasoning_tier")
        if reasoning is not None and (not isinstance(reasoning, str) or not reasoning.strip()):
            raise Phase2bPilotError("reasoning_tier must be null or non-empty text.")
        if base_id == "codex" and reasoning is None:
            raise Phase2bPilotError("Codex Phase 2b agent requires a reasoning_tier.")
        permission_mode = _text(raw, "permission_mode")
        expected_permission_mode = (
            "acceptEdits" if base_id == "claude-code" else "workspace-write"
        )
        if permission_mode != expected_permission_mode:
            raise Phase2bPilotError(
                f"{base_id} Phase 2b permission_mode must be "
                f"{expected_permission_mode!r}."
            )
        result.append(PairedAgentSpec(
            agent_id=_safe_id(raw, "agent_id"),
            base_id=base_id,
            model=_text(raw, "model"),
            reasoning_tier=reasoning,
            cli_version=_text(raw, "cli_version"),
            permission_mode=permission_mode,
            time_limit_seconds=_positive_number(raw, "time_limit_seconds"),
        ))
    if {item.base_id for item in result} != {"claude-code", "codex"}:
        raise Phase2bPilotError("Phase 2b agents must be Claude Code and Codex.")
    if len({item.agent_id for item in result}) != 2:
        raise Phase2bPilotError("Phase 2b agent IDs must be unique.")
    return result[0], result[1]


def _assignment(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    _exact_keys(raw, {
        "random_seed", "order_assignment_rule", "stable_identity_rule",
        "balanced_first_position", "agent_result_isolation",
    }, "assignment")
    _integer(raw, "random_seed")
    _const(raw, "order_assignment_rule", ORDER_ASSIGNMENT_RULE)
    _const(raw, "stable_identity_rule", STABLE_IDENTITY_RULE)
    _const(raw, "balanced_first_position", True)
    _const(raw, "agent_result_isolation", True)
    return raw


def _tasks(
    values: Sequence[Any],
    *,
    task_set_version: str,
    repository_ids: set[str],
    role_sets: Mapping[str, tuple[str, ...]],
) -> tuple[tuple[PairedTaskSpec, ...], Mapping[str, str]]:
    if len(values) != 60:
        raise Phase2bPilotError("Phase 2b requires exactly 60 tasks.")
    result: list[PairedTaskSpec] = []
    repositories: dict[str, str] = {}
    evaluator_ids: set[str] = set()
    for index, item in enumerate(values):
        raw = _mapping(item, f"tasks[{index}]")
        _exact_keys(raw, {
            "task_id", "task_set_version", "source_provenance", "description",
            "objective", "constraints", "acceptance_criteria", "instruction_language",
            "repository_code_language", "repository_doc_language", "task_category",
            "required_capabilities", "risk", "mutation_scope", "read_only",
            "repository_id", "fixture_paths", "fixture_hash", "estimated_resource_bucket",
            "modified_file_allowlist", "task_author_role_ids", "confirmatory_reuse_allowed",
            "evaluator",
        }, f"tasks[{index}]")
        task_id = _safe_id(raw, "task_id")
        _const(raw, "task_set_version", task_set_version)
        language = _enum(raw, "instruction_language", set(LANGUAGE_QUOTA))
        category = _enum(raw, "task_category", set(CATEGORY_QUOTA))
        repository_id = _safe_id(raw, "repository_id")
        if repository_id not in repository_ids:
            raise Phase2bPilotError(f"Task references unknown repository: {task_id}")
        provenance = _source_provenance(
            _object(raw, "source_provenance"),
            language=language,
            task_author_roles=set(role_sets["task_author_role_ids"]),
        )
        task_authors = _id_tuple(raw, "task_author_role_ids")
        if not set(task_authors).issubset(role_sets["task_author_role_ids"]):
            raise Phase2bPilotError(f"Task author role is not declared: {task_id}")
        if provenance["selected_by_role_id"] not in task_authors:
            raise Phase2bPilotError(f"Task source selector is not one of its task authors: {task_id}")
        description = _text(raw, "description")
        objective = _text(raw, "objective")
        constraints = _text_tuple(raw, "constraints", nonempty=True)
        acceptance = _text_tuple(raw, "acceptance_criteria", nonempty=True)
        capabilities = _id_tuple(raw, "required_capabilities")
        try:
            tuple(Capability(item) for item in capabilities)
        except ValueError as exc:
            raise Phase2bPilotError(f"Unknown task capability for {task_id}: {exc}") from exc
        _const(raw, "risk", "low")
        _const(raw, "mutation_scope", "isolated-checkout-only")
        if not isinstance(raw.get("read_only"), bool):
            raise Phase2bPilotError(f"Task read_only must be boolean: {task_id}")
        fixture_paths = _relative_paths(raw, "fixture_paths", nonempty=True)
        allowlist = _relative_paths(raw, "modified_file_allowlist", nonempty=False)
        bucket = _enum(raw, "estimated_resource_bucket", {"small", "medium"})
        _const(raw, "confirmatory_reuse_allowed", False)
        evaluator = _evaluator(
            _object(raw, "evaluator"),
            task_id=task_id,
            contract_fields={
                "description": (description,),
                "objective": (objective,),
                "constraints": constraints,
                "acceptance_criteria": acceptance,
            },
            evaluator_roles=set(role_sets["evaluator_author_role_ids"]),
            validity_roles=set(role_sets["validity_reviewer_role_ids"]),
        )
        if bucket == "small" and evaluator.timeout_seconds > 30:
            raise Phase2bPilotError(
                f"Small-bucket evaluator timeout must be at most 30 seconds: {task_id}"
            )
        if bucket == "medium" and evaluator.timeout_seconds <= 30:
            raise Phase2bPilotError(
                f"Medium-bucket evaluator timeout must be greater than 30 seconds: {task_id}"
            )
        if evaluator.evaluator_id in evaluator_ids:
            raise Phase2bPilotError("Each Phase 2b task requires a unique evaluator ID.")
        evaluator_ids.add(evaluator.evaluator_id)
        if bool(raw["read_only"]) and allowlist:
            raise Phase2bPilotError(
                f"Read-only task modified_file_allowlist must be empty: {task_id}"
            )
        if not bool(raw["read_only"]) and not allowlist:
            raise Phase2bPilotError(
                f"Mutable task modified_file_allowlist cannot be empty: {task_id}"
            )
        result.append(PairedTaskSpec(
            task_id=task_id,
            task_set_version=task_set_version,
            source=str(provenance["source_reference"]),
            description=description,
            objective=objective,
            constraints=(
                *constraints,
                *(f"Acceptance criterion: {criterion}" for criterion in acceptance),
            ),
            instruction_language=language,
            repository_code_language=_text(raw, "repository_code_language"),
            repository_doc_language=_enum(raw, "repository_doc_language", {"ko", "en", "mixed", "none"}),
            task_category=category,
            required_capabilities=capabilities,
            risk="low",
            mutation_scope="isolated-checkout-only",
            read_only=bool(raw["read_only"]),
            fixture_paths=fixture_paths,
            fixture_hash=_hash(raw, "fixture_hash"),
            estimated_resource_bucket=bucket,
            evaluator=evaluator,
            modified_file_allowlist=allowlist,
        ))
        repositories[task_id] = repository_id
    if len({item.task_id for item in result}) != 60:
        raise Phase2bPilotError("Phase 2b task IDs must be unique.")
    languages = {key: sum(task.instruction_language == key for task in result) for key in LANGUAGE_QUOTA}
    categories = {key: sum(task.task_category == key for task in result) for key in CATEGORY_QUOTA}
    if languages != LANGUAGE_QUOTA or categories != CATEGORY_QUOTA:
        raise Phase2bPilotError(
            f"Phase 2b fixed quotas are not exact: languages={languages}, categories={categories}"
        )
    return tuple(result), repositories


def _source_provenance(
    raw: Mapping[str, Any],
    *,
    language: str,
    task_author_roles: set[str],
) -> Mapping[str, Any]:
    _exact_keys(raw, {
        "source_kind", "source_reference", "source_revision", "selection_rationale",
        "origin_language", "native_task", "translation_relationship_id",
        "adaptation_history", "license_or_use_basis", "selected_by_role_id", "selected_at",
    }, "source_provenance")
    _enum(raw, "source_kind", {
        "maintainer-authored", "public-issue-derived", "benchmark-adapted", "synthetic-fixture"
    })
    _text(raw, "source_reference")
    _text(raw, "source_revision")
    _text(raw, "selection_rationale")
    _const(raw, "origin_language", language)
    _const(raw, "native_task", True)
    _const(raw, "translation_relationship_id", None)
    _text_tuple(raw, "adaptation_history", nonempty=False)
    _text(raw, "license_or_use_basis")
    selector = _safe_id(raw, "selected_by_role_id")
    if selector not in task_author_roles:
        raise Phase2bPilotError("Source selector is not a declared task author.")
    _timestamp(raw, "selected_at")
    return raw


def _evaluator(
    raw: Mapping[str, Any],
    *,
    task_id: str,
    contract_fields: Mapping[str, tuple[str, ...]],
    evaluator_roles: set[str],
    validity_roles: set[str],
) -> PairedEvaluatorSpec:
    _exact_keys(raw, {
        "evaluator_id", "version", "role", "evaluation_mode", "aggregation", "command",
        "artifact_paths", "artifact_hash", "timeout_seconds", "agent_blind",
        "protected_read_only", "evaluator_author_role_id", "validity_reviewer_role_id",
        "assertion_inventory_complete", "assertion_contracts", "negative_control",
        "positive_control", "validity_review_completed", "validity_reviewed_at",
    }, f"evaluator for {task_id}")
    evaluator_id = _safe_id(raw, "evaluator_id")
    version = _text(raw, "version")
    if not _VERSION.fullmatch(version):
        raise Phase2bPilotError(f"Evaluator version must be a sha256 content version: {task_id}")
    _const(raw, "role", "objective_quality")
    _enum(raw, "evaluation_mode", {
        "deterministic-acceptance-test", "golden-output-or-patch-invariant",
        "property-or-integration-evaluator",
    })
    _const(raw, "aggregation", "binary-single-v1")
    command = _text_tuple(raw, "command", nonempty=True)
    artifact_paths = _relative_paths(raw, "artifact_paths", nonempty=True)
    timeout = _positive_number(raw, "timeout_seconds")
    if timeout > 120:
        raise Phase2bPilotError(f"Evaluator timeout exceeds the medium bucket: {task_id}")
    _const(raw, "agent_blind", True)
    _const(raw, "protected_read_only", True)
    author = _safe_id(raw, "evaluator_author_role_id")
    reviewer = _safe_id(raw, "validity_reviewer_role_id")
    if author not in evaluator_roles or reviewer not in validity_roles:
        raise Phase2bPilotError(f"Evaluator construction role is not declared: {task_id}")
    _const(raw, "assertion_inventory_complete", True)
    assertion_values = _array(raw, "assertion_contracts")
    if not assertion_values:
        raise Phase2bPilotError(f"Evaluator assertion inventory is empty: {task_id}")
    assertions: list[PairedEvaluatorAssertionContract] = []
    for index, item in enumerate(assertion_values):
        assertion = _mapping(item, f"assertion_contracts[{index}]")
        _exact_keys(assertion, {
            "assertion_id", "evaluator_requirement", "task_contract_field",
            "task_contract_text",
        }, f"assertion_contracts[{index}]")
        assertion_id = _safe_id(assertion, "assertion_id")
        field = _enum(assertion, "task_contract_field", set(contract_fields))
        text = _text(assertion, "task_contract_text")
        if not any(text in value for value in contract_fields[field]):
            raise Phase2bPilotError(
                f"Evaluator assertion text is absent from task {field}: {task_id}/{assertion_id}"
            )
        assertions.append(PairedEvaluatorAssertionContract(
            assertion_id=assertion_id,
            evaluator_requirement=_text(assertion, "evaluator_requirement"),
            task_contract_field=field,
            task_contract_text=text,
        ))
    if len({item.assertion_id for item in assertions}) != len(assertions):
        raise Phase2bPilotError(f"Evaluator assertion IDs must be unique: {task_id}")
    mapped_acceptance = {
        item.task_contract_text
        for item in assertions
        if item.task_contract_field == "acceptance_criteria"
    }
    if not set(contract_fields["acceptance_criteria"]).issubset(mapped_acceptance):
        raise Phase2bPilotError(f"Every acceptance criterion must be mapped: {task_id}")
    negative_control_id = _control(_object(raw, "negative_control"), expected=0)
    positive_control_id = _control(_object(raw, "positive_control"), expected=1)
    if negative_control_id == positive_control_id:
        raise Phase2bPilotError(
            f"Positive and negative controls must have distinct IDs: {task_id}"
        )
    _const(raw, "validity_review_completed", True)
    _timestamp(raw, "validity_reviewed_at")
    return PairedEvaluatorSpec(
        evaluator_id=evaluator_id,
        version=version,
        role="quality",
        aggregation="binary-single-v1",
        command=command,
        artifact_paths=artifact_paths,
        artifact_hash=_hash(raw, "artifact_hash"),
        timeout_seconds=timeout,
        assertion_contracts=tuple(assertions),
        assertion_inventory_complete=True,
    )


def _control(raw: Mapping[str, Any], *, expected: int) -> str:
    _exact_keys(raw, {
        "control_id", "description", "expected_quality", "observed_quality",
        "artifact_hash", "completed_at",
    }, "control evidence")
    control_id = _safe_id(raw, "control_id")
    _text(raw, "description")
    _const(raw, "expected_quality", expected)
    _const(raw, "observed_quality", expected)
    _hash(raw, "artifact_hash")
    _timestamp(raw, "completed_at")
    return control_id


def _analysis_plan(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    _exact_keys(raw, {
        "primary_estimand", "primary_population", "reporting_strata",
        "minimum_reporting_cell_size", "pilot_inference_scope", "binary_interval_method",
        "continuous_interval_method", "confidence_level", "decision_margins",
        "secondary_metrics", "missingness", "target_workload_aggregate",
    }, "analysis_plan")
    _const(raw, "primary_estimand", PRIMARY_METRIC)
    _const(raw, "primary_population", "experimental-quota-by-preregistered-stratum")
    _const(raw, "reporting_strata", ["instruction_language", "task_category"])
    if _integer(raw, "minimum_reporting_cell_size") < 4:
        raise Phase2bPilotError("minimum_reporting_cell_size must be at least four.")
    _const(raw, "pilot_inference_scope", INFERENCE_SCOPE)
    _const(raw, "binary_interval_method", "exact-mcnemar-binomial-and-paired-risk-difference-v1")
    _enum(raw, "continuous_interval_method", {"seeded-paired-bootstrap-v1", "exact-paired-permutation-v1"})
    _const(raw, "confidence_level", 0.95)
    margins = _array(raw, "decision_margins")
    if not margins:
        raise Phase2bPilotError("Phase 2b decision margins cannot be empty.")
    for index, item in enumerate(margins):
        margin = _mapping(item, f"decision_margins[{index}]")
        _exact_keys(margin, {"metric", "scope", "value", "rationale", "frozen_before_pilot"}, f"decision_margins[{index}]")
        _text(margin, "metric"); _text(margin, "scope"); _number(margin, "value"); _text(margin, "rationale")
        _const(margin, "frozen_before_pilot", True)
    _const(raw, "secondary_metrics", list(SECONDARY_METRICS))
    missing = _object(raw, "missingness")
    _exact_keys(missing, {"quality", "cost", "terminal", "subjective_disagreement"}, "missingness")
    _const(missing, "quality", "missing-never-impute-zero-or-pass")
    _const(missing, "cost", "unknown-never-impute-zero")
    _const(missing, "terminal", "incomplete-until-reconciled")
    _const(missing, "subjective_disagreement", "not-applicable-primary-objective-evaluators-only")
    _const(raw, "target_workload_aggregate", "not-estimable-without-independent-representative-intake-weights")
    return raw


def _resource_budget(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    _exact_keys(raw, {
        "maximum_executions", "maximum_agent_execution_count",
        "maximum_evaluator_execution_count", "maximum_active_wall_time_seconds",
    }, "maximum_resource_budget")
    for key in ("maximum_executions", "maximum_agent_execution_count", "maximum_evaluator_execution_count"):
        _const(raw, key, 120)
    _positive_number(raw, "maximum_active_wall_time_seconds")
    return raw


def _rules(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    _exact_keys(raw, {"stopping", "pause", "exclusion", "resume"}, "rules")
    for key in ("stopping", "pause", "exclusion"):
        _text_tuple(raw, key, nonempty=True)
    resume = _object(raw, "resume")
    _exact_keys(resume, {
        "retain_finalized_prefix", "run_only_untouched_suffix",
        "preserve_missing_failure_rows", "reject_duplicate_attempt_ids",
    }, "rules.resume")
    for key in resume:
        _const(resume, key, True)
    return raw


def _confirmatory_holdout(raw: Mapping[str, Any]) -> None:
    _exact_keys(raw, {
        "pilot_tasks_reusable", "new_tasks_required", "sample_size_method",
        "sample_size_frozen_before_confirmatory_execution",
    }, "confirmatory_holdout")
    _const(raw, "pilot_tasks_reusable", False)
    _const(raw, "new_tasks_required", True)
    _enum(raw, "sample_size_method", {"conservative-discordance-bound", "preregistered-internal-pilot-reestimation"})
    _const(raw, "sample_size_frozen_before_confirmatory_execution", True)


def _authorization(raw: Mapping[str, Any]) -> None:
    _exact_keys(raw, {
        "manifest_must_be_committed_before_results", "agent_free_validation_required",
        "separate_run_authorization_required", "agent_execution_authorized_by_this_manifest",
    }, "authorization")
    _const(raw, "manifest_must_be_committed_before_results", True)
    _const(raw, "agent_free_validation_required", True)
    _const(raw, "separate_run_authorization_required", True)
    _const(raw, "agent_execution_authorized_by_this_manifest", False)


def _protected_artifact_paths(root: Path, raw_paths: Iterable[str]) -> tuple[Path, ...]:
    candidates = tuple(root / raw for raw in raw_paths)
    if any(candidate.is_symlink() for candidate in candidates):
        raise Phase2bPilotError("Evaluator artifact must not be a symlink.")
    paths = tuple(candidate.resolve(strict=True) for candidate in candidates)
    if any(path == root or not path.is_relative_to(root) for path in paths):
        raise Phase2bPilotError("Evaluator artifact escaped or selected the protected root.")
    return paths


def _fixture_paths(root: Path, raw_paths: Iterable[str]) -> tuple[Path, ...]:
    paths = tuple((root / raw).resolve(strict=True) for raw in raw_paths)
    if any(path != root and not path.is_relative_to(root) for path in paths):
        raise Phase2bPilotError("Fixture path escaped the repository.")
    return paths


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise Phase2bPilotError(f"{label} must be an object.")
    return value


def _object(raw: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    return _mapping(raw.get(key), key)


def _array(raw: Mapping[str, Any], key: str) -> list[Any]:
    value = raw.get(key)
    if not isinstance(value, list):
        raise Phase2bPilotError(f"{key} must be an array.")
    return value


def _exact_keys(raw: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(raw) != expected:
        missing = sorted(expected - set(raw))
        extra = sorted(set(raw) - expected)
        raise Phase2bPilotError(f"{label} fields mismatch; missing={missing}, extra={extra}")


def _text(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise Phase2bPilotError(f"{key} must be non-empty text.")
    return value


def _safe_id(raw: Mapping[str, Any], key: str) -> str:
    value = _text(raw, key)
    if not _SAFE_ID.fullmatch(value):
        raise Phase2bPilotError(f"{key} is not a safe identifier: {value}")
    return value


def _hash(raw: Mapping[str, Any], key: str) -> str:
    value = _text(raw, key)
    if not _HASH.fullmatch(value):
        raise Phase2bPilotError(f"{key} must be a lowercase Git/SHA-256 hash.")
    return value


def _enum(raw: Mapping[str, Any], key: str, allowed: set[str]) -> str:
    value = _text(raw, key)
    if value not in allowed:
        raise Phase2bPilotError(f"{key} must be one of {sorted(allowed)}.")
    return value


def _const(raw: Mapping[str, Any], key: str, expected: Any) -> None:
    if raw.get(key) != expected or isinstance(raw.get(key), bool) != isinstance(expected, bool):
        raise Phase2bPilotError(f"{key} must equal {expected!r}.")


def _integer(raw: Mapping[str, Any], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise Phase2bPilotError(f"{key} must be an integer.")
    return value


def _number(raw: Mapping[str, Any], key: str) -> float:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Phase2bPilotError(f"{key} must be numeric.")
    number = float(value)
    if not math.isfinite(number):
        raise Phase2bPilotError(f"{key} must be finite.")
    return number


def _positive_number(raw: Mapping[str, Any], key: str) -> float:
    value = _number(raw, key)
    if value <= 0:
        raise Phase2bPilotError(f"{key} must be positive.")
    return value


def _text_tuple(raw: Mapping[str, Any], key: str, *, nonempty: bool) -> tuple[str, ...]:
    values = _array(raw, key)
    if nonempty and not values:
        raise Phase2bPilotError(f"{key} cannot be empty.")
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise Phase2bPilotError(f"{key} entries must be non-empty text.")
    return tuple(values)


def _id_tuple(raw: Mapping[str, Any], key: str) -> tuple[str, ...]:
    values = _text_tuple(raw, key, nonempty=True)
    if any(not _SAFE_ID.fullmatch(item) for item in values) or len(values) != len(set(values)):
        raise Phase2bPilotError(f"{key} must contain unique safe identifiers.")
    return values


def _relative_paths(raw: Mapping[str, Any], key: str, *, nonempty: bool) -> tuple[str, ...]:
    values = _text_tuple(raw, key, nonempty=nonempty)
    if len(values) != len(set(values)):
        raise Phase2bPilotError(f"{key} paths must be unique.")
    for value in values:
        path = PurePosixPath(value)
        if (
            value == "."
            or path.as_posix() != value
            or path.is_absolute()
            or ".." in path.parts
            or "\\" in value
            or any(char in value for char in "*?[")
        ):
            raise Phase2bPilotError(f"{key} contains an unsafe relative path: {value}")
    return values


def _timestamp(raw: Mapping[str, Any], key: str) -> str:
    value = _text(raw, key)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Phase2bPilotError(f"{key} must be an ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise Phase2bPilotError(f"{key} must include an explicit UTC offset.")
    return value


def _reject_duplicate_object_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise Phase2bPilotError(f"JSON object contains duplicate key: {key}")
        result[key] = value
    return result
