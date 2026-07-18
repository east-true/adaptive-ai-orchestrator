from __future__ import annotations

import hashlib
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from .agents import Agent
from .domain import ExecutionRecord, ExecutionStatus, Task
from .events import JsonlEventStore, LifecycleEvent, LifecycleEventType
from .git_snapshot import GitSnapshot
from .process_runner import ProcessRunner, SubprocessRunner
from .routing_state import LifecycleRecorder


class ExecutionLogger(Protocol):
    def write(self, record: ExecutionRecord) -> None: ...


_UNROUTED_CONFIG_HASH = hashlib.sha256(b'{"selector":"unrouted-manual"}').hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class OrchestratorKernel:
    """Single-agent-first coordinator for CLI coding agents."""

    def __init__(
        self,
        agents: dict[str, Agent],
        logger: ExecutionLogger,
        workspace: Path,
        runner: ProcessRunner | None = None,
        git_snapshot: GitSnapshot | None = None,
        include_git_diff: bool = False,
        lifecycle_recorder: LifecycleRecorder | None = None,
    ) -> None:
        self._agents = agents
        self._logger = logger
        self._workspace = workspace.resolve()
        self._runner = runner or SubprocessRunner()
        self._git_snapshot = git_snapshot or GitSnapshot()
        self._include_git_diff = include_git_diff
        self._lifecycle = lifecycle_recorder or LifecycleRecorder(JsonlEventStore(self._workspace / ".orchestrator" / "events.jsonl"))

    def execute(
        self,
        task: Task,
        agent_id: str,
        log_execution: bool = True,
        *,
        execution_id: str | None = None,
        attempt_id: str | None = None,
        task_id: str | None = None,
        parent_attempt_id: str | None = None,
        policy_version: str = "unrouted-manual",
        config_hash: str = _UNROUTED_CONFIG_HASH,
        selection_mode: str = "manual",
        cohort: str = "manual",
        routing_evidence_eligible: bool = False,
        escalation_reasons: tuple[str, ...] = (),
        trigger_classes: tuple[str, ...] = (),
        selection_payload: dict[str, object] | None = None,
        context_schema: str | None = None,
        routing_context: dict[str, object] | None = None,
        environment_epoch: str | None = None,
    ) -> ExecutionRecord:
        if agent_id not in self._agents:
            raise KeyError(f"Unknown agent: {agent_id}")
        agent = self._agents[agent_id]
        execution_id = execution_id or str(uuid4())
        attempt_id = attempt_id or str(uuid4())
        task_id = task_id or task.task_id or str(uuid4())
        occurred_at = _utc_now()
        prompt = ""
        command: tuple[str, ...] = ()
        terminal_recorded = False
        selection = {
            "policy_name": "unrouted-manual",
            "policy_version": policy_version,
            "config_hash": config_hash,
            "selection_mode": selection_mode,
            "cohort": cohort,
            "context_schema": "task-v1",
            "context_features": {},
            "eligible_candidates": [agent.agent_id],
            "ineligible_reasons": {
                candidate_id: "manual_selection_override"
                for candidate_id in self._agents
                if candidate_id != agent.agent_id
            },
            "candidate_probabilities": {
                candidate_id: float(candidate_id == agent.agent_id)
                for candidate_id in self._agents
            },
            "selected_agent": agent.agent_id,
            "selected_agent_base_id": agent.base_id,
            "selected_probability": 1.0,
            "baseline_candidate": agent.agent_id,
            "random_draw_id": None,
        }
        if selection_payload:
            selection.update(selection_payload)
        self.record_lifecycle(
            LifecycleEventType.SELECTION_MADE,
            execution_id=execution_id,
            task_id=task_id,
            attempt_id=attempt_id,
            parent_attempt_id=parent_attempt_id,
            payload=selection,
        )
        self.record_lifecycle(
            LifecycleEventType.EXECUTION_STARTED,
            execution_id=execution_id,
            task_id=task_id,
            attempt_id=attempt_id,
            parent_attempt_id=parent_attempt_id,
            payload={
                "agent_id": agent.agent_id,
                "agent_base_id": agent.base_id,
                "workspace": str(self._workspace),
                "time_limit_seconds": task.time_limit_seconds,
                "owner_pid": os.getpid(),
                "owner_host": socket.gethostname(),
            },
        )
        try:
            run = agent.execute(task, self._workspace, self._runner)
            prompt, process, command = run.prompt, run.process, tuple(run.process.command)
            self.record_lifecycle(
                LifecycleEventType.EXECUTION_TERMINAL,
                execution_id=execution_id,
                task_id=task_id,
                attempt_id=attempt_id,
                parent_attempt_id=parent_attempt_id,
                payload={
                    "status": process.status.value,
                    "exit_code": process.exit_code,
                    "duration_ms": process.duration_ms,
                    "command": list(command),
                },
            )
            terminal_recorded = True
            changes = self._git_snapshot.collect(self._workspace)
            error = process.stderr or None if process.status is not ExecutionStatus.COMPLETED else None
            result, metadata = agent.parse_result(process.stdout or "")
            record = ExecutionRecord(
                task=task,
                agent_id=agent.agent_id,
                prompt=prompt,
                command=command,
                status=process.status,
                result=result,
                error=error,
                exit_code=process.exit_code,
                duration_ms=process.duration_ms,
                workspace_modified_files=changes.modified_files,
                workspace_git_diff=changes.git_diff if self._include_git_diff else None,
                metadata=metadata,
                agent_base_id=agent.base_id,
                execution_id=execution_id,
                attempt_id=attempt_id,
                parent_attempt_id=parent_attempt_id,
                occurred_at=occurred_at,
                policy_version=policy_version,
                config_hash=config_hash,
                selection_mode=selection_mode,
                cohort=cohort,
                routing_evidence_eligible=routing_evidence_eligible,
                escalation_reasons=escalation_reasons,
                trigger_classes=trigger_classes,
                task_id=task_id,
                context_schema=context_schema,
                routing_context=routing_context or {},
                environment_epoch=environment_epoch,
            )
        except Exception as exc:
            if not terminal_recorded:
                self.record_lifecycle(
                    LifecycleEventType.EXECUTION_TERMINAL,
                    execution_id=execution_id,
                    task_id=task_id,
                    attempt_id=attempt_id,
                    parent_attempt_id=parent_attempt_id,
                    payload={"status": "failed", "error_type": type(exc).__name__, "error": str(exc)},
                )
            record = ExecutionRecord(
                task=task,
                agent_id=agent.agent_id,
                prompt=prompt,
                command=command,
                status=ExecutionStatus.FAILED,
                result=None,
                error=str(exc),
                exit_code=None,
                duration_ms=0,
                agent_base_id=agent.base_id,
                execution_id=execution_id,
                attempt_id=attempt_id,
                parent_attempt_id=parent_attempt_id,
                occurred_at=occurred_at,
                policy_version=policy_version,
                config_hash=config_hash,
                selection_mode=selection_mode,
                cohort=cohort,
                routing_evidence_eligible=routing_evidence_eligible,
                escalation_reasons=escalation_reasons,
                trigger_classes=trigger_classes,
                task_id=task_id,
                context_schema=context_schema,
                routing_context=routing_context or {},
                environment_epoch=environment_epoch,
            )
        except BaseException as exc:
            if not terminal_recorded:
                self.record_lifecycle(
                    LifecycleEventType.EXECUTION_TERMINAL,
                    execution_id=execution_id,
                    task_id=task_id,
                    attempt_id=attempt_id,
                    parent_attempt_id=parent_attempt_id,
                    payload={"status": "interrupted", "error_type": type(exc).__name__},
                )
            self.record_lifecycle(
                LifecycleEventType.OUTCOME_FINALIZED,
                execution_id=execution_id,
                task_id=task_id,
                attempt_id=attempt_id,
                parent_attempt_id=parent_attempt_id,
                payload={"status": "interrupted", "error_type": type(exc).__name__},
            )
            raise
        if log_execution:
            self._logger.write(record)
            self.record_lifecycle(
                LifecycleEventType.OUTCOME_FINALIZED,
                execution_id=execution_id,
                task_id=task_id,
                attempt_id=attempt_id,
                parent_attempt_id=parent_attempt_id,
                payload={
                    "execution_status": record.status.value,
                    "verification_status": None,
                    "routing_evidence_eligible": record.routing_evidence_eligible,
                },
            )
        return record

    def log(self, record: ExecutionRecord) -> None:
        self._logger.write(record)

    def record_lifecycle(self, event_type: LifecycleEventType, **kwargs: object) -> LifecycleEvent:
        return self._lifecycle.record(event_type, **kwargs)

    @property
    def agents(self) -> tuple[Agent, ...]:
        return tuple(self._agents.values())

    @property
    def workspace(self) -> Path:
        return self._workspace

    @property
    def runner(self) -> ProcessRunner:
        return self._runner
