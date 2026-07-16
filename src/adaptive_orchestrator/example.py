from pathlib import Path

from .agents import CodexAgent
from .domain import Capability, Task
from .kernel import OrchestratorKernel
from .logging import JsonlExecutionLogger
from .process_runner import ProcessResult, ProcessRunner
from .domain import ExecutionStatus


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
