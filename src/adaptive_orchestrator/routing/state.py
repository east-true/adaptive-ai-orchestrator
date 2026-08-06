from __future__ import annotations

import json
import os
import socket
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from adaptive_orchestrator.infrastructure.events import JsonlEventStore, LifecycleEvent, LifecycleEventType
from adaptive_orchestrator.infrastructure.file_lock import lock_exclusive, unlock


class ReplayError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AttemptState:
    task_id: str
    parent_attempt_id: str | None
    selection_sequence: int
    status: str
    selection: Mapping[str, Any] = field(default_factory=dict)
    started: Mapping[str, Any] = field(default_factory=dict)
    terminal: Mapping[str, Any] = field(default_factory=dict)
    evaluations: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    outcome: Mapping[str, Any] = field(default_factory=dict)
    event_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ExecutionState:
    task_id: str
    last_sequence: int
    attempts: Mapping[str, AttemptState]


@dataclass(frozen=True, slots=True)
class RoutingState:
    state_schema_version: int
    executions: Mapping[str, ExecutionState]
    applied_event_ids: tuple[str, ...]
    duplicate_event_ids: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self.to_json())

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), default=str)


class EventProjector:
    """Pure, deterministic lifecycle projector with transition validation."""

    state_schema_version = 2

    def replay(self, events: Sequence[LifecycleEvent]) -> RoutingState:
        executions: dict[str, dict[str, Any]] = {}
        seen: dict[str, str] = {}
        applied: list[str] = []
        duplicates: list[str] = []

        for event in events:
            fingerprint = json.dumps(asdict(event), sort_keys=True, separators=(",", ":"), default=str)
            if event.event_id in seen:
                if seen[event.event_id] != fingerprint:
                    raise ReplayError(f"Event id collision with different content: {event.event_id}")
                duplicates.append(event.event_id)
                continue
            seen[event.event_id] = fingerprint

            execution = executions.setdefault(event.execution_id, {
                "task_id": event.task_id,
                "last_sequence": 0,
                "attempts": {},
            })
            if execution["task_id"] != event.task_id:
                raise ReplayError(f"Task id changed within execution {event.execution_id}.")
            expected_sequence = execution["last_sequence"] + 1
            if event.sequence != expected_sequence:
                raise ReplayError(
                    f"Sequence gap for execution {event.execution_id}: expected {expected_sequence}, got {event.sequence}."
                )
            execution["last_sequence"] = event.sequence
            self._apply_event(execution, event)
            applied.append(event.event_id)

        frozen_executions: dict[str, ExecutionState] = {}
        for execution_id in sorted(executions):
            execution = executions[execution_id]
            attempts = {
                attempt_id: AttemptState(
                    task_id=value["task_id"],
                    parent_attempt_id=value["parent_attempt_id"],
                    selection_sequence=value["selection_sequence"],
                    status=value["status"],
                    selection=value["selection"],
                    started=value["started"],
                    terminal=value["terminal"],
                    evaluations=tuple(value["evaluations"]),
                    outcome=value["outcome"],
                    event_ids=tuple(value["event_ids"]),
                )
                for attempt_id, value in sorted(execution["attempts"].items())
            }
            frozen_executions[execution_id] = ExecutionState(
                task_id=execution["task_id"],
                last_sequence=execution["last_sequence"],
                attempts=attempts,
            )
        return RoutingState(self.state_schema_version, frozen_executions, tuple(applied), tuple(duplicates))

    def _apply_event(self, execution: dict[str, Any], event: LifecycleEvent) -> None:
        attempts: dict[str, dict[str, Any]] = execution["attempts"]
        attempt = attempts.get(event.attempt_id)
        if event.event_type is LifecycleEventType.SELECTION_MADE:
            if attempt is not None:
                raise ReplayError(f"Duplicate selection transition for attempt {event.attempt_id}.")
            if event.parent_attempt_id is not None and event.parent_attempt_id not in attempts:
                raise ReplayError(f"Unknown parent attempt {event.parent_attempt_id} for {event.attempt_id}.")
            attempts[event.attempt_id] = {
                "task_id": event.task_id,
                "parent_attempt_id": event.parent_attempt_id,
                "selection_sequence": event.sequence,
                "status": "selected",
                "selection": dict(event.payload),
                "started": {},
                "terminal": {},
                "evaluations": [],
                "outcome": {},
                "event_ids": [event.event_id],
            }
            return
        if attempt is None:
            raise ReplayError(f"{event.event_type.value} occurred before selection for attempt {event.attempt_id}.")
        if event.parent_attempt_id != attempt["parent_attempt_id"]:
            raise ReplayError(f"Parent attempt id changed for attempt {event.attempt_id}.")
        if attempt["status"] == "finalized":
            raise ReplayError(f"Event occurred after outcome_finalized for attempt {event.attempt_id}.")

        if event.event_type is LifecycleEventType.EXECUTION_STARTED:
            if attempt["status"] != "selected":
                raise ReplayError(f"execution_started requires selected state for attempt {event.attempt_id}.")
            attempt["status"] = "started"
            attempt["started"] = dict(event.payload)
        elif event.event_type in {LifecycleEventType.EXECUTION_TERMINAL, LifecycleEventType.EXECUTION_RECONCILED}:
            if attempt["status"] != "started":
                raise ReplayError(f"{event.event_type.value} requires started state for attempt {event.attempt_id}.")
            attempt["status"] = "reconciled" if event.event_type is LifecycleEventType.EXECUTION_RECONCILED else "terminal"
            attempt["terminal"] = dict(event.payload)
        elif event.event_type is LifecycleEventType.EVALUATION_COMPLETED:
            if attempt["status"] not in {"terminal", "reconciled", "evaluated"}:
                raise ReplayError(f"evaluation_completed requires terminal state for attempt {event.attempt_id}.")
            attempt["status"] = "evaluated"
            attempt["evaluations"].append(dict(event.payload))
        elif event.event_type is LifecycleEventType.OUTCOME_FINALIZED:
            if attempt["status"] not in {"terminal", "reconciled", "evaluated"}:
                raise ReplayError(f"outcome_finalized requires terminal state for attempt {event.attempt_id}.")
            attempt["status"] = "finalized"
            attempt["outcome"] = dict(event.payload)
        else:  # pragma: no cover - enum exhaustiveness guard
            raise ReplayError(f"Unsupported lifecycle event type: {event.event_type}")
        attempt["event_ids"].append(event.event_id)


class RoutingStateStore:
    """Disposable materialized projection; the event log remains source-of-truth."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, state: RoutingState) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(state.to_json() + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, self.path)
        except BaseException:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise

    def read(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ReplayError("Routing state must be a JSON object.")
        return value


def _recorder_lock_path(event_path: Path) -> Path:
    return event_path.with_name(f".{event_path.name}.recorder.lock")


@contextmanager
def _exclusive_recorder_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(lock_path.parent, 0o700)
    with lock_path.open("a+", encoding="utf-8") as stream:
        os.chmod(lock_path, 0o600)
        lock_exclusive(stream)
        try:
            yield
        finally:
            unlock(stream)


def _rebuild_routing_state_unlocked(
    event_store: JsonlEventStore,
    state_store: RoutingStateStore,
) -> RoutingState:
    state = EventProjector().replay(event_store.read())
    state_store.write(state)
    return state


def rebuild_routing_state(
    event_store: JsonlEventStore,
    state_store: RoutingStateStore | None = None,
) -> RoutingState:
    """Rebuild the disposable projection under the recorder lock without appending events."""

    target = state_store or RoutingStateStore(event_store.path.with_name("routing-state.json"))
    with _exclusive_recorder_lock(_recorder_lock_path(event_store.path)):
        return _rebuild_routing_state_unlocked(event_store, target)


class LifecycleRecorder:
    def __init__(self, event_store: JsonlEventStore, state_store: RoutingStateStore | None = None) -> None:
        self.event_store = event_store
        self.state_store = state_store or RoutingStateStore(event_store.path.with_name("routing-state.json"))
        self._lock_path = _recorder_lock_path(event_store.path)
        with self._exclusive_lock():
            self._reconcile_incomplete_unlocked()
            self._rebuild_state_unlocked()

    def record(self, event_type: LifecycleEventType, **kwargs: Any) -> LifecycleEvent:
        with self._exclusive_lock():
            event = self._append_event_unlocked(event_type, **kwargs)
            self._rebuild_state_unlocked()
            return event

    def rebuild_state(self) -> RoutingState:
        with self._exclusive_lock():
            return self._rebuild_state_unlocked()

    def _rebuild_state_unlocked(self) -> RoutingState:
        return _rebuild_routing_state_unlocked(self.event_store, self.state_store)

    def _append_event_unlocked(
        self,
        event_type: LifecycleEventType,
        **kwargs: Any,
    ) -> LifecycleEvent:
        """Append only after the prospective durable log replays successfully."""

        return self.event_store._append_validated(
            event_type,
            validator=EventProjector().replay,
            **kwargs,
        )

    def reconcile_incomplete(self) -> tuple[LifecycleEvent, ...]:
        with self._exclusive_lock():
            reconciled = self._reconcile_incomplete_unlocked()
            self._rebuild_state_unlocked()
            return reconciled

    def _reconcile_incomplete_unlocked(self) -> tuple[LifecycleEvent, ...]:
        state = EventProjector().replay(self.event_store.read())
        reconciled: list[LifecycleEvent] = []
        for execution_id, execution in state.executions.items():
            for attempt_id, attempt in execution.attempts.items():
                if attempt.status == "reconciled":
                    self._append_event_unlocked(
                        LifecycleEventType.OUTCOME_FINALIZED,
                        execution_id=execution_id,
                        task_id=attempt.task_id,
                        attempt_id=attempt_id,
                        parent_attempt_id=attempt.parent_attempt_id,
                        payload=dict(attempt.terminal),
                    )
                    continue
                if attempt.status != "started":
                    continue
                if _attempt_owner_is_active(attempt.started):
                    continue
                reconciled.append(self._append_event_unlocked(
                    LifecycleEventType.EXECUTION_RECONCILED,
                    execution_id=execution_id,
                    task_id=attempt.task_id,
                    attempt_id=attempt_id,
                    parent_attempt_id=attempt.parent_attempt_id,
                    payload={"status": "abandoned", "reason": "recovered_on_next_start"},
                ))
                self._append_event_unlocked(
                    LifecycleEventType.OUTCOME_FINALIZED,
                    execution_id=execution_id,
                    task_id=attempt.task_id,
                    attempt_id=attempt_id,
                    parent_attempt_id=attempt.parent_attempt_id,
                    payload={"status": "abandoned", "reason": "recovered_on_next_start"},
                )
        return tuple(reconciled)

    @contextmanager
    def _exclusive_lock(self) -> Iterator[None]:
        """Serialize event mutation and its materialized projection across processes.

        The recorder lock is always acquired before the event store's own lock.
        Standalone event readers acquire only the latter, so there is no inverse
        lock order that could deadlock with a recorder operation.
        """

        with _exclusive_recorder_lock(self._lock_path):
            yield


def _attempt_owner_is_active(started: Mapping[str, Any]) -> bool:
    owner_pid = started.get("owner_pid")
    owner_host = started.get("owner_host")
    if not isinstance(owner_pid, int) or owner_pid <= 0:
        return False
    if owner_host != socket.gethostname():
        # A local process cannot safely declare a remote owner dead.
        return True
    try:
        os.kill(owner_pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
