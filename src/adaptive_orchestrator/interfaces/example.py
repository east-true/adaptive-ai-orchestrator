from pathlib import Path

from adaptive_orchestrator.core.domain import Capability, ExecutionStatus, Task
from adaptive_orchestrator.execution.agents import CodexAgent
from adaptive_orchestrator.execution.process_runner import ProcessResult, ProcessRunner
from adaptive_orchestrator.infrastructure.logging import JsonlExecutionLogger
from adaptive_orchestrator.orchestration.kernel import OrchestratorKernel


class PreviewRunner(ProcessRunner):
    """Shows the command that would be executed without invoking a coding agent."""

    def run(self, command, cwd, timeout_seconds):
        return ProcessResult(command, ExecutionStatus.COMPLETED, f"Preview: {' '.join(command)}", "", 0, 0.0)


def main() -> None:
    agent = CodexAgent(capabilities=frozenset({Capability.PLANNING}))
    kernel = OrchestratorKernel({agent.agent_id: agent}, JsonlExecutionLogger(Path(".orchestrator/executions.jsonl")), Path.cwd(), runner=PreviewRunner())
    record = kernel.execute(Task("Draft a small implementation plan.", "Validate the kernel flow.", required_capabilities=(Capability.PLANNING,)), agent.agent_id)
    print(record.result or record.error)


if __name__ == "__main__":
    main()
