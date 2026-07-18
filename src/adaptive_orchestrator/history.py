from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .escalation import trigger_classes_for


@dataclass(frozen=True, slots=True)
class AgentMetrics:
    executions: int = 0
    successful_executions: int = 0
    verified_executions: int = 0
    passed_verifications: int = 0
    total_duration_ms: float = 0.0
    duration_samples: int = 0
    total_cost_usd: float = 0.0
    cost_samples: int = 0

    @property
    def success_rate(self) -> float | None:
        return self.successful_executions / self.executions if self.executions else None

    @property
    def verification_pass_rate(self) -> float | None:
        return self.passed_verifications / self.verified_executions if self.verified_executions else None

    @property
    def average_duration_ms(self) -> float | None:
        return self.total_duration_ms / self.duration_samples if self.duration_samples else None

    @property
    def average_cost_usd(self) -> float | None:
        # None (not 0.0) when no execution logged a cost, e.g. Codex today (see agents.py CodexAgent).
        return self.total_cost_usd / self.cost_samples if self.cost_samples else None


class ExecutionHistory:
    """Reads local JSONL telemetry for routing signals; malformed lines are ignored."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def agent_ids(self) -> tuple[str, ...]:
        """Distinct agent ids observed in the log, in first-seen order."""
        seen: dict[str, None] = {}
        for item in self.records():
            agent_id = item.get("agent_id")
            if isinstance(agent_id, str):
                seen.setdefault(agent_id, None)
        return tuple(seen)

    def records(self) -> tuple[dict, ...]:
        """Read rows and add honest retrospective cohort labels where possible."""
        if not self.path.exists():
            return ()
        records: list[dict] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                records.append(_with_derived_labels(item))
        return tuple(records)

    def metrics_for(self, agent_id: str) -> AgentMetrics:
        return self._metrics_matching(lambda item: item.get("agent_id") == agent_id)

    def routing_metrics_for(self, agent_id: str) -> AgentMetrics:
        """Metrics visible to the legacy router while Phase -1 freezes new biased evidence."""
        return self._metrics_matching(
            lambda item: item.get("agent_id") == agent_id,
            routing_evidence_only=True,
        )

    def metrics_for_base(self, base_id: str) -> AgentMetrics:
        return self._metrics_matching(lambda item: item.get("agent_base_id", item.get("agent_id")) == base_id)

    def _metrics_matching(self, predicate: Callable[[dict], bool], routing_evidence_only: bool = False) -> AgentMetrics:
        metrics = AgentMetrics()
        for item in self.records():
            if not predicate(item):
                continue
            if routing_evidence_only and item.get("routing_evidence_eligible") is False:
                continue
            completed = item.get("status") == "completed"
            verification = item.get("verification") or {}
            verified = verification.get("status") in {"passed", "failed", "timed_out"}
            passed = verification.get("status") == "passed"
            duration = _finite_float(item.get("duration_ms"))
            cost = _finite_float((item.get("metadata") or {}).get("cost_usd"))
            metrics = AgentMetrics(
                executions=metrics.executions + 1,
                successful_executions=metrics.successful_executions + int(completed),
                verified_executions=metrics.verified_executions + int(verified),
                passed_verifications=metrics.passed_verifications + int(passed),
                total_duration_ms=metrics.total_duration_ms + duration if duration is not None else metrics.total_duration_ms,
                duration_samples=metrics.duration_samples + int(duration is not None),
                total_cost_usd=metrics.total_cost_usd + cost if cost is not None else metrics.total_cost_usd,
                cost_samples=metrics.cost_samples + int(cost is not None),
            )
        return metrics


def _finite_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _with_derived_labels(item: dict) -> dict:
    normalized = dict(item)
    decision = item.get("routing_decision") or {}
    selected_agent = decision.get("selected_agent")
    requested_agent = decision.get("requested_agent")

    selection_mode = item.get("selection_mode")
    if not selection_mode:
        if selected_agent and item.get("agent_id") != selected_agent:
            selection_mode = "escalation"
        elif requested_agent and requested_agent != "auto":
            selection_mode = "manual"
        elif selected_agent:
            selection_mode = "exploit"
        else:
            selection_mode = "unknown"
        normalized["selection_mode"] = selection_mode

    if not item.get("cohort"):
        normalized["cohort"] = selection_mode if selection_mode in {"manual", "escalation"} else "legacy"

    reasons = tuple(item.get("escalation_reasons") or ())
    if not reasons:
        reasons = tuple((item.get("escalation") or {}).get("reasons") or ())
    if reasons:
        normalized["escalation_reasons"] = list(reasons)
        if not item.get("trigger_classes"):
            normalized["trigger_classes"] = list(trigger_classes_for(reasons))

    return normalized
