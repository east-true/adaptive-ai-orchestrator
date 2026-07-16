from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .domain import ExecutionStatus, VerificationStatus


@dataclass(frozen=True, slots=True)
class EscalationDecision:
    should_escalate: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EscalationPolicy:
    """The single, explainable gate from single-agent-first to a second agent.

    Multi-agent collaboration is not the default (project-constitution.md 5).
    Its own escalation flow is: Single Agent First -> Task Difficulty Analysis
    -> Need Additional Intelligence? -> Multi-Agent Collaboration. This policy
    implements that decision: escalation fires only when the first attempt
    gives a concrete reason to distrust it (it failed, its verification failed
    or timed out) or the router's own analysis flagged risk, uncertainty, or
    difficulty above a configured threshold.

    difficulty_threshold defaults higher than risk/uncertainty because
    TaskAnalyzer.analyze's difficulty score floors at 1 (never 0): a low
    threshold would escalate on nearly every multi-capability task, which
    would violate the "minimum sufficient intelligence" goal in
    project-constitution.md 5. 4 (of 5) requires a genuinely broad or
    high-priority task, not a routine one.
    """

    risk_threshold: int = 3
    uncertainty_threshold: int = 3
    difficulty_threshold: int = 4

    def decide(
        self,
        analysis: Mapping[str, object] | None,
        execution_status: ExecutionStatus,
        verification_status: VerificationStatus,
    ) -> EscalationDecision:
        reasons: list[str] = []
        if execution_status is not ExecutionStatus.COMPLETED:
            reasons.append("execution_failed")
        if verification_status is VerificationStatus.FAILED:
            reasons.append("verification_failed")
        if verification_status is VerificationStatus.TIMED_OUT:
            reasons.append("verification_timed_out")
        analysis = analysis or {}
        if int(analysis.get("risk", 0)) >= self.risk_threshold:
            reasons.append("high_risk")
        if int(analysis.get("uncertainty", 0)) >= self.uncertainty_threshold:
            reasons.append("high_uncertainty")
        if int(analysis.get("difficulty", 0)) >= self.difficulty_threshold:
            reasons.append("high_difficulty")
        return EscalationDecision(bool(reasons), tuple(reasons))
