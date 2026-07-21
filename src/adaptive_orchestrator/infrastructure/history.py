from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from adaptive_orchestrator.core.domain import EvaluatorRole
from adaptive_orchestrator.orchestration.escalation import trigger_classes_for

_EVALUATOR_ROLES = tuple(role.value for role in EvaluatorRole)


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


@dataclass(frozen=True, slots=True)
class EvaluatorMetrics:
    """Role-specific observation counts. Roles are never substituted for one another."""

    result_count: int = 0
    observed_count: int = 0
    passed_count: int = 0
    failed_count: int = 0
    error_count: int = 0
    score_total: float = 0.0
    score_samples: int = 0

    @property
    def pass_rate(self) -> float | None:
        return self.passed_count / self.observed_count if self.observed_count else None

    @property
    def average_score(self) -> float | None:
        return self.score_total / self.score_samples if self.score_samples else None


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

    def evaluator_metrics_for(self, agent_id: str, role: EvaluatorRole | str) -> EvaluatorMetrics:
        role_name = role.value if isinstance(role, EvaluatorRole) else role
        if role_name not in _EVALUATOR_ROLES:
            raise ValueError(f"Unknown evaluator role: {role_name}")
        metrics = EvaluatorMetrics()
        for item in self.records():
            if item.get("agent_id") != agent_id:
                continue
            role_projection = (item.get("evaluation_projection") or {}).get(role_name) or {}
            scores = [_finite_float(score) for score in role_projection.get("scores", ())]
            finite_scores = [score for score in scores if score is not None]
            metrics = EvaluatorMetrics(
                result_count=metrics.result_count + int(role_projection.get("result_count", 0)),
                observed_count=metrics.observed_count + int(role_projection.get("observed_count", 0)),
                passed_count=metrics.passed_count + int(role_projection.get("passed_count", 0)),
                failed_count=metrics.failed_count + int(role_projection.get("failed_count", 0)),
                error_count=metrics.error_count + int(role_projection.get("error_count", 0)),
                score_total=metrics.score_total + sum(finite_scores),
                score_samples=metrics.score_samples + len(finite_scores),
            )
        return metrics

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

    if not item.get("evaluation_projection"):
        normalized["evaluation_projection"] = _derive_evaluation_projection(item)

    return normalized


def _derive_evaluation_projection(item: dict) -> dict[str, dict[str, object]]:
    projection: dict[str, dict[str, object]] = {
        role: {
            "result_count": 0,
            "observed": False,
            "observed_count": 0,
            "passed_count": 0,
            "failed_count": 0,
            "error_count": 0,
            "scores": [],
        }
        for role in _EVALUATOR_ROLES
    }
    evaluations = item.get("evaluations")
    if isinstance(evaluations, list) and evaluations:
        for result in evaluations:
            if not isinstance(result, dict) or result.get("role") not in projection:
                continue
            _add_projection_result(projection[result["role"]], result)
        return projection

    # Old terminal rows had no roles. Process status is reliability, while the
    # old verifier can only be migrated conservatively to constraint evidence.
    status = item.get("status")
    if status in {"completed", "failed", "timed_out", "spawn_error"}:
        _add_projection_result(projection[EvaluatorRole.RELIABILITY.value], {
            "status": "passed" if status == "completed" else "failed",
            "observed": True,
        })
    verification = item.get("verification")
    if isinstance(verification, dict) and verification.get("status") in {"passed", "failed", "timed_out", "skipped"}:
        _add_projection_result(projection[EvaluatorRole.CONSTRAINT.value], {
            "status": verification["status"],
            "observed": verification["status"] != "skipped",
        })
    return projection


def _add_projection_result(projection: dict[str, object], result: dict) -> None:
    projection["result_count"] = int(projection["result_count"]) + 1
    observed = result.get("observed") is True
    if observed:
        projection["observed"] = True
        projection["observed_count"] = int(projection["observed_count"]) + 1
        if result.get("status") == "passed":
            projection["passed_count"] = int(projection["passed_count"]) + 1
        elif result.get("status") in {"failed", "timed_out"}:
            projection["failed_count"] = int(projection["failed_count"]) + 1
    if result.get("status") == "error":
        projection["error_count"] = int(projection["error_count"]) + 1
    score = _finite_float(result.get("score"))
    if score is not None:
        scores = projection["scores"]
        assert isinstance(scores, list)
        scores.append(score)
