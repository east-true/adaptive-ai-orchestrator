from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from .agents import Agent
from .domain import ExecutionRecord, ExecutionStatus, Task
from .git_snapshot import GitSnapshot
from .process_runner import ProcessRunner, SubprocessRunner


class ExecutionLogger(Protocol):
    def write(self, record: ExecutionRecord) -> None: ...


_UNROUTED_CONFIG_HASH = hashlib.sha256(b'{"selector":"unrouted-manual"}').hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class OrchestratorKernel:
    """Single-agent-first coordinator for CLI coding agents."""

    def __init__(self, agents: dict[str, Agent], logger: ExecutionLogger, workspace: Path, runner: ProcessRunner | None = None, git_snapshot: GitSnapshot | None = None, include_git_diff: bool = False) -> None:
        self._agents = agents
        self._logger = logger
        self._workspace = workspace.resolve()
        self._runner = runner or SubprocessRunner()
        self._git_snapshot = git_snapshot or GitSnapshot()
        self._include_git_diff = include_git_diff

    def execute(
        self,
        task: Task,
        agent_id: str,
        log_execution: bool = True,
        *,
        execution_id: str | None = None,
        attempt_id: str | None = None,
        parent_attempt_id: str | None = None,
        policy_version: str = "unrouted-manual",
        config_hash: str = _UNROUTED_CONFIG_HASH,
        selection_mode: str = "manual",
        cohort: str = "manual",
        routing_evidence_eligible: bool = False,
        escalation_reasons: tuple[str, ...] = (),
        trigger_classes: tuple[str, ...] = (),
    ) -> ExecutionRecord:
        if agent_id not in self._agents:
            raise KeyError(f"Unknown agent: {agent_id}")
        agent = self._agents[agent_id]
        execution_id = execution_id or str(uuid4())
        attempt_id = attempt_id or str(uuid4())
        occurred_at = _utc_now()
        prompt = ""
        command: tuple[str, ...] = ()
        try:
            run = agent.execute(task, self._workspace, self._runner)
            prompt, process, command = run.prompt, run.process, tuple(run.process.command)
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
            )
        except Exception as exc:
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
            )
        if log_execution:
            self._logger.write(record)
        return record

    def log(self, record: ExecutionRecord) -> None:
        self._logger.write(record)

    @property
    def agents(self) -> tuple[Agent, ...]:
        return tuple(self._agents.values())

    @property
    def workspace(self) -> Path:
        return self._workspace

    @property
    def runner(self) -> ProcessRunner:
        return self._runner
