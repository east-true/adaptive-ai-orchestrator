from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import asdict, replace
from pathlib import Path
from time import monotonic
from typing import Callable

from .agents import Agent, ClaudeCodeAgent, CodexAgent
from .domain import Capability, EvaluatorRole, EvaluatorSpec, EvaluatorStatus, ExecutionStatus, Task
from .events import JsonlEventStore, LifecycleEventType
from .kernel import OrchestratorKernel
from .logging import JsonlExecutionLogger
from .paired_experiment import (
    PAIRED_MANIFEST_SCHEMA,
    PairAssignment,
    PairedAgentSpec,
    PairedExperimentError,
    PairedManifest,
    PairedTaskSpec,
    analyze_paired_observations,
    assign_pairs,
    observations_from_routing_state,
    prepare_paired_workspaces,
)
from .process_runner import ProcessRunner, SubprocessRunner
from .routing_state import LifecycleRecorder
from .verification import CommandVerifier, evaluation_projection


class PairedExecutionError(PairedExperimentError):
    pass


PAIRED_RUN_SCHEMA = "paired-run-v1"


class PairedSmokeRunner:
    """Execute a pre-registered paired manifest with an explicit safety gate."""

    def __init__(
        self,
        manifest: PairedManifest,
        manifest_path: Path,
        source_repository: Path,
        workspace_root: Path,
        control_state_dir: Path,
        *,
        process_runner_factory: Callable[[], ProcessRunner] = SubprocessRunner,
        version_resolver: Callable[[PairedAgentSpec], str] | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.manifest = manifest
        self.manifest_path = manifest_path
        self.source_repository = source_repository
        self.workspace_root = workspace_root
        self.control_state_dir = control_state_dir
        self.process_runner_factory = process_runner_factory
        self.version_resolver = version_resolver or _installed_cli_version
        self.clock = clock

    def run(self, *, confirm_agent_execution: bool = False) -> dict[str, object]:
        if not confirm_agent_execution:
            raise PairedExecutionError(
                "Paired agent execution requires --confirm-agent-execution; dry-run remains agent-free."
            )
        source = self.source_repository.resolve(strict=True)
        workspace_root = self.workspace_root.expanduser().resolve()
        control = self.control_state_dir.expanduser().resolve()
        if control == source or control.is_relative_to(source):
            raise PairedExecutionError("Paired control state must be outside the source repository.")
        if control == workspace_root or control.is_relative_to(workspace_root):
            raise PairedExecutionError("Paired control state must be outside the workspace root.")
        if workspace_root.is_relative_to(control):
            raise PairedExecutionError("Paired workspace root must be outside the control state directory.")
        if workspace_root.exists() and (not workspace_root.is_dir() or any(workspace_root.iterdir())):
            raise PairedExecutionError("Paired workspace root must be a new or empty dedicated directory.")
        if control.exists() and (not control.is_dir() or any(control.iterdir())):
            raise PairedExecutionError("Paired control state must be a new or empty dedicated directory.")

        wall_limit = self.manifest.maximum_resource_budget.get("wall_time_seconds")
        if wall_limit is None:
            raise PairedExecutionError("Paired execution requires a wall_time_seconds resource budget.")
        for budget_name in ("agent_execution_count", "evaluator_execution_count"):
            declared_limit = self.manifest.maximum_resource_budget.get(
                budget_name,
                float(self.manifest.maximum_executions),
            )
            if declared_limit < self.manifest.maximum_executions:
                raise PairedExecutionError(
                    f"{budget_name} budget {declared_limit:g} cannot cover "
                    f"{self.manifest.maximum_executions} preregistered attempts."
                )

        for agent_spec in self.manifest.agents:
            observed_version = self.version_resolver(agent_spec).strip()
            version_pattern = rf"(?<![0-9A-Za-z]){re.escape(agent_spec.cli_version)}(?![0-9A-Za-z])"
            if not re.search(version_pattern, observed_version):
                raise PairedExecutionError(
                    f"CLI version mismatch for {agent_spec.agent_id}: "
                    f"expected {agent_spec.cli_version}, observed {observed_version or '<empty>'}"
                )

        prepared = prepare_paired_workspaces(self.manifest, self.manifest_path, source, workspace_root)
        workspace_by_key = {
            (item["task_id"], item["agent_id"]): Path(item["path"])
            for item in prepared["workspaces"]
        }
        recorder = LifecycleRecorder(JsonlEventStore(control / "events.jsonl"))
        agent_specs = {spec.agent_id: spec for spec in self.manifest.agents}
        agents = {agent_id: _agent_from_spec(spec) for agent_id, spec in agent_specs.items()}
        config_hash = hashlib.sha256(
            json.dumps(self.manifest.as_dict(), sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        deadline = self.clock() + float(wall_limit)
        assignments = assign_pairs(self.manifest)
        completed_attempts = 0
        for assignment in assignments:
            task_spec = next(task for task in self.manifest.tasks if task.task_id == assignment.task_id)
            for agent_id in assignment.agent_order:
                if self.clock() >= deadline:
                    raise PairedExecutionError(
                        f"Paired wall-time budget exhausted after {completed_attempts} of "
                        f"{self.manifest.maximum_executions} attempts."
                    )
                workspace = workspace_by_key[(assignment.task_id, agent_id)]
                self._run_attempt(
                    recorder,
                    agents[agent_id],
                    agent_specs[agent_id],
                    task_spec,
                    assignment,
                    workspace,
                    config_hash,
                    deadline,
                )
                completed_attempts += 1

        state = recorder.rebuild_state()
        observations = observations_from_routing_state(self.manifest, state)
        return {
            "schema_version": PAIRED_RUN_SCHEMA,
            "manifest_schema_version": PAIRED_MANIFEST_SCHEMA,
            "experiment_id": self.manifest.experiment_id,
            "agent_execution_started": True,
            "control_state_dir": str(control),
            "completed_attempts": completed_attempts,
            "prepared": prepared,
            "analysis": analyze_paired_observations(self.manifest, observations),
        }

    def _run_attempt(
        self,
        recorder: LifecycleRecorder,
        agent: Agent,
        agent_spec: PairedAgentSpec,
        task_spec: PairedTaskSpec,
        assignment: PairAssignment,
        workspace: Path,
        config_hash: str,
        deadline: float,
    ) -> None:
        remaining_agent_seconds = max(0.001, deadline - self.clock())
        task = Task(
            task_id=task_spec.task_id,
            description=task_spec.description,
            objective=task_spec.objective,
            constraints=task_spec.constraints,
            required_capabilities=tuple(Capability(item) for item in task_spec.required_capabilities),
            time_limit_seconds=min(agent_spec.time_limit_seconds, remaining_agent_seconds),
            context={
                "paired_experiment_id": self.manifest.experiment_id,
                "pair_id": assignment.pair_id,
                "task_source": task_spec.source,
                "instruction_language": task_spec.instruction_language,
            },
        )
        routing_context = {
            "schema_version": "routing-context-v1",
            "required_capabilities": list(task_spec.required_capabilities),
            "inferred_capabilities": [],
            "task_category": task_spec.task_category,
            "difficulty": 1,
            "risk": 1,
            "uncertainty": 0,
            "instruction_language": task_spec.instruction_language,
            "objective_evaluator_available": True,
            "constraint_evaluator_count": 0,
            "environment_epoch": self.manifest.environment_epoch,
        }
        candidate_probabilities = {
            candidate.agent_id: float(candidate.agent_id == agent.agent_id)
            for candidate in self.manifest.agents
        }
        selection_payload = {
            "policy_name": "paired-smoke",
            "policy_version": "paired-smoke-v1",
            "config_hash": config_hash,
            "selection_mode": "paired_eval",
            "cohort": "paired",
            "context_schema": "routing-context-v1",
            "context_features": routing_context,
            "eligible_candidates": [candidate.agent_id for candidate in self.manifest.agents],
            "ineligible_reasons": {},
            "candidate_probabilities": candidate_probabilities,
            "selected_agent": agent.agent_id,
            "selected_agent_base_id": agent.base_id,
            "selected_probability": 1.0,
            "baseline_candidate": None,
            "random_draw_id": None,
            "pair_id": assignment.pair_id,
            "pair_order_index": assignment.order_index,
            "agent_order_position": assignment.agent_order.index(agent.agent_id),
        }
        kernel = OrchestratorKernel(
            {agent.agent_id: agent},
            JsonlExecutionLogger(workspace / ".orchestrator" / "executions.jsonl"),
            workspace,
            runner=self.process_runner_factory(),
            lifecycle_recorder=recorder,
        )
        record = kernel.execute(
            task,
            agent.agent_id,
            log_execution=False,
            execution_id=assignment.execution_id,
            attempt_id=assignment.attempt_ids[agent.agent_id],
            task_id=task.task_id,
            policy_version="paired-smoke-v1",
            config_hash=config_hash,
            selection_mode="paired_eval",
            cohort="paired",
            routing_evidence_eligible=False,
            selection_payload=selection_payload,
            context_schema="routing-context-v1",
            routing_context=routing_context,
            environment_epoch=self.manifest.environment_epoch,
        )
        remaining_evaluator_seconds = deadline - self.clock()
        if remaining_evaluator_seconds <= 0:
            recorder.record(
                LifecycleEventType.OUTCOME_FINALIZED,
                execution_id=assignment.execution_id,
                task_id=task.task_id,
                attempt_id=assignment.attempt_ids[agent.agent_id],
                payload={
                    "execution_status": record.status.value,
                    "evaluation_projection": {},
                    "routing_evidence_eligible": False,
                    "finalization_reason": "resource_budget_exhausted_before_evaluation",
                },
            )
            raise PairedExecutionError("Paired wall-time budget exhausted before objective evaluation.")
        evaluator = self.manifest_task_evaluator(
            task_spec,
            timeout_seconds=min(task_spec.evaluator.timeout_seconds, remaining_evaluator_seconds),
        )
        verifier = CommandVerifier(evaluator_specs=(evaluator,))
        try:
            verification, evaluations = verifier.verify_with_evaluations(
                task,
                record.status,
                workspace,
                kernel.runner,
            )
        except BaseException as exc:
            recorder.record(
                LifecycleEventType.OUTCOME_FINALIZED,
                execution_id=assignment.execution_id,
                task_id=task.task_id,
                attempt_id=assignment.attempt_ids[agent.agent_id],
                payload={"status": "evaluation_interrupted", "error_type": type(exc).__name__},
            )
            raise

        finalized = replace(
            record,
            verification=verification,
            evaluations=evaluations,
            evaluation_projection=evaluation_projection(evaluations),
            task_analysis={
                "instruction_language": task_spec.instruction_language,
                "task_category": task_spec.task_category,
                "risk": task_spec.risk,
            },
            routing_context=routing_context,
            context_schema="routing-context-v1",
            environment_epoch=self.manifest.environment_epoch,
        )
        for result in evaluations:
            recorder.record(
                LifecycleEventType.EVALUATION_COMPLETED,
                execution_id=assignment.execution_id,
                task_id=task.task_id,
                attempt_id=assignment.attempt_ids[agent.agent_id],
                payload=asdict(result),
            )
        recorder.record(
            LifecycleEventType.OUTCOME_FINALIZED,
            execution_id=assignment.execution_id,
            task_id=task.task_id,
            attempt_id=assignment.attempt_ids[agent.agent_id],
            payload={
                "execution_status": finalized.status.value,
                "verification": asdict(verification),
                "evaluation_projection": finalized.evaluation_projection,
                "routing_evidence_eligible": False,
            },
        )
        kernel.log(finalized)
        if record.status is not ExecutionStatus.COMPLETED:
            raise PairedExecutionError(
                f"Paired execution paused after infrastructure terminal status "
                f"{record.status.value} for {task.task_id}/{agent.agent_id}."
            )
        quality_result = next(result for result in evaluations if result.role is EvaluatorRole.QUALITY)
        if quality_result.status in {EvaluatorStatus.ERROR, EvaluatorStatus.TIMED_OUT, EvaluatorStatus.SKIPPED}:
            raise PairedExecutionError(
                f"Paired execution paused after evaluator status {quality_result.status.value} "
                f"for {task.task_id}/{agent.agent_id}."
            )

    def manifest_task_evaluator(
        self,
        task_spec: PairedTaskSpec,
        *,
        timeout_seconds: float | None = None,
    ) -> EvaluatorSpec:
        artifact_paths = tuple(
            str((self.manifest_path.parent / path).resolve())
            if not Path(path).is_absolute()
            else str(Path(path).expanduser().resolve())
            for path in task_spec.evaluator.artifact_paths
        )
        artifact_path_map = dict(zip(task_spec.evaluator.artifact_paths, artifact_paths, strict=True))
        command = tuple(artifact_path_map.get(token, token) for token in task_spec.evaluator.command)
        return EvaluatorSpec(
            evaluator_id=task_spec.evaluator.evaluator_id,
            version=task_spec.evaluator.version,
            role=EvaluatorRole.QUALITY,
            subject=task_spec.objective,
            command=command,
            timeout_seconds=(
                timeout_seconds
                if timeout_seconds is not None
                else task_spec.evaluator.timeout_seconds
            ),
            evidence_scope="Pre-registered paired task-specific objective quality.",
            artifact_paths=artifact_paths,
        )


def _agent_from_spec(spec: PairedAgentSpec) -> Agent:
    if spec.base_id == "claude-code":
        agent = ClaudeCodeAgent(
            agent_id=spec.agent_id,
            model=spec.model,
            permission_mode=spec.permission_mode,
        )
    elif spec.base_id == "codex":
        agent = CodexAgent(
            agent_id=spec.agent_id,
            model=spec.model,
            reasoning_effort=spec.reasoning_tier,
            sandbox_mode=spec.permission_mode,
        )
    else:  # pragma: no cover - manifest validation rejects unknown bases
        raise PairedExecutionError(f"Unsupported paired agent base: {spec.base_id}")
    if agent.agent_id != spec.agent_id:
        raise PairedExecutionError(f"Agent registry ID mismatch: expected {spec.agent_id}, got {agent.agent_id}")
    return agent


def _installed_cli_version(spec: PairedAgentSpec) -> str:
    executable = "claude" if spec.base_id == "claude-code" else "codex"
    try:
        result = subprocess.run(
            (executable, "--version"),
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PairedExecutionError(f"Unable to resolve {executable} CLI version: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise PairedExecutionError(f"Unable to resolve {executable} CLI version: {detail}")
    return "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
