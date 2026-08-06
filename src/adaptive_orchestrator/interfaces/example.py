from pathlib import Path

from adaptive_orchestrator.core.domain import Capability, ExecutionStatus, Task
from adaptive_orchestrator.execution.agents import CodexAgent
from adaptive_orchestrator.execution.process_runner import ProcessResult, ProcessRunner
from adaptive_orchestrator.infrastructure.events import JsonlEventStore
from adaptive_orchestrator.infrastructure.logging import JsonlExecutionLogger
from adaptive_orchestrator.infrastructure.state_paths import resolve_control_state_directory
from adaptive_orchestrator.orchestration.kernel import OrchestratorKernel
from adaptive_orchestrator.routing.state import LifecycleRecorder, RoutingStateStore


class PreviewRunner(ProcessRunner):
    """Shows the command that would be executed without invoking a coding agent."""

    def run(self, command, cwd, timeout_seconds):
        return ProcessResult(command, ExecutionStatus.COMPLETED, f"Preview: {' '.join(command)}", "", 0, 0.0)


def main() -> None:
    workspace = Path.cwd()
    agent = CodexAgent(capabilities=frozenset({Capability.PLANNING}))
    # Resolve the lifecycle log outside the agent-writeable workspace, the way
    # the CLI does. The kernel's own fallback keeps it under the workspace, which
    # is convenient for a throwaway embedding but leaves the log where the agent
    # being orchestrated can reach it.
    control_directory = resolve_control_state_directory(workspace)
    kernel = OrchestratorKernel(
        {agent.agent_id: agent},
        JsonlExecutionLogger(workspace / ".orchestrator" / "executions.jsonl"),
        workspace,
        runner=PreviewRunner(),
        lifecycle_recorder=LifecycleRecorder(
            JsonlEventStore(control_directory / "events.jsonl"),
            RoutingStateStore(control_directory / "routing-state.json"),
        ),
    )
    record = kernel.execute(Task("Draft a small implementation plan.", "Validate the kernel flow.", required_capabilities=(Capability.PLANNING,)), agent.agent_id)
    print(record.result or record.error)


if __name__ == "__main__":
    main()
