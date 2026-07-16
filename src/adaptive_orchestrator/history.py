from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AgentMetrics:
    executions: int = 0
    successful_executions: int = 0
    verified_executions: int = 0
    passed_verifications: int = 0
    total_duration_ms: float = 0.0
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
        return self.total_duration_ms / self.executions if self.executions else None

    @property
    def average_cost_usd(self) -> float | None:
        # None (not 0.0) when no execution logged a cost, e.g. Codex today (see agents.py CodexAgent).
        return self.total_cost_usd / self.cost_samples if self.cost_samples else None


class ExecutionHistory:
    """Reads local JSONL telemetry for routing signals; malformed lines are ignored."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def metrics_for(self, agent_id: str) -> AgentMetrics:
        metrics = AgentMetrics()
        if not self.path.exists():
            return metrics
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("agent_id") != agent_id:
                continue
            completed = item.get("status") == "completed"
            verification = item.get("verification") or {}
            verified = verification.get("status") in {"passed", "failed", "timed_out"}
            passed = verification.get("status") == "passed"
            cost = (item.get("metadata") or {}).get("cost_usd")
            metrics = AgentMetrics(
                executions=metrics.executions + 1,
                successful_executions=metrics.successful_executions + int(completed),
                verified_executions=metrics.verified_executions + int(verified),
                passed_verifications=metrics.passed_verifications + int(passed),
                total_duration_ms=metrics.total_duration_ms + float(item.get("duration_ms") or 0),
                total_cost_usd=metrics.total_cost_usd + float(cost) if cost is not None else metrics.total_cost_usd,
                cost_samples=metrics.cost_samples + int(cost is not None),
            )
        return metrics
