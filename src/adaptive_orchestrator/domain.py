from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


class Capability(str, Enum):
    REPOSITORY_UNDERSTANDING = "repository_understanding"
    CODE_GENERATION = "code_generation"
    DEBUGGING = "debugging"
    ARCHITECTURE_REASONING = "architecture_reasoning"
    RESEARCH = "research"
    SECURITY_REVIEW = "security_review"
    TESTING = "testing"
    OPTIMIZATION = "optimization"
    PLANNING = "planning"


class Priority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class ExecutionStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    SPAWN_ERROR = "spawn_error"


@dataclass(frozen=True, slots=True)
class Task:
    description: str
    objective: str
    context: Mapping[str, Any] = field(default_factory=dict)
    constraints: Sequence[str] = field(default_factory=tuple)
    required_capabilities: Sequence[Capability] = field(default_factory=tuple)
    priority: Priority = Priority.NORMAL
    time_limit_seconds: float | None = None
    cost_limit_usd: float | None = None

    def __post_init__(self) -> None:
        if not self.description.strip() or not self.objective.strip():
            raise ValueError("Task description and objective are required.")
        if self.cost_limit_usd is not None and self.cost_limit_usd < 0:
            raise ValueError("cost_limit_usd cannot be negative.")
        if self.time_limit_seconds is not None and self.time_limit_seconds <= 0:
            raise ValueError("time_limit_seconds must be positive.")


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    task: Task
    agent_id: str
    prompt: str
    command: Sequence[str]
    status: ExecutionStatus
    result: str | None
    error: str | None
    exit_code: int | None
    duration_ms: float
    workspace_modified_files: Sequence[str] = field(default_factory=tuple)
    workspace_git_diff: str | None = None
