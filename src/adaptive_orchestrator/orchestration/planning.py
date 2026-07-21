from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from adaptive_orchestrator.core.domain import Task
from adaptive_orchestrator.execution.agents import Agent


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    """A deliberately single-step plan; future planners may expand it."""

    task: Task
    agent_id: str
    rationale: str
    analysis: dict[str, object] | None = None
    decision: dict[str, object] | None = None


class CapabilitySelector:
    """Deterministic v0.1 selector. It does not estimate quality or cost yet."""

    policy_version = "legacy-biased"

    @staticmethod
    def policy_config() -> dict[str, object]:
        return {
            "selector": "capability-selector",
            "selection_rule": "first-capable-in-registry-order",
        }

    def select(self, task: Task, agents: Iterable[Agent], requested_agent_id: str = "auto") -> ExecutionPlan:
        candidates = list(agents)
        if requested_agent_id != "auto":
            candidates = [agent for agent in candidates if agent.agent_id == requested_agent_id]
            if not candidates:
                raise ValueError(f"Unknown agent: {requested_agent_id}")
        for agent in candidates:
            if agent.supports(task.required_capabilities):
                return ExecutionPlan(task, agent.agent_id, "Selected because it satisfies every required capability.")
        requirements = ", ".join(capability.value for capability in task.required_capabilities) or "none"
        raise ValueError(f"No available agent supports required capabilities: {requirements}")
