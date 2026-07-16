from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .domain import Capability, Task
from .process_runner import ProcessResult, ProcessRunner


@dataclass(frozen=True, slots=True)
class AgentRun:
    prompt: str
    process: ProcessResult


class Agent(ABC):
    """A capability-declared coding-agent adapter, independent of a CLI vendor."""

    agent_id: str
    capabilities: frozenset[Capability]

    def supports(self, requirements: Iterable[Capability]) -> bool:
        return set(requirements).issubset(self.capabilities)

    def execute(self, task: Task, workspace: Path, runner: ProcessRunner) -> AgentRun:
        if not self.supports(task.required_capabilities):
            missing = set(task.required_capabilities) - self.capabilities
            raise ValueError(f"Agent '{self.agent_id}' lacks capabilities: {sorted(x.value for x in missing)}")
        prompt = self.build_prompt(task)
        return AgentRun(prompt, runner.run(self.build_command(prompt, workspace), workspace, task.time_limit_seconds))

    @abstractmethod
    def build_command(self, prompt: str, workspace: Path) -> Sequence[str]:
        raise NotImplementedError

    @staticmethod
    def build_prompt(task: Task) -> str:
        constraints = "\n".join(f"- {item}" for item in task.constraints) or "- None"
        capabilities = ", ".join(item.value for item in task.required_capabilities) or "none"
        return (
            f"Objective: {task.objective}\n\nDescription: {task.description}\n\n"
            f"Required capabilities: {capabilities}\nConstraints:\n{constraints}\nContext: {dict(task.context)}"
        )


@dataclass(frozen=True, slots=True)
class ClaudeCodeAgent(Agent):
    agent_id: str = "claude-code"
    executable: str = "claude"
    permission_mode: str = "acceptEdits"
    capabilities: frozenset[Capability] = frozenset(Capability)

    def build_command(self, prompt: str, workspace: Path) -> Sequence[str]:
        return (self.executable, "--print", "--output-format", "text", "--permission-mode", self.permission_mode, prompt)


@dataclass(frozen=True, slots=True)
class CodexAgent(Agent):
    agent_id: str = "codex"
    executable: str = "codex"
    sandbox_mode: str = "workspace-write"
    capabilities: frozenset[Capability] = frozenset(Capability)

    def build_command(self, prompt: str, workspace: Path) -> Sequence[str]:
        return (self.executable, "exec", "--sandbox", self.sandbox_mode, "--cd", str(workspace), prompt)
