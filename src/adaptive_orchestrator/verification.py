from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .domain import ExecutionStatus, Task, VerificationResult, VerificationStatus
from .process_runner import ProcessRunner

_STATUS_FOR_EXECUTION = {
    ExecutionStatus.COMPLETED: VerificationStatus.PASSED,
    ExecutionStatus.FAILED: VerificationStatus.FAILED,
    ExecutionStatus.TIMED_OUT: VerificationStatus.TIMED_OUT,
    ExecutionStatus.SPAWN_ERROR: VerificationStatus.FAILED,
}
_STATUS_SEVERITY = {VerificationStatus.PASSED: 0, VerificationStatus.TIMED_OUT: 1, VerificationStatus.FAILED: 2}


@dataclass(frozen=True, slots=True)
class CommandVerifier:
    """Runs one or more explicit, shell-free verification commands after successful execution.

    `command` is the original single-check field (e.g. run the test suite);
    `additional_commands` is purely additive (e.g. also lint, also typecheck).
    Every configured command runs regardless of the others' outcome, since
    these are typically independent checks; the aggregate status is the worst
    of the individual outcomes.
    """

    command: Sequence[str] = ()
    timeout_seconds: float | None = None
    additional_commands: Sequence[Sequence[str]] = field(default_factory=tuple)

    def verify(self, task: Task, execution_status: ExecutionStatus, workspace: Path, runner: ProcessRunner) -> VerificationResult:
        commands = ([tuple(self.command)] if self.command else []) + [tuple(item) for item in self.additional_commands]
        if execution_status is not ExecutionStatus.COMPLETED or not commands:
            return VerificationResult(VerificationStatus.SKIPPED)

        worst_status = VerificationStatus.PASSED
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        total_duration_ms = 0.0
        last_exit_code: int | None = None
        for command in commands:
            result = runner.run(command, workspace, self.timeout_seconds or task.time_limit_seconds)
            command_status = _STATUS_FOR_EXECUTION[result.status]
            if _STATUS_SEVERITY[command_status] > _STATUS_SEVERITY[worst_status]:
                worst_status = command_status
            header = " ".join(command)
            if result.stdout:
                stdout_parts.append(f"$ {header}\n{result.stdout}")
            if result.stderr:
                stderr_parts.append(f"$ {header}\n{result.stderr}")
            total_duration_ms += result.duration_ms
            last_exit_code = result.exit_code

        return VerificationResult(
            worst_status,
            tuple(commands),
            "\n\n".join(stdout_parts) or None,
            "\n\n".join(stderr_parts) or None,
            last_exit_code,
            total_duration_ms,
        )
