from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .domain import ExecutionStatus, Task, VerificationResult, VerificationStatus
from .process_runner import ProcessRunner


@dataclass(frozen=True, slots=True)
class CommandVerifier:
    """Runs an explicit, shell-free verification command after successful execution."""

    command: Sequence[str] = ()
    timeout_seconds: float | None = None

    def verify(self, task: Task, execution_status: ExecutionStatus, workspace: Path, runner: ProcessRunner) -> VerificationResult:
        if execution_status is not ExecutionStatus.COMPLETED or not self.command:
            return VerificationResult(VerificationStatus.SKIPPED)
        result = runner.run(self.command, workspace, self.timeout_seconds or task.time_limit_seconds)
        status = {
            ExecutionStatus.COMPLETED: VerificationStatus.PASSED,
            ExecutionStatus.FAILED: VerificationStatus.FAILED,
            ExecutionStatus.TIMED_OUT: VerificationStatus.TIMED_OUT,
            ExecutionStatus.SPAWN_ERROR: VerificationStatus.FAILED,
        }[result.status]
        return VerificationResult(status, result.command, result.stdout or None, result.stderr or None, result.exit_code, result.duration_ms)
