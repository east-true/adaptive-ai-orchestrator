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


class VerificationStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    SKIPPED = "skipped"


class MemoryEntryType(str, Enum):
    ARCHITECTURE_DECISION = "ARCHITECTURE_DECISION"
    DESIGN_REASONING = "DESIGN_REASONING"
    TRADE_OFF = "TRADE_OFF"
    FAILURE_HISTORY = "FAILURE_HISTORY"
    PROJECT_CONTEXT = "PROJECT_CONTEXT"
    CODE_EVOLUTION = "CODE_EVOLUTION"


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
class MemoryEntry:
    entry_type: MemoryEntryType
    title: str
    summary: str
    rationale: str = ""
    alternatives_considered: Sequence[str] = field(default_factory=tuple)
    tags: Sequence[str] = field(default_factory=tuple)
    related_task_description: str | None = None

    def __post_init__(self) -> None:
        if not self.title.strip() or not self.summary.strip():
            raise ValueError("MemoryEntry title and summary are required.")


@dataclass(frozen=True, slots=True)
class VerificationResult:
    status: VerificationStatus
    commands: Sequence[Sequence[str]] = field(default_factory=tuple)
    stdout: str | None = None
    stderr: str | None = None
    exit_code: int | None = None
    duration_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class ExecutionMetadata:
    """Provider-neutral execution metadata parsed from a CLI's structured output.

    Every field is optional: adapters fill in only what their CLI's verified
    output schema actually exposes, rather than guessing at an unverified one.
    """

    cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    num_turns: int | None = None
    session_id: str | None = None
    model: str | None = None


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
    verification: VerificationResult | None = None
    task_analysis: Mapping[str, Any] | None = None
    routing_decision: Mapping[str, Any] | None = None
    escalation: "EscalationRecord | None" = None
    metadata: ExecutionMetadata | None = None
    # Permanent logs must identify the vendor without joining against today's mutable registry.
    agent_base_id: str | None = None
    # Phase -1 additive telemetry. Defaults keep old constructors/readers valid;
    # every new kernel execution populates these fields.
    execution_id: str | None = None
    attempt_id: str | None = None
    parent_attempt_id: str | None = None
    occurred_at: str | None = None
    policy_version: str | None = None
    config_hash: str | None = None
    selection_mode: str | None = None
    cohort: str | None = None
    routing_evidence_eligible: bool | None = None
    escalation_reasons: Sequence[str] = field(default_factory=tuple)
    trigger_classes: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class EscalationRecord:
    """A second agent's attempt, run only because the first attempt gave a concrete reason to distrust it."""

    reasons: Sequence[str]
    agent_id: str
    record: ExecutionRecord
    trigger_classes: Sequence[str] = field(default_factory=tuple)
