from __future__ import annotations

from dataclasses import replace

from .domain import EscalationRecord, ExecutionRecord, Task
from .escalation import EscalationPolicy
from .kernel import OrchestratorKernel
from .planning import CapabilitySelector, ExecutionPlan
from .verification import CommandVerifier


class EngineeringWorkflow:
    """Planning, single-agent-first execution, optional verification, and measured escalation."""

    def __init__(
        self,
        kernel: OrchestratorKernel,
        selector: CapabilitySelector,
        verifier: CommandVerifier,
        escalation_policy: EscalationPolicy | None = None,
    ) -> None:
        self._kernel = kernel
        self._selector = selector
        self._verifier = verifier
        self._escalation_policy = escalation_policy

    def run(self, task: Task, requested_agent_id: str = "auto") -> tuple[ExecutionPlan, ExecutionRecord]:
        plan = self._selector.select(task, self._kernel.agents, requested_agent_id)
        record = self._run_agent(task, plan)

        escalation = None
        # An explicit agent request is a deliberate override; escalation would silently defeat it.
        if self._escalation_policy is not None and requested_agent_id == "auto":
            decision = self._escalation_policy.decide(plan.analysis, record.status, record.verification.status)
            if decision.should_escalate:
                next_agent_id = self._next_candidate(plan)
                if next_agent_id is not None:
                    escalated_plan = replace(plan, agent_id=next_agent_id, rationale="Escalated: " + ", ".join(decision.reasons))
                    escalated_record = self._run_agent(task, escalated_plan)
                    self._kernel.log(escalated_record)
                    escalation = EscalationRecord(decision.reasons, next_agent_id, escalated_record)

        record = replace(record, escalation=escalation)
        self._kernel.log(record)
        return plan, record

    def _run_agent(self, task: Task, plan: ExecutionPlan) -> ExecutionRecord:
        record = self._kernel.execute(task, plan.agent_id, log_execution=False)
        verification = self._verifier.verify(task, record.status, self._kernel.workspace, self._kernel.runner)
        return replace(record, verification=verification, task_analysis=plan.analysis, routing_decision=plan.decision)

    def _next_candidate(self, plan: ExecutionPlan) -> str | None:
        """The next-best routed candidate, or any other capable agent if the selector kept no ranking."""
        scored_candidates = (plan.decision or {}).get("candidate_scores") or {}
        for agent_id in scored_candidates:
            if agent_id != plan.agent_id:
                return agent_id
        for agent in self._kernel.agents:
            if agent.agent_id != plan.agent_id and agent.supports(plan.task.required_capabilities):
                return agent.agent_id
        return None
