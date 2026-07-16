from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .domain import Capability, ExecutionMetadata, Task
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

    def parse_result(self, stdout: str) -> tuple[str | None, ExecutionMetadata | None]:
        """Default: no structured output protocol verified for this CLI yet."""
        return stdout or None, None

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
        return (self.executable, "--print", "--output-format", "json", "--permission-mode", self.permission_mode, prompt)

    def parse_result(self, stdout: str) -> tuple[str | None, ExecutionMetadata | None]:
        # Verified against Claude Code 2.1.211's `--output-format json` (see README "CLI compatibility").
        text = stdout.strip()
        if not text:
            return None, None
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return stdout, None
        if not isinstance(payload, dict):
            return stdout, None
        usage = payload.get("usage") or {}
        metadata = ExecutionMetadata(
            cost_usd=payload.get("total_cost_usd"),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            cached_input_tokens=usage.get("cache_read_input_tokens"),
            num_turns=payload.get("num_turns"),
            session_id=payload.get("session_id"),
        )
        return payload.get("result") or stdout, metadata


@dataclass(frozen=True, slots=True)
class CodexAgent(Agent):
    agent_id: str = "codex"
    executable: str = "codex"
    sandbox_mode: str = "workspace-write"
    capabilities: frozenset[Capability] = frozenset(Capability)

    def build_command(self, prompt: str, workspace: Path) -> Sequence[str]:
        return (self.executable, "exec", "--sandbox", self.sandbox_mode, "--cd", str(workspace), "--json", prompt)

    def parse_result(self, stdout: str) -> tuple[str | None, ExecutionMetadata | None]:
        # Verified live against Codex CLI 0.144.5's `exec --json`: thread.started{thread_id},
        # item.completed{item:{type, text}} (only type "agent_message" carries the final answer;
        # other item types like command_execution are intentionally ignored here),
        # turn.completed{usage:{input_tokens, cached_input_tokens, output_tokens,
        # reasoning_output_tokens}}, and on failure error{message}/turn.failed{error}. No cost
        # field is exposed, unlike Claude Code's --output-format json.
        events: list[dict] = []
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a truncated/partial line (e.g. after a timeout); skip, don't discard the rest
        if not events:
            return stdout or None, None

        result_text: str | None = None
        thread_id: str | None = None
        usage: dict | None = None
        for event in events:
            event_type = event.get("type")
            item = event.get("item") or {}
            if event_type == "thread.started":
                thread_id = event.get("thread_id")
            elif event_type == "item.completed" and item.get("type") == "agent_message":
                result_text = item.get("text")
            elif event_type == "turn.completed":
                usage = event.get("usage")
            elif event_type in {"error", "turn.failed"}:
                message = event.get("message") or (event.get("error") or {}).get("message")
                if message:
                    result_text = result_text or message

        metadata = ExecutionMetadata(
            input_tokens=(usage or {}).get("input_tokens"),
            output_tokens=(usage or {}).get("output_tokens"),
            cached_input_tokens=(usage or {}).get("cached_input_tokens"),
            session_id=thread_id,
        )
        return result_text or stdout, metadata
