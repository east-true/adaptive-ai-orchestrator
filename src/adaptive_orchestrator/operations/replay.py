from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping

from adaptive_orchestrator.infrastructure.events import JsonlEventStore, LifecycleEvent
from adaptive_orchestrator.routing.state import EventProjector, RoutingState


@dataclass(frozen=True, slots=True)
class AttemptSummary:
    attempt_count: int
    finalized_attempt_count: int
    incomplete_attempt_count: int
    attempt_status_counts: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class LegacyReplayReport:
    row_count: int
    valid_record_count: int
    malformed_row_count: int
    typed_quality_record_count: int
    counterfactual_supported: bool = False
    purpose: str = "schema-validation-and-record-reproduction-only"

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def replay_events(events: tuple[LifecycleEvent, ...]) -> RoutingState:
    return EventProjector().replay(events)


def replay_event_log(path: Path) -> RoutingState:
    return replay_events(JsonlEventStore(path).read())


def summarize_attempts(state: RoutingState) -> AttemptSummary:
    """Count every materialized attempt once from one immutable replay projection."""

    observed = Counter(
        attempt.status
        for execution in state.executions.values()
        for attempt in execution.attempts.values()
    )
    attempt_count = sum(observed.values())
    finalized = observed["finalized"]
    return AttemptSummary(
        attempt_count=attempt_count,
        finalized_attempt_count=finalized,
        incomplete_attempt_count=attempt_count - finalized,
        attempt_status_counts={status: observed[status] for status in sorted(observed)},
    )


def replay_digest(state: RoutingState) -> str:
    """Stable digest for byte-for-byte replay checks of the same event input."""

    return hashlib.sha256(state.to_json().encode("utf-8")).hexdigest()


def validate_legacy_execution_log(path: Path) -> LegacyReplayReport:
    if not path.exists():
        return LegacyReplayReport(0, 0, 0, 0)
    rows = path.read_text(encoding="utf-8").splitlines()
    valid = 0
    malformed = 0
    typed_quality = 0
    for line in rows:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if not isinstance(item, dict) or not isinstance(item.get("agent_id"), str):
            malformed += 1
            continue
        valid += 1
        quality = [
            result
            for result in item.get("evaluations") or ()
            if isinstance(result, dict) and result.get("role") == "quality" and result.get("observed") is True
        ]
        typed_quality += int(bool(quality))
    return LegacyReplayReport(len(rows), valid, malformed, typed_quality)
