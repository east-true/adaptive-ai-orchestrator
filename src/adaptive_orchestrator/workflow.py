from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from .domain import EscalationRecord, ExecutionRecord, ExecutionStatus, Task, VerificationStatus
from .escalation import EscalationPolicy
from .kernel import OrchestratorKernel
from .planning import CapabilitySelector, ExecutionPlan
from .verification import CommandVerifier


def execution_succeeded(record: ExecutionRecord) -> bool:
    """True if the record itself, or its escalated attempt, completed and passed/skipped verification."""

    def _ok(candidate: ExecutionRecord) -> bool:
        return candidate.status is ExecutionStatus.COMPLETED and candidate.verification is not None and candidate.verification.status in {
            VerificationStatus.PASSED,
            VerificationStatus.SKIPPED,
        }

    return _ok(record) or bool(record.escalation and _ok(record.escalation.record))


@dataclass(frozen=True, slots=True)
class StepResult:
    plan: ExecutionPlan
    record: ExecutionRecord


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    """The outcome of an explicit, caller-structured sequence of tasks (see `run_plan`)."""

    steps: tuple[StepResult, ...]
    stopped_early: bool

    @property
    def succeeded(self) -> bool:
        return not self.stopped_early and all(execution_succeeded(step.record) for step in self.steps)


class EngineeringWorkflow:
    """Planning, single-agent-first execution, optional verification, and measured escalation.

    `run` handles one task; `run_plan` sequences an explicit, caller-supplied list of tasks through it.
    """

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

    def run_plan(self, tasks: Sequence[Task], requested_agent_id: str = "auto", stop_on_failure: bool = True) -> WorkflowResult:
        """Runs an explicit, caller-structured sequence of tasks through `run`, one step at a time.

        There is no inference of structure from a single task's free-text
        description; the plan's structure is exactly the list the caller
        supplied. Each step reuses the full single-task pipeline (routing,
        execution, verification, escalation) unchanged.
        """
        steps: list[StepResult] = []
        for task in tasks:
            plan, record = self.run(task, requested_agent_id)
            steps.append(StepResult(plan, record))
            if stop_on_failure and not execution_succeeded(record):
                return WorkflowResult(tuple(steps), stopped_early=True)
        return WorkflowResult(tuple(steps), stopped_early=False)

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
