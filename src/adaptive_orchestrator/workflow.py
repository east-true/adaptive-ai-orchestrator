from __future__ import annotations

from dataclasses import replace

from .domain import ExecutionRecord, Task
from .kernel import OrchestratorKernel
from .planning import CapabilitySelector, ExecutionPlan
from .verification import CommandVerifier


class EngineeringWorkflow:
    """Planning, single-agent execution, and optional verification for Kernel v0.1."""

    def __init__(self, kernel: OrchestratorKernel, selector: CapabilitySelector, verifier: CommandVerifier) -> None:
        self._kernel = kernel
        self._selector = selector
        self._verifier = verifier

    def run(self, task: Task, requested_agent_id: str = "auto") -> tuple[ExecutionPlan, ExecutionRecord]:
        plan = self._selector.select(task, self._kernel.agents, requested_agent_id)
        record = self._kernel.execute(task, plan.agent_id, log_execution=False)
        verification = self._verifier.verify(task, record.status, self._kernel.workspace, self._kernel.runner)
        record = replace(record, verification=verification, task_analysis=plan.analysis, routing_decision=plan.decision)
        self._kernel.log(record)
        return plan, record
