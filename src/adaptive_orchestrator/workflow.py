from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from typing import Sequence
from uuid import uuid4

from .domain import EscalationRecord, ExecutionRecord, ExecutionStatus, Task, VerificationStatus
from .escalation import EscalationPolicy
from .kernel import OrchestratorKernel
from .planning import CapabilitySelector, ExecutionPlan
from .verification import CommandVerifier, evaluation_projection


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
        policy_config = getattr(selector, "policy_config", None)
        selector_config = policy_config() if callable(policy_config) else {"selector": type(selector).__qualname__}
        config = {
            "selector": selector_config,
            "agents": [
                {"agent_id": agent.agent_id, "agent_base_id": agent.base_id}
                for agent in kernel.agents
            ],
            "escalation": asdict(escalation_policy) if escalation_policy is not None else None,
            "evaluation": verifier.policy_config(),
        }
        encoded_config = json.dumps(config, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        self._policy_version = str(getattr(selector, "policy_version", "legacy-biased"))
        self._config_hash = hashlib.sha256(encoded_config).hexdigest()

    def run(self, task: Task, requested_agent_id: str = "auto") -> tuple[ExecutionPlan, ExecutionRecord]:
        plan = self._selector.select(task, self._kernel.agents, requested_agent_id)
        execution_id = str(uuid4())
        selection_mode = "manual" if requested_agent_id != "auto" else "exploit"
        cohort = "manual" if requested_agent_id != "auto" else "legacy"
        record = self._run_agent(task, plan, execution_id=execution_id, selection_mode=selection_mode, cohort=cohort)

        escalation = None
        escalation_reasons: tuple[str, ...] = ()
        trigger_classes: tuple[str, ...] = ()
        # An explicit agent request is a deliberate override; escalation would silently defeat it.
        if self._escalation_policy is not None and requested_agent_id == "auto":
            decision = self._escalation_policy.decide(plan.analysis, record.status, record.verification.status)
            escalation_reasons = decision.reasons
            trigger_classes = decision.trigger_classes
            if decision.should_escalate:
                next_agent_id = self._next_candidate(plan)
                if next_agent_id is not None:
                    escalated_plan = replace(plan, agent_id=next_agent_id, rationale="Escalated: " + ", ".join(decision.reasons))
                    escalated_record = self._run_agent(
                        task,
                        escalated_plan,
                        execution_id=execution_id,
                        parent_attempt_id=record.attempt_id,
                        selection_mode="escalation",
                        cohort="escalation",
                        escalation_reasons=decision.reasons,
                        trigger_classes=decision.trigger_classes,
                    )
                    self._kernel.log(escalated_record)
                    escalation = EscalationRecord(decision.reasons, next_agent_id, escalated_record, decision.trigger_classes)

        record = replace(
            record,
            escalation=escalation,
            escalation_reasons=escalation_reasons,
            trigger_classes=trigger_classes,
        )
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

    def _run_agent(
        self,
        task: Task,
        plan: ExecutionPlan,
        *,
        execution_id: str,
        parent_attempt_id: str | None = None,
        selection_mode: str,
        cohort: str,
        escalation_reasons: tuple[str, ...] = (),
        trigger_classes: tuple[str, ...] = (),
    ) -> ExecutionRecord:
        record = self._kernel.execute(
            task,
            plan.agent_id,
            log_execution=False,
            execution_id=execution_id,
            parent_attempt_id=parent_attempt_id,
            policy_version=self._policy_version,
            config_hash=self._config_hash,
            selection_mode=selection_mode,
            cohort=cohort,
            routing_evidence_eligible=False,
            escalation_reasons=escalation_reasons,
            trigger_classes=trigger_classes,
        )
        verification, evaluations = self._verifier.verify_with_evaluations(
            task,
            record.status,
            self._kernel.workspace,
            self._kernel.runner,
        )
        return replace(
            record,
            verification=verification,
            evaluations=evaluations,
            evaluation_projection=evaluation_projection(evaluations),
            task_analysis=plan.analysis,
            routing_decision=plan.decision,
        )

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
