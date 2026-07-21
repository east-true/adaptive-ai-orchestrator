from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from adaptive_orchestrator.core.domain import Capability, Task
from adaptive_orchestrator.execution.agents import Agent
from adaptive_orchestrator.infrastructure.history import ExecutionHistory
from adaptive_orchestrator.orchestration.planning import ExecutionPlan


_KEYWORDS: Mapping[Capability, tuple[str, ...]] = {
    Capability.REPOSITORY_UNDERSTANDING: ("repository", "repo", "codebase", "dependency", "의존성", "저장소", "코드베이스"),
    Capability.CODE_GENERATION: ("implement", "create code", "create feature", "create a feature", "add feature", "write code", "구현", "기능 추가", "코드 작성"),
    Capability.DEBUGGING: ("bug", "error", "failure", "fix", "debug", "오류", "버그", "수정", "실패"),
    Capability.ARCHITECTURE_REASONING: ("architecture", "design", "refactor", "trade-off", "설계", "아키텍처", "리팩터링"),
    Capability.RESEARCH: ("research", "compare", "investigate", "조사", "비교", "리서치"),
    Capability.SECURITY_REVIEW: ("security", "auth", "permission", "credential", "보안", "인증", "권한", "비밀"),
    Capability.TESTING: ("test", "coverage", "verify", "검증", "테스트", "커버리지"),
    Capability.OPTIMIZATION: ("performance", "optimize", "latency", "성능", "최적화", "지연"),
    Capability.PLANNING: ("plan", "roadmap", "break down", "계획", "로드맵", "분해"),
}


@dataclass(frozen=True, slots=True)
class TaskAnalysis:
    capabilities: tuple[Capability, ...]
    required_capabilities: tuple[Capability, ...]
    inferred_capabilities: tuple[Capability, ...]
    difficulty: int
    risk: int
    uncertainty: int
    signals: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "capabilities": [item.value for item in self.capabilities],
            "required_capabilities": [item.value for item in self.required_capabilities],
            "inferred_capabilities": [item.value for item in self.inferred_capabilities],
            "difficulty": self.difficulty,
            "risk": self.risk,
            "uncertainty": self.uncertainty,
            "signals": list(self.signals),
        }


class TaskAnalyzer:
    def analyze(self, task: Task) -> TaskAnalysis:
        text = f"{task.description} {task.objective} {' '.join(task.constraints)}".lower()
        inferred = {capability for capability, keywords in _KEYWORDS.items() if any(keyword in text for keyword in keywords)}
        capabilities = tuple(sorted(set(task.required_capabilities) | inferred, key=lambda item: item.value))
        signals = [f"inferred:{item.value}" for item in inferred]

        # Difficulty tracks deliberately-declared scope (task.required_capabilities), not raw
        # text length or how many keyword categories a long description happens to touch: a
        # thorough, well-specified multi-requirement task description should not look "harder"
        # than a vague one-liner just for being long. Text-inferred-only capabilities still count,
        # but at a third the weight of explicitly required ones (see docs/architecture.md, evolution #3).
        explicit_count = len(task.required_capabilities)
        inferred_only_count = len(inferred - set(task.required_capabilities))
        difficulty = min(5, 1 + explicit_count // 2 + inferred_only_count // 3 + int(task.priority.value in {"high", "critical"}))

        # Risk keyword matching is inherently approximate (one incidental mention, e.g. "credential"
        # used as a test-writing example, isn't the same evidence as a task that's actually
        # security-/production-sensitive). Require multiple distinct hits for the full contribution,
        # and only trust SECURITY_REVIEW as a risk signal when the caller explicitly required it,
        # not merely when the word "security" appears somewhere in a long description.
        risk_words = (
            "security", "credential", "permission", "production", "deploy", "migration", "delete",
            "force push", "force-push", "rm -rf", "drop table", "overwrite", "irreversible", "no backup",
            "보안", "권한", "운영", "배포", "마이그레이션", "삭제", "강제 푸시", "덮어쓰기", "되돌릴 수 없", "백업 없이",
        )
        risk_word_hits = sum(1 for word in risk_words if word in text)
        explicit_security_review = Capability.SECURITY_REVIEW in task.required_capabilities
        risk = min(5, min(2, risk_word_hits) + int(explicit_security_review) * 2 + int(task.priority.value == "critical"))

        uncertainty = min(5, int(not task.required_capabilities) + int(not inferred) + int("?" in text or "unknown" in text or "모름" in text))
        return TaskAnalysis(
            capabilities,
            tuple(sorted(task.required_capabilities, key=lambda item: item.value)),
            tuple(sorted(inferred, key=lambda item: item.value)),
            difficulty,
            risk,
            uncertainty,
            tuple(sorted(signals)),
        )


@dataclass(frozen=True, slots=True)
class AgentRoutingProfile:
    """Tunable policy data, not an intrinsic or exclusive agent role."""

    capability_affinity: Mapping[Capability, float]
    complexity_preference: float
    risk_preference: float


def default_profiles() -> Mapping[str, AgentRoutingProfile]:
    neutral = {capability: 1.0 for capability in Capability}
    return {
        "claude-code": AgentRoutingProfile({**neutral, Capability.ARCHITECTURE_REASONING: 1.15, Capability.REPOSITORY_UNDERSTANDING: 1.1, Capability.PLANNING: 1.1}, 1.0, 1.0),
        "codex": AgentRoutingProfile({**neutral, Capability.CODE_GENERATION: 1.15, Capability.DEBUGGING: 1.15, Capability.TESTING: 1.15}, 0.75, 0.85),
    }


def _profile_for(agent: Agent, profiles: Mapping[str, AgentRoutingProfile]) -> AgentRoutingProfile:
    profile = profiles.get(agent.agent_id)
    if profile is None:
        profile = profiles.get(agent.base_id)
    if profile is None:
        profile = AgentRoutingProfile({}, 0.5, 0.5)
    return profile


_MIN_SAMPLES_FOR_FULL_CONFIDENCE = 5
"""Below this many logged executions, historical evidence is blended toward a
neutral prior rather than trusted outright — a single lucky (or unlucky) run
should not fully determine routing (see docs/architecture.md, evolution #3)."""

_NEUTRAL_EVIDENCE = 0.5 * 0.4 + 0.5 * 0.3  # what a candidate with no history has always scored; the floor confidence blends toward
_COST_LIMIT_PENALTY = 20.0


class AdaptiveRouter:
    """Explainable routing based on task signals, configured policy, and history."""

    policy_version = "legacy-biased"

    def __init__(self, analyzer: TaskAnalyzer, history: ExecutionHistory, profiles: Mapping[str, AgentRoutingProfile] | None = None) -> None:
        self._analyzer = analyzer
        self._history = history
        self._profiles = profiles or default_profiles()

    def policy_config(self) -> dict[str, object]:
        return {
            "selector": "adaptive-router",
            "profiles": {
                agent_id: {
                    "capability_affinity": {
                        capability.value: value
                        for capability, value in sorted(profile.capability_affinity.items(), key=lambda item: item[0].value)
                    },
                    "complexity_preference": profile.complexity_preference,
                    "risk_preference": profile.risk_preference,
                }
                for agent_id, profile in sorted(self._profiles.items())
            },
            "min_samples_for_full_confidence": _MIN_SAMPLES_FOR_FULL_CONFIDENCE,
            "neutral_evidence": _NEUTRAL_EVIDENCE,
            "cost_limit_penalty": _COST_LIMIT_PENALTY,
        }

    def select(self, task: Task, agents: Iterable[Agent], requested_agent_id: str = "auto") -> ExecutionPlan:
        analysis = self._analyzer.analyze(task)
        available = tuple(agents)  # the parameter is an Iterable; it is scanned more than once below
        candidates = [agent for agent in available if agent.supports(analysis.capabilities)]
        if requested_agent_id != "auto":
            known = {agent.agent_id for agent in available}
            # An unknown id and a known-but-incapable id are different failures; saying "cannot
            # satisfy capabilities" for a typo sends the reader looking at the wrong thing.
            if requested_agent_id not in known:
                raise ValueError(f"Unknown agent: {requested_agent_id}. Available: {', '.join(sorted(known))}")
            candidates = [agent for agent in candidates if agent.agent_id == requested_agent_id]
            if not candidates:
                raise ValueError(f"Requested agent cannot satisfy capabilities: {requested_agent_id}")
        if not candidates:
            raise ValueError("No available agent supports the analyzed capability requirements.")
        scored: list[tuple[float, Agent, dict[str, object]]] = []
        for agent in candidates:
            profile = _profile_for(agent, self._profiles)
            affinity = sum(profile.capability_affinity.get(capability, 1.0) for capability in analysis.capabilities) / max(len(analysis.capabilities), 1)
            complexity_fit = 1 - abs(profile.complexity_preference - analysis.difficulty / 5)
            risk_fit = 1 - abs(profile.risk_preference - analysis.risk / 5)
            metrics = self._history.routing_metrics_for(agent.agent_id)

            # Blend observed success/verification rates toward the neutral prior when there isn't
            # yet enough history to trust them outright (a single run should not decide routing).
            confidence = min(1.0, metrics.executions / _MIN_SAMPLES_FOR_FULL_CONFIDENCE)
            success_rate = metrics.success_rate if metrics.success_rate is not None else 0.5
            verification_pass_rate = metrics.verification_pass_rate if metrics.verification_pass_rate is not None else 0.5
            raw_evidence = success_rate * 0.4 + verification_pass_rate * 0.3
            evidence = confidence * raw_evidence + (1 - confidence) * _NEUTRAL_EVIDENCE

            cost_penalty = 0.0
            cost_penalty_reason = None
            if task.cost_limit_usd is not None and metrics.average_cost_usd is not None and metrics.average_cost_usd > task.cost_limit_usd:
                cost_penalty = _COST_LIMIT_PENALTY
                cost_penalty_reason = f"historical average cost ${metrics.average_cost_usd:.4f} exceeds task cost_limit_usd ${task.cost_limit_usd:.4f}"

            score = affinity * 50 + complexity_fit * 15 + risk_fit * 10 + evidence * 25 - cost_penalty
            scored.append((score, agent, {
                "score": round(score, 2),
                "affinity": round(affinity, 2),
                "complexity_fit": round(complexity_fit, 2),
                "risk_fit": round(risk_fit, 2),
                "cost_penalty_reason": cost_penalty_reason,
                "history": {
                    "executions": metrics.executions,
                    "confidence": round(confidence, 2),
                    "success_rate": metrics.success_rate,
                    "verification_pass_rate": metrics.verification_pass_rate,
                    "average_cost_usd": metrics.average_cost_usd,
                },
            }))
        scored.sort(key=lambda item: (-item[0], item[1].agent_id))
        _, selected, selected_details = scored[0]
        decision = {"requested_agent": requested_agent_id, "selected_agent": selected.agent_id, "candidate_scores": {agent.agent_id: details for _, agent, details in scored}, "rationale": "Highest explainable policy score among agents supporting the analyzed capabilities."}
        return ExecutionPlan(task, selected.agent_id, decision["rationale"], analysis.as_dict(), decision)
