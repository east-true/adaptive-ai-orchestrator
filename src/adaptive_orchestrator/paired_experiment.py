from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from uuid import NAMESPACE_URL, uuid5

from .domain import Capability
from .routing_state import RoutingState
from .verification import evaluator_content_version, hash_evaluator_artifacts, validate_evaluator_artifacts

PAIRED_MANIFEST_SCHEMA = "paired-smoke-manifest-v1"
PAIRED_ANALYSIS_SCHEMA = "paired-analysis-v1"
ORDER_ASSIGNMENT_RULE = "seeded-balanced-sha256-v1"
QUALITY_AGGREGATION_RULE = "binary-single-v1"
PRIMARY_METRIC = "paired-objective-quality-risk-difference"

_HEX_HASH = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_AGENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_TERMINAL_STATUSES = frozenset({
    "completed", "failed", "timed_out", "spawn_error", "interrupted", "abandoned", "incomplete",
})


class PairedExperimentError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PairedAgentSpec:
    agent_id: str
    base_id: str
    model: str
    reasoning_tier: str | None
    cli_version: str
    permission_mode: str
    time_limit_seconds: float


@dataclass(frozen=True, slots=True)
class PairedEvaluatorSpec:
    evaluator_id: str
    version: str
    role: str
    aggregation: str
    command: tuple[str, ...]
    artifact_paths: tuple[str, ...]
    artifact_hash: str
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class PairedTaskSpec:
    task_id: str
    task_set_version: str
    source: str
    description: str
    objective: str
    constraints: tuple[str, ...]
    instruction_language: str
    repository_code_language: str
    repository_doc_language: str
    task_category: str
    required_capabilities: tuple[str, ...]
    risk: str
    mutation_scope: str
    read_only: bool
    fixture_paths: tuple[str, ...]
    fixture_hash: str
    estimated_resource_bucket: str
    evaluator: PairedEvaluatorSpec


@dataclass(frozen=True, slots=True)
class PairedManifest:
    schema_version: str
    protocol_version: str
    experiment_id: str
    task_set_version: str
    environment_epoch: str
    base_revision: str
    base_tree_hash: str
    random_seed: int
    order_assignment_rule: str
    agents: tuple[PairedAgentSpec, PairedAgentSpec]
    tasks: tuple[PairedTaskSpec, ...]
    primary_metric: str
    secondary_metrics: tuple[str, ...]
    reporting_strata: tuple[str, ...]
    minimum_reporting_cell_size: int
    non_inferiority_margin: float
    confidence_level: float
    interval_method: str
    maximum_executions: int
    maximum_resource_budget: Mapping[str, Any]
    stopping_rules: tuple[str, ...]
    pause_rules: tuple[str, ...]
    exclusion_rules: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PairAssignment:
    order_index: int
    task_id: str
    pair_id: str
    execution_id: str
    agent_order: tuple[str, str]
    attempt_ids: Mapping[str, str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PreparedWorkspace:
    task_id: str
    agent_id: str
    path: str
    commit_hash: str
    tree_hash: str
    clean: bool
    evaluator_id: str
    evaluator_version: str
    evaluator_artifact_hash: str


@dataclass(frozen=True, slots=True)
class PairedAttemptObservation:
    task_id: str
    pair_id: str
    execution_id: str
    attempt_id: str
    agent_id: str
    terminal_status: str
    quality_observed: bool
    quality_score: float | None

    def __post_init__(self) -> None:
        if self.terminal_status not in _TERMINAL_STATUSES:
            raise PairedExperimentError(f"Unsupported terminal status: {self.terminal_status}")
        if self.quality_observed:
            if isinstance(self.quality_score, bool) or self.quality_score not in {0, 0.0, 1, 1.0}:
                raise PairedExperimentError("Observed paired quality must be binary 0 or 1.")
        elif self.quality_score is not None:
            raise PairedExperimentError("Unobserved paired quality cannot carry a score.")


def load_paired_manifest(path: Path) -> PairedManifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PairedExperimentError(f"Unable to read paired manifest {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise PairedExperimentError("Paired manifest must be a JSON object.")
    return paired_manifest_from_dict(raw)


def paired_manifest_from_dict(raw: Mapping[str, Any]) -> PairedManifest:
    schema_version = _required_string(raw, "schema_version")
    if schema_version != PAIRED_MANIFEST_SCHEMA:
        raise PairedExperimentError(f"Unsupported paired manifest schema: {schema_version}")
    task_set_version = _required_string(raw, "task_set_version")
    agents_raw = _required_list(raw, "agents")
    if len(agents_raw) != 2:
        raise PairedExperimentError("Paired smoke requires exactly two agents.")
    agents = (
        _agent_from_dict(_mapping(agents_raw[0], "agent")),
        _agent_from_dict(_mapping(agents_raw[1], "agent")),
    )
    if len({agent.agent_id for agent in agents}) != 2:
        raise PairedExperimentError("Paired agent IDs must be unique.")
    if {agent.base_id for agent in agents} != {"claude-code", "codex"}:
        raise PairedExperimentError("Phase 2a paired smoke requires Claude Code and Codex base agents.")

    tasks_raw = _required_list(raw, "tasks")
    if len(tasks_raw) != 4:
        raise PairedExperimentError("Phase 2a paired smoke requires exactly four tasks.")
    tasks = tuple(_task_from_dict(_mapping(item, "task"), task_set_version) for item in tasks_raw)
    if len({task.task_id for task in tasks}) != len(tasks):
        raise PairedExperimentError("Paired task IDs must be unique.")
    if len({task.evaluator.evaluator_id for task in tasks}) != len(tasks):
        raise PairedExperimentError("Each smoke task requires its own evaluator ID.")

    seed = _required_int(raw, "random_seed")
    assignment_rule = _required_string(raw, "order_assignment_rule")
    if assignment_rule != ORDER_ASSIGNMENT_RULE:
        raise PairedExperimentError(f"Unsupported paired order assignment rule: {assignment_rule}")
    primary_metric = _required_string(raw, "primary_metric")
    if primary_metric != PRIMARY_METRIC:
        raise PairedExperimentError(f"Unsupported Phase 2a primary metric: {primary_metric}")
    reporting_strata = _string_tuple(raw, "reporting_strata", nonempty=True)
    allowed_strata = {"instruction_language", "task_category"}
    if not set(reporting_strata).issubset(allowed_strata):
        raise PairedExperimentError(f"Unsupported reporting strata: {sorted(set(reporting_strata) - allowed_strata)}")
    minimum_cell = _required_int(raw, "minimum_reporting_cell_size")
    if minimum_cell <= 0:
        raise PairedExperimentError("minimum_reporting_cell_size must be positive.")
    confidence = _required_number(raw, "confidence_level")
    if not 0 < confidence < 1:
        raise PairedExperimentError("confidence_level must be between zero and one.")
    maximum_executions = _required_int(raw, "maximum_executions")
    if maximum_executions != len(tasks) * len(agents):
        raise PairedExperimentError("maximum_executions must equal the declared paired task count times two.")
    resource_budget = _resource_budget(raw.get("maximum_resource_budget"))

    return PairedManifest(
        schema_version=schema_version,
        protocol_version=_required_string(raw, "protocol_version"),
        experiment_id=_safe_identifier(raw, "experiment_id"),
        task_set_version=task_set_version,
        environment_epoch=_required_string(raw, "environment_epoch"),
        base_revision=_required_string(raw, "base_revision"),
        base_tree_hash=_required_hash(raw, "base_tree_hash"),
        random_seed=seed,
        order_assignment_rule=assignment_rule,
        agents=agents,
        tasks=tasks,
        primary_metric=primary_metric,
        secondary_metrics=_string_tuple(raw, "secondary_metrics", nonempty=True),
        reporting_strata=reporting_strata,
        minimum_reporting_cell_size=minimum_cell,
        non_inferiority_margin=_required_number(raw, "non_inferiority_margin"),
        confidence_level=confidence,
        interval_method=_required_string(raw, "interval_method"),
        maximum_executions=maximum_executions,
        maximum_resource_budget=resource_budget,
        stopping_rules=_string_tuple(raw, "stopping_rules", nonempty=True),
        pause_rules=_string_tuple(raw, "pause_rules", nonempty=True),
        exclusion_rules=_string_tuple(raw, "exclusion_rules", nonempty=True),
    )


def assign_pairs(manifest: PairedManifest) -> tuple[PairAssignment, ...]:
    """Balanced, deterministic order assignment with stable pair/execution/attempt IDs."""

    ranked = sorted(
        manifest.tasks,
        key=lambda task: hashlib.sha256(
            f"{manifest.random_seed}:{manifest.experiment_id}:{task.task_id}".encode("utf-8")
        ).hexdigest(),
    )
    offset_material = hashlib.sha256(f"{manifest.random_seed}:{manifest.experiment_id}:offset".encode("utf-8")).digest()
    offset = offset_material[0] % 2
    agent_ids = tuple(agent.agent_id for agent in manifest.agents)
    namespace = uuid5(NAMESPACE_URL, f"adaptive-ai-orchestrator:{manifest.experiment_id}")
    assignments: list[PairAssignment] = []
    for order_index, task in enumerate(ranked):
        pair_id = str(uuid5(namespace, f"pair:{task.task_id}"))
        execution_id = str(uuid5(namespace, f"execution:{task.task_id}"))
        first_index = (order_index + offset) % 2
        agent_order = (agent_ids[first_index], agent_ids[1 - first_index])
        assignments.append(PairAssignment(
            order_index=order_index,
            task_id=task.task_id,
            pair_id=pair_id,
            execution_id=execution_id,
            agent_order=agent_order,
            attempt_ids={
                agent_id: str(uuid5(namespace, f"attempt:{task.task_id}:{agent_id}"))
                for agent_id in agent_ids
            },
        ))
    return tuple(assignments)


def validate_paired_environment(manifest: PairedManifest, manifest_path: Path, source_repository: Path) -> dict[str, Any]:
    source = source_repository.resolve(strict=True)
    repository_root = Path(_git(source, "rev-parse", "--show-toplevel")).resolve(strict=True)
    if repository_root != source:
        raise PairedExperimentError(f"source_repository must be the Git repository root: {repository_root}")
    if _git(source, "status", "--porcelain", "--untracked-files=all"):
        raise PairedExperimentError(f"Source repository must be clean before paired preparation: {source}")
    commit_hash = _git(source, "rev-parse", f"{manifest.base_revision}^{{commit}}")
    head_hash = _git(source, "rev-parse", "HEAD")
    if head_hash != commit_hash:
        raise PairedExperimentError(
            f"Source HEAD must equal the manifest base revision: expected {commit_hash}, got {head_hash}"
        )
    tree_hash = _git(source, "rev-parse", f"{commit_hash}^{{tree}}")
    if tree_hash != manifest.base_tree_hash:
        raise PairedExperimentError(
            f"Manifest base_tree_hash does not match {manifest.base_revision}: expected {manifest.base_tree_hash}, got {tree_hash}"
        )

    artifact_hashes: dict[str, str] = {}
    fixture_hashes: dict[str, str] = {}
    for task in manifest.tasks:
        artifact_paths = _resolve_manifest_paths(manifest_path, task.evaluator.artifact_paths)
        validate_evaluator_artifacts(tuple(str(path) for path in artifact_paths), source)
        artifact_hash = hash_evaluator_artifacts(tuple(str(path) for path in artifact_paths))
        if artifact_hash != task.evaluator.artifact_hash:
            raise PairedExperimentError(f"Evaluator artifact hash changed for task {task.task_id}.")
        version = evaluator_content_version(task.evaluator.command, tuple(str(path) for path in artifact_paths))
        if version != task.evaluator.version:
            raise PairedExperimentError(f"Evaluator version does not match command/artifact content for task {task.task_id}.")
        if not _command_references_artifact(task.evaluator.command, task.evaluator.artifact_paths, artifact_paths):
            raise PairedExperimentError(f"Evaluator command must reference a protected artifact for task {task.task_id}.")
        artifact_hashes[task.task_id] = artifact_hash

        fixture_paths = _resolve_fixture_paths(source, task.fixture_paths)
        fixture_hash = hash_evaluator_artifacts(tuple(str(path) for path in fixture_paths))
        if fixture_hash != task.fixture_hash:
            raise PairedExperimentError(f"Fixture hash changed for task {task.task_id}.")
        fixture_hashes[task.task_id] = fixture_hash

    return {
        "commit_hash": commit_hash,
        "tree_hash": tree_hash,
        "artifact_hashes": artifact_hashes,
        "fixture_hashes": fixture_hashes,
    }


def prepare_paired_workspaces(
    manifest: PairedManifest,
    manifest_path: Path,
    source_repository: Path,
    workspace_root: Path,
) -> dict[str, Any]:
    """Create detached, clean worktrees only; no coding agent is invoked."""

    source = source_repository.resolve(strict=True)
    root = workspace_root.expanduser().resolve()
    if root == source or root.is_relative_to(source):
        raise PairedExperimentError("Paired workspace root must be outside the source repository.")
    environment = validate_paired_environment(manifest, manifest_path, source)
    assignments = assign_pairs(manifest)
    task_by_id = {task.task_id: task for task in manifest.tasks}
    experiment_root = root / _path_component(manifest.experiment_id)
    planned: list[tuple[PairAssignment, str, Path]] = []
    for assignment in assignments:
        for agent_id in assignment.agent_order:
            target = experiment_root / _path_component(assignment.task_id) / _path_component(agent_id)
            if target.exists():
                raise PairedExperimentError(f"Paired workspace target already exists: {target}")
            if target == source or target.is_relative_to(source):
                raise PairedExperimentError(f"Paired workspace target must be isolated from source: {target}")
            planned.append((assignment, agent_id, target))

    created: list[Path] = []
    prepared: list[PreparedWorkspace] = []
    try:
        for assignment, agent_id, target in planned:
            target.parent.mkdir(parents=True, exist_ok=True)
            _git(source, "worktree", "add", "--detach", str(target), environment["commit_hash"])
            created.append(target)
            commit_hash = _git(target, "rev-parse", "HEAD")
            tree_hash = _git(target, "rev-parse", "HEAD^{tree}")
            clean = not bool(_git(target, "status", "--porcelain", "--untracked-files=all"))
            if commit_hash != environment["commit_hash"] or tree_hash != environment["tree_hash"] or not clean:
                raise PairedExperimentError(f"Prepared workspace failed base integrity validation: {target}")
            task = task_by_id[assignment.task_id]
            fixture_hash = hash_evaluator_artifacts(tuple(
                str(path) for path in _resolve_fixture_paths(target, task.fixture_paths)
            ))
            if fixture_hash != task.fixture_hash:
                raise PairedExperimentError(f"Prepared workspace fixture hash mismatch: {target}")
            prepared.append(PreparedWorkspace(
                task_id=assignment.task_id,
                agent_id=agent_id,
                path=str(target),
                commit_hash=commit_hash,
                tree_hash=tree_hash,
                clean=clean,
                evaluator_id=task.evaluator.evaluator_id,
                evaluator_version=task.evaluator.version,
                evaluator_artifact_hash=task.evaluator.artifact_hash,
            ))
    except BaseException:
        for target in reversed(created):
            subprocess.run(
                ("git", "-C", str(source), "worktree", "remove", "--force", str(target)),
                check=False,
                capture_output=True,
                text=True,
            )
        raise

    return {
        "schema_version": PAIRED_MANIFEST_SCHEMA,
        "experiment_id": manifest.experiment_id,
        "agent_execution_started": False,
        "source_commit_hash": environment["commit_hash"],
        "source_tree_hash": environment["tree_hash"],
        "base_hashes_identical": len({workspace.tree_hash for workspace in prepared}) == 1,
        "assignment_rule": manifest.order_assignment_rule,
        "assignments": [assignment.as_dict() for assignment in assignments],
        "workspaces": [asdict(workspace) for workspace in prepared],
    }


def observations_from_routing_state(
    manifest: PairedManifest,
    state: RoutingState,
) -> tuple[PairedAttemptObservation, ...]:
    observations: list[PairedAttemptObservation] = []
    task_by_id = {task.task_id: task for task in manifest.tasks}
    known_agents = {agent.agent_id for agent in manifest.agents}
    for assignment in assign_pairs(manifest):
        execution = state.executions.get(assignment.execution_id)
        if execution is not None:
            present_attempts = {
                agent_id: execution.attempts[assignment.attempt_ids[agent_id]]
                for agent_id in assignment.agent_order
                if assignment.attempt_ids[agent_id] in execution.attempts
            }
            if len(present_attempts) == 2:
                recorded_order = tuple(
                    agent_id for agent_id, _ in sorted(
                        present_attempts.items(), key=lambda item: item[1].selection_sequence
                    )
                )
                if recorded_order != assignment.agent_order:
                    raise PairedExperimentError(f"Paired execution order mismatch for task {assignment.task_id}.")
        for agent_id in assignment.agent_order:
            attempt_id = assignment.attempt_ids[agent_id]
            if execution is None or attempt_id not in execution.attempts:
                observations.append(PairedAttemptObservation(
                    assignment.task_id, assignment.pair_id, assignment.execution_id, attempt_id,
                    agent_id, "incomplete", False, None,
                ))
                continue
            attempt = execution.attempts[attempt_id]
            selection = attempt.selection
            if selection.get("cohort") != "paired" or selection.get("selection_mode") != "paired_eval":
                raise PairedExperimentError(f"Attempt is not declared paired evidence: {attempt_id}")
            if selection.get("selected_agent") != agent_id:
                raise PairedExperimentError(f"Paired selected agent mismatch for attempt {attempt_id}.")
            if (
                selection.get("pair_id") != assignment.pair_id
                or selection.get("pair_order_index") != assignment.order_index
                or selection.get("agent_order_position") != assignment.agent_order.index(agent_id)
            ):
                raise PairedExperimentError(f"Paired order assignment metadata mismatch: {attempt_id}")
            if selection.get("context_features", {}).get("environment_epoch") != manifest.environment_epoch:
                raise PairedExperimentError(f"Environment epoch mismatch for paired attempt {attempt_id}.")
            probabilities = selection.get("candidate_probabilities") or {}
            if set(probabilities) != known_agents or probabilities.get(agent_id) != 1.0 or any(
                probability != float(candidate == agent_id) for candidate, probability in probabilities.items()
            ):
                raise PairedExperimentError(f"Paired attempt propensity contract mismatch: {attempt_id}")
            if execution.task_id != assignment.task_id or attempt.task_id != assignment.task_id:
                raise PairedExperimentError(f"Paired task identity mismatch for attempt {attempt_id}.")
            if attempt.status != "finalized":
                observations.append(PairedAttemptObservation(
                    assignment.task_id, assignment.pair_id, assignment.execution_id, attempt_id,
                    agent_id, "incomplete", False, None,
                ))
                continue

            terminal_status = str(attempt.terminal.get("status") or attempt.outcome.get("execution_status") or "incomplete")
            task = task_by_id[assignment.task_id]
            quality = [result for result in attempt.evaluations if result.get("role") == "quality"]
            if any(result.get("evaluator_id") != task.evaluator.evaluator_id for result in quality):
                raise PairedExperimentError(f"Unexpected quality evaluator for paired attempt {attempt_id}.")
            if len(quality) > 1:
                raise PairedExperimentError(f"Multiple quality results violate binary-single aggregation: {attempt_id}")
            observed = False
            score: float | None = None
            if quality:
                result = quality[0]
                if result.get("version") != task.evaluator.version:
                    raise PairedExperimentError(f"Evaluator version mismatch for paired attempt {attempt_id}.")
                if result.get("artifact_hash_expected") != task.evaluator.artifact_hash:
                    raise PairedExperimentError(f"Evaluator artifact pin mismatch for paired attempt {attempt_id}.")
                if result.get("observed") is True:
                    if result.get("artifact_integrity_verified") is not True:
                        raise PairedExperimentError(f"Observed quality lacks verified evaluator integrity: {attempt_id}")
                    if result.get("artifact_hash_before") != task.evaluator.artifact_hash or result.get("artifact_hash_after") != task.evaluator.artifact_hash:
                        raise PairedExperimentError(f"Evaluator artifact changed for paired attempt {attempt_id}.")
                    observed = True
                    score = result.get("score")
            observations.append(PairedAttemptObservation(
                assignment.task_id,
                assignment.pair_id,
                assignment.execution_id,
                attempt_id,
                agent_id,
                terminal_status,
                observed,
                score,
            ))
    return tuple(observations)


def analyze_paired_observations(
    manifest: PairedManifest,
    observations: Sequence[PairedAttemptObservation],
) -> dict[str, Any]:
    assignments = assign_pairs(manifest)
    expected = {
        (assignment.task_id, agent_id): (
            assignment.pair_id,
            assignment.execution_id,
            assignment.attempt_ids[agent_id],
        )
        for assignment in assignments
        for agent_id in assignment.agent_order
    }
    indexed: dict[tuple[str, str], PairedAttemptObservation] = {}
    for observation in observations:
        key = (observation.task_id, observation.agent_id)
        if key not in expected:
            raise PairedExperimentError(f"Unexpected paired observation: {key}")
        if key in indexed:
            raise PairedExperimentError(f"Duplicate paired observation: {key}")
        if (observation.pair_id, observation.execution_id, observation.attempt_id) != expected[key]:
            raise PairedExperimentError(f"Deterministic paired identity mismatch: {key}")
        indexed[key] = observation

    agent_by_base = {agent.base_id: agent.agent_id for agent in manifest.agents}
    claude_id = agent_by_base["claude-code"]
    codex_id = agent_by_base["codex"]
    task_by_id = {task.task_id: task for task in manifest.tasks}
    pair_rows: list[dict[str, Any]] = []
    for assignment in assignments:
        claude = indexed.get((assignment.task_id, claude_id))
        codex = indexed.get((assignment.task_id, codex_id))
        pair_status = _pair_status(claude, codex)
        pair_rows.append({
            "task_id": assignment.task_id,
            "pair_id": assignment.pair_id,
            "pair_status": pair_status,
            "instruction_language": task_by_id[assignment.task_id].instruction_language,
            "task_category": task_by_id[assignment.task_id].task_category,
            "claude_quality": claude.quality_score if claude and claude.quality_observed else None,
            "codex_quality": codex.quality_score if codex and codex.quality_observed else None,
            "claude_terminal_status": claude.terminal_status if claude else "incomplete",
            "codex_terminal_status": codex.terminal_status if codex else "incomplete",
        })

    overall = _summarize_pairs(pair_rows, manifest.minimum_reporting_cell_size)
    strata: dict[str, dict[str, Any]] = {}
    for stratum in manifest.reporting_strata:
        strata[stratum] = {}
        values = sorted({str(row[stratum]) for row in pair_rows})
        for value in values:
            rows = [row for row in pair_rows if row[stratum] == value]
            strata[stratum][value] = _summarize_pairs(rows, manifest.minimum_reporting_cell_size)
    return {
        "schema_version": PAIRED_ANALYSIS_SCHEMA,
        "experiment_id": manifest.experiment_id,
        "primary_metric": manifest.primary_metric,
        "pair_count": len(pair_rows),
        "pairs": pair_rows,
        "overall_quota_diagnostic_not_workload_value": overall,
        "strata": strata,
        "promotion_allowed": False,
        "promotion_blockers": [
            "phase2a_pipeline_only",
            "confidence_interval_and_confirmatory_threshold_not_implemented",
            "target_workload_weights_unavailable",
        ],
    }


def _summarize_pairs(rows: Sequence[Mapping[str, Any]], minimum_cell_size: int) -> dict[str, Any]:
    table = {"claude_pass_codex_pass": 0, "claude_pass_codex_fail": 0, "claude_fail_codex_pass": 0, "claude_fail_codex_fail": 0}
    binary_rows = [row for row in rows if row["claude_quality"] in {0, 0.0, 1, 1.0} and row["codex_quality"] in {0, 0.0, 1, 1.0}]
    for row in binary_rows:
        claude_pass = float(row["claude_quality"]) == 1.0
        codex_pass = float(row["codex_quality"]) == 1.0
        key = (
            "claude_pass_codex_pass" if claude_pass and codex_pass
            else "claude_pass_codex_fail" if claude_pass
            else "claude_fail_codex_pass" if codex_pass
            else "claude_fail_codex_fail"
        )
        table[key] += 1
    n = len(binary_rows)
    risk_difference = (table["claude_pass_codex_fail"] - table["claude_fail_codex_pass"]) / n if n else None
    return {
        "pair_count": len(rows),
        "pair_status_counts": {
            status: sum(row["pair_status"] == status for row in rows)
            for status in ("complete", "one-sided failure", "incomplete")
        },
        "binary_observed_pair_count": n,
        "quality_missing_pair_count": len(rows) - n,
        "table_2x2": table,
        "claude_win_tie_loss": {
            "win": table["claude_pass_codex_fail"],
            "tie": table["claude_pass_codex_pass"] + table["claude_fail_codex_fail"],
            "loss": table["claude_fail_codex_pass"],
        },
        "paired_risk_difference": risk_difference,
        "reporting_status": "estimable" if n >= minimum_cell_size else "insufficient_data",
        "preferred_agent": None,
        "ranking_withheld_reason": "Phase 2a validates the pipeline; it does not promote or rank a policy.",
    }


def _pair_status(
    first: PairedAttemptObservation | None,
    second: PairedAttemptObservation | None,
) -> str:
    if first is None or second is None or first.terminal_status == "incomplete" or second.terminal_status == "incomplete":
        return "incomplete"
    completed = (first.terminal_status == "completed", second.terminal_status == "completed")
    if completed[0] != completed[1] or first.quality_observed != second.quality_observed:
        return "one-sided failure"
    return "complete"


def _agent_from_dict(raw: Mapping[str, Any]) -> PairedAgentSpec:
    time_limit = _required_number(raw, "time_limit_seconds")
    if time_limit <= 0:
        raise PairedExperimentError("Agent time_limit_seconds must be positive.")
    base_id = _required_string(raw, "base_id")
    reasoning_tier = _optional_string(raw.get("reasoning_tier"), "reasoning_tier")
    if base_id == "codex" and reasoning_tier is None:
        raise PairedExperimentError("Codex paired agent requires an exact reasoning_tier.")
    return PairedAgentSpec(
        agent_id=_agent_identifier(raw, "agent_id"),
        base_id=base_id,
        model=_required_string(raw, "model"),
        reasoning_tier=reasoning_tier,
        cli_version=_required_string(raw, "cli_version"),
        permission_mode=_required_string(raw, "permission_mode"),
        time_limit_seconds=time_limit,
    )


def _task_from_dict(raw: Mapping[str, Any], expected_task_set_version: str) -> PairedTaskSpec:
    task_set_version = _required_string(raw, "task_set_version")
    if task_set_version != expected_task_set_version:
        raise PairedExperimentError("Task task_set_version must match the manifest.")
    language = _required_string(raw, "instruction_language")
    if language not in {"ko", "en", "mixed"}:
        raise PairedExperimentError(f"Unsupported instruction language: {language}")
    risk = _required_string(raw, "risk")
    if risk != "low":
        raise PairedExperimentError("Phase 2a smoke admits low-risk tasks only.")
    capabilities = _string_tuple(raw, "required_capabilities")
    try:
        tuple(Capability(item) for item in capabilities)
    except ValueError as exc:
        raise PairedExperimentError(f"Unknown required capability: {exc}") from exc
    fixture_paths = _string_tuple(raw, "fixture_paths", nonempty=True)
    for path in fixture_paths:
        candidate = Path(path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise PairedExperimentError("Fixture paths must be repository-relative without '..'.")
    read_only = raw.get("read_only")
    if not isinstance(read_only, bool):
        raise PairedExperimentError("Task read_only must be boolean.")
    return PairedTaskSpec(
        task_id=_safe_identifier(raw, "task_id"),
        task_set_version=task_set_version,
        source=_required_string(raw, "source"),
        description=_required_string(raw, "description"),
        objective=_required_string(raw, "objective"),
        constraints=_string_tuple(raw, "constraints"),
        instruction_language=language,
        repository_code_language=_required_string(raw, "repository_code_language"),
        repository_doc_language=_required_string(raw, "repository_doc_language"),
        task_category=_required_string(raw, "task_category"),
        required_capabilities=capabilities,
        risk=risk,
        mutation_scope=_required_string(raw, "mutation_scope"),
        read_only=read_only,
        fixture_paths=fixture_paths,
        fixture_hash=_required_hash(raw, "fixture_hash"),
        estimated_resource_bucket=_required_string(raw, "estimated_resource_bucket"),
        evaluator=_evaluator_from_dict(_mapping(raw.get("evaluator"), "evaluator")),
    )


def _evaluator_from_dict(raw: Mapping[str, Any]) -> PairedEvaluatorSpec:
    role = _required_string(raw, "role")
    if role != "quality":
        raise PairedExperimentError("Paired primary evaluators must have role 'quality'.")
    aggregation = _required_string(raw, "aggregation")
    if aggregation != QUALITY_AGGREGATION_RULE:
        raise PairedExperimentError(f"Unsupported paired evaluator aggregation: {aggregation}")
    timeout = _required_number(raw, "timeout_seconds")
    if timeout <= 0:
        raise PairedExperimentError("Evaluator timeout_seconds must be positive.")
    return PairedEvaluatorSpec(
        evaluator_id=_safe_identifier(raw, "evaluator_id"),
        version=_required_string(raw, "version"),
        role=role,
        aggregation=aggregation,
        command=_string_tuple(raw, "command", nonempty=True),
        artifact_paths=_string_tuple(raw, "artifact_paths", nonempty=True),
        artifact_hash=_required_hash(raw, "artifact_hash"),
        timeout_seconds=timeout,
    )


def _git(repository: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            ("git", "-C", str(repository), *arguments),
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise PairedExperimentError(f"Unable to invoke git: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
        raise PairedExperimentError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout.strip()


def _resolve_manifest_paths(manifest_path: Path, raw_paths: Iterable[str]) -> tuple[Path, ...]:
    base = manifest_path.expanduser().resolve().parent
    return tuple((Path(path).expanduser() if Path(path).expanduser().is_absolute() else base / path).resolve(strict=True) for path in raw_paths)


def _resolve_fixture_paths(source: Path, raw_paths: Iterable[str]) -> tuple[Path, ...]:
    paths = tuple((source / path).resolve(strict=True) for path in raw_paths)
    if any(path != source and not path.is_relative_to(source) for path in paths):
        raise PairedExperimentError("Fixture path escaped the source repository.")
    return paths


def _command_references_artifact(command: Sequence[str], raw_paths: Sequence[str], resolved_paths: Sequence[Path]) -> bool:
    candidates = {str(path) for path in resolved_paths} | set(raw_paths)
    return any(token in candidates for token in command)


def _path_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", value)


def _required_string(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PairedExperimentError(f"{key} must be a non-empty string.")
    return value


def _safe_identifier(raw: Mapping[str, Any], key: str) -> str:
    value = _required_string(raw, key)
    if not _SAFE_ID.fullmatch(value):
        raise PairedExperimentError(f"{key} contains unsupported characters: {value}")
    return value


def _agent_identifier(raw: Mapping[str, Any], key: str) -> str:
    value = _required_string(raw, key)
    if not _AGENT_ID.fullmatch(value):
        raise PairedExperimentError(f"{key} contains unsupported characters: {value}")
    return value


def _required_hash(raw: Mapping[str, Any], key: str) -> str:
    value = _required_string(raw, key)
    if not _HEX_HASH.fullmatch(value):
        raise PairedExperimentError(f"{key} must be a lowercase hexadecimal SHA hash.")
    return value


def _required_int(raw: Mapping[str, Any], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise PairedExperimentError(f"{key} must be an integer.")
    return value


def _required_number(raw: Mapping[str, Any], key: str) -> float:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PairedExperimentError(f"{key} must be numeric.")
    return float(value)


def _required_list(raw: Mapping[str, Any], key: str) -> list[Any]:
    value = raw.get(key)
    if not isinstance(value, list):
        raise PairedExperimentError(f"{key} must be a list.")
    return value


def _string_tuple(raw: Mapping[str, Any], key: str, *, nonempty: bool = False) -> tuple[str, ...]:
    value = raw.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise PairedExperimentError(f"{key} must be a list of non-empty strings.")
    if nonempty and not value:
        raise PairedExperimentError(f"{key} must not be empty.")
    return tuple(value)


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PairedExperimentError(f"{label} must be an object.")
    return value


def _optional_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise PairedExperimentError(f"{label} must be null or a non-empty string.")
    return value


def _resource_budget(value: Any) -> dict[str, float]:
    raw = _mapping(value, "maximum_resource_budget")
    if not raw:
        raise PairedExperimentError("maximum_resource_budget must not be empty.")
    budget: dict[str, float] = {}
    for key, limit in raw.items():
        if not isinstance(key, str) or not key.strip():
            raise PairedExperimentError("Resource budget keys must be non-empty strings.")
        if isinstance(limit, bool) or not isinstance(limit, (int, float)) or not math.isfinite(float(limit)) or float(limit) <= 0:
            raise PairedExperimentError(f"Resource budget limit must be a positive finite number: {key}")
        budget[key] = float(limit)
    return budget
