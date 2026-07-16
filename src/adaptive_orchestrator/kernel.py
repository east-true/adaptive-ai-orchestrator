from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .agents import Agent
from .domain import ExecutionRecord, ExecutionStatus, Task
from .git_snapshot import GitSnapshot
from .process_runner import ProcessRunner, SubprocessRunner


class ExecutionLogger(Protocol):
    def write(self, record: ExecutionRecord) -> None: ...


class OrchestratorKernel:
    """Single-agent-first coordinator for CLI coding agents."""

    def __init__(self, agents: dict[str, Agent], logger: ExecutionLogger, workspace: Path, runner: ProcessRunner | None = None, git_snapshot: GitSnapshot | None = None, include_git_diff: bool = False) -> None:
        self._agents = agents
        self._logger = logger
        self._workspace = workspace.resolve()
        self._runner = runner or SubprocessRunner()
        self._git_snapshot = git_snapshot or GitSnapshot()
        self._include_git_diff = include_git_diff

    def execute(self, task: Task, agent_id: str, log_execution: bool = True) -> ExecutionRecord:
        if agent_id not in self._agents:
            raise KeyError(f"Unknown agent: {agent_id}")
        agent = self._agents[agent_id]
        prompt = ""
        command: tuple[str, ...] = ()
        try:
            run = agent.execute(task, self._workspace, self._runner)
            prompt, process, command = run.prompt, run.process, tuple(run.process.command)
            changes = self._git_snapshot.collect(self._workspace)
            error = process.stderr or None if process.status is not ExecutionStatus.COMPLETED else None
            result, metadata = agent.parse_result(process.stdout or "")
            record = ExecutionRecord(task, agent.agent_id, prompt, command, process.status, result, error, process.exit_code, process.duration_ms, changes.modified_files, changes.git_diff if self._include_git_diff else None, metadata=metadata)
        except Exception as exc:
            record = ExecutionRecord(task, agent.agent_id, prompt, command, ExecutionStatus.FAILED, None, str(exc), None, 0, (), None)
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
