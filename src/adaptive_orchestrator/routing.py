from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .agents import Agent
from .domain import Capability, Task
from .history import ExecutionHistory
from .planning import ExecutionPlan


_KEYWORDS: Mapping[Capability, tuple[str, ...]] = {
    Capability.REPOSITORY_UNDERSTANDING: ("repository", "repo", "codebase", "dependency", "의존성", "저장소", "코드베이스"),
    Capability.CODE_GENERATION: ("implement", "create", "add feature", "write code", "구현", "기능 추가", "작성"),
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
    difficulty: int
    risk: int
    uncertainty: int
    signals: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "capabilities": [item.value for item in self.capabilities],
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
        difficulty = min(5, 1 + len(capabilities) // 2 + int(len(text) > 240) + int(task.priority.value in {"high", "critical"}))
        risk_words = ("security", "credential", "permission", "production", "deploy", "migration", "delete", "보안", "권한", "운영", "배포", "마이그레이션", "삭제")
        risk = min(5, int(any(word in text for word in risk_words)) * 2 + int(Capability.SECURITY_REVIEW in capabilities) * 2 + int(task.priority.value == "critical"))
        uncertainty = min(5, int(not task.required_capabilities) + int(not inferred) + int("?" in text or "unknown" in text or "모름" in text))
        return TaskAnalysis(capabilities, difficulty, risk, uncertainty, tuple(sorted(signals)))


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


class AdaptiveRouter:
    """Explainable routing based on task signals, configured policy, and history."""

    def __init__(self, analyzer: TaskAnalyzer, history: ExecutionHistory, profiles: Mapping[str, AgentRoutingProfile] | None = None) -> None:
        self._analyzer = analyzer
        self._history = history
        self._profiles = profiles or default_profiles()

    def select(self, task: Task, agents: Iterable[Agent], requested_agent_id: str = "auto") -> ExecutionPlan:
        analysis = self._analyzer.analyze(task)
        candidates = [agent for agent in agents if agent.supports(analysis.capabilities)]
        if requested_agent_id != "auto":
            candidates = [agent for agent in candidates if agent.agent_id == requested_agent_id]
            if not candidates:
                raise ValueError(f"Requested agent cannot satisfy capabilities: {requested_agent_id}")
        if not candidates:
            raise ValueError("No available agent supports the analyzed capability requirements.")
        scored: list[tuple[float, Agent, dict[str, object]]] = []
        for agent in candidates:
            profile = self._profiles.get(agent.agent_id, AgentRoutingProfile({}, 0.5, 0.5))
            affinity = sum(profile.capability_affinity.get(capability, 1.0) for capability in analysis.capabilities) / max(len(analysis.capabilities), 1)
            complexity_fit = 1 - abs(profile.complexity_preference - analysis.difficulty / 5)
            risk_fit = 1 - abs(profile.risk_preference - analysis.risk / 5)
            metrics = self._history.metrics_for(agent.agent_id)
            evidence = (metrics.success_rate or 0.5) * 0.4 + (metrics.verification_pass_rate or 0.5) * 0.3
            score = affinity * 50 + complexity_fit * 15 + risk_fit * 10 + evidence * 25
            scored.append((score, agent, {"score": round(score, 2), "affinity": round(affinity, 2), "complexity_fit": round(complexity_fit, 2), "risk_fit": round(risk_fit, 2), "history": {"executions": metrics.executions, "success_rate": metrics.success_rate, "verification_pass_rate": metrics.verification_pass_rate}}))
        scored.sort(key=lambda item: (-item[0], item[1].agent_id))
        _, selected, selected_details = scored[0]
        decision = {"requested_agent": requested_agent_id, "selected_agent": selected.agent_id, "candidate_scores": {agent.agent_id: details for _, agent, details in scored}, "rationale": "Highest explainable policy score among agents supporting the analyzed capabilities."}
        return ExecutionPlan(task, selected.agent_id, decision["rationale"], analysis.as_dict(), decision)
