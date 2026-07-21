from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

import fcntl

from adaptive_orchestrator.infrastructure.logging import redact

EVENT_SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class LifecycleEventType(str, Enum):
    SELECTION_MADE = "selection_made"
    EXECUTION_STARTED = "execution_started"
    EXECUTION_TERMINAL = "execution_terminal"
    EXECUTION_RECONCILED = "execution_reconciled"
    EVALUATION_COMPLETED = "evaluation_completed"
    OUTCOME_FINALIZED = "outcome_finalized"


@dataclass(frozen=True, slots=True)
class LifecycleEvent:
    event_type: LifecycleEventType
    execution_id: str
    sequence: int
    task_id: str
    attempt_id: str
    event_id: str = field(default_factory=lambda: str(uuid4()))
    schema_version: int = EVENT_SCHEMA_VERSION
    occurred_at: str = field(default_factory=utc_now)
    recorded_at: str = field(default_factory=utc_now)
    parent_attempt_id: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != EVENT_SCHEMA_VERSION:
            raise ValueError(f"Unsupported event schema_version: {self.schema_version}")
        if self.sequence <= 0:
            raise ValueError("Lifecycle event sequence must be positive.")
        for name, value in (
            ("event_id", self.event_id),
            ("execution_id", self.execution_id),
            ("task_id", self.task_id),
            ("attempt_id", self.attempt_id),
            ("occurred_at", self.occurred_at),
            ("recorded_at", self.recorded_at),
        ):
            if not value.strip():
                raise ValueError(f"Lifecycle event {name} is required.")
        if self.event_type is LifecycleEventType.SELECTION_MADE:
            _validate_selection_payload(self.payload)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LifecycleEvent":
        return cls(
            event_type=LifecycleEventType(value["event_type"]),
            execution_id=str(value["execution_id"]),
            sequence=int(value["sequence"]),
            task_id=str(value["task_id"]),
            attempt_id=str(value["attempt_id"]),
            event_id=str(value["event_id"]),
            schema_version=int(value["schema_version"]),
            occurred_at=str(value["occurred_at"]),
            recorded_at=str(value["recorded_at"]),
            parent_attempt_id=value.get("parent_attempt_id"),
            payload=value.get("payload") or {},
        )


class EventLogError(ValueError):
    pass


class JsonlEventStore:
    """Durable append-only event source with locked sequence allocation."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(
        self,
        event_type: LifecycleEventType,
        *,
        execution_id: str,
        task_id: str,
        attempt_id: str,
        parent_attempt_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
        event_id: str | None = None,
        occurred_at: str | None = None,
    ) -> LifecycleEvent:
        """Allocate the next execution sequence and fsync one event atomically.

        Reusing an event ID is idempotent: the existing event is returned and
        no second line is appended.
        """

        requested_event_id = event_id or str(uuid4())
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        with self.path.open("a+", encoding="utf-8") as stream:
            os.chmod(self.path, 0o600)
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                stream.seek(0)
                events = _parse_lines(stream.read().splitlines(), self.path)
                for existing in events:
                    if existing.event_id == requested_event_id:
                        same_request = (
                            existing.event_type is event_type
                            and existing.execution_id == execution_id
                            and existing.task_id == task_id
                            and existing.attempt_id == attempt_id
                            and existing.parent_attempt_id == parent_attempt_id
                            and dict(existing.payload) == dict(payload or {})
                            and (occurred_at is None or existing.occurred_at == occurred_at)
                        )
                        if not same_request:
                            raise EventLogError(f"Event id collision with different content: {requested_event_id}")
                        return existing
                next_sequence = max((item.sequence for item in events if item.execution_id == execution_id), default=0) + 1
                event = LifecycleEvent(
                    event_type=event_type,
                    execution_id=execution_id,
                    sequence=next_sequence,
                    task_id=task_id,
                    attempt_id=attempt_id,
                    event_id=requested_event_id,
                    occurred_at=occurred_at or utc_now(),
                    parent_attempt_id=parent_attempt_id,
                    payload=payload or {},
                )
                serialized = json.dumps(redact(asdict(event)), default=str, sort_keys=True, separators=(",", ":"))
                stream.seek(0, os.SEEK_END)
                stream.write(serialized + "\n")
                stream.flush()
                os.fsync(stream.fileno())
                return event
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def read(self) -> tuple[LifecycleEvent, ...]:
        if not self.path.exists():
            return ()
        with self.path.open("r", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_SH)
            try:
                return _parse_lines(stream.read().splitlines(), self.path)
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _parse_lines(lines: Sequence[str], path: Path) -> tuple[LifecycleEvent, ...]:
    events: list[LifecycleEvent] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TypeError("event row must be an object")
            events.append(LifecycleEvent.from_dict(value))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise EventLogError(f"Invalid event at {path}:{line_number}: {exc}") from exc
    return tuple(events)


def _validate_selection_payload(payload: Mapping[str, Any]) -> None:
    selected = payload.get("selected_agent")
    probabilities = payload.get("candidate_probabilities")
    eligible = payload.get("eligible_candidates")
    ineligible = payload.get("ineligible_reasons")
    selected_probability = payload.get("selected_probability")
    if not isinstance(selected, str) or not selected:
        raise ValueError("selection_made requires selected_agent.")
    if not isinstance(probabilities, Mapping) or not probabilities:
        raise ValueError("selection_made requires candidate_probabilities.")
    numeric_probabilities: dict[str, float] = {}
    for agent_id, probability in probabilities.items():
        if not isinstance(agent_id, str) or isinstance(probability, bool) or not isinstance(probability, (int, float)):
            raise ValueError("candidate probabilities must map agent IDs to numbers.")
        numeric_probabilities[agent_id] = float(probability)
        if not 0 <= numeric_probabilities[agent_id] <= 1:
            raise ValueError("candidate probabilities must be between zero and one.")
    if abs(sum(numeric_probabilities.values()) - 1.0) > 1e-9:
        raise ValueError("candidate probabilities must sum to one.")
    if selected not in numeric_probabilities or numeric_probabilities[selected] <= 0:
        raise ValueError("selected agent must have positive probability.")
    if isinstance(selected_probability, bool) or not isinstance(selected_probability, (int, float)):
        raise ValueError("selection_made requires numeric selected_probability.")
    if abs(float(selected_probability) - numeric_probabilities[selected]) > 1e-12:
        raise ValueError("selected_probability must match candidate_probabilities.")
    if not isinstance(eligible, (list, tuple)) or selected not in eligible:
        raise ValueError("selected agent must be eligible.")
    if not isinstance(ineligible, Mapping):
        raise ValueError("selection_made requires ineligible_reasons.")
    for agent_id in ineligible:
        if numeric_probabilities.get(agent_id, 0.0) != 0.0:
            raise ValueError("ineligible candidates must have zero probability.")
