from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Protocol, Sequence

from .domain import ExecutionStatus


@dataclass(frozen=True, slots=True)
class ProcessResult:
    command: Sequence[str]
    status: ExecutionStatus
    stdout: str
    stderr: str
    exit_code: int | None
    duration_ms: float


class ProcessRunner(Protocol):
    def run(self, command: Sequence[str], cwd: Path, timeout_seconds: float | None) -> ProcessResult: ...


class SubprocessRunner:
    """Runs a CLI process without a shell and collects its complete result."""

    def run(self, command: Sequence[str], cwd: Path, timeout_seconds: float | None) -> ProcessResult:
        started = perf_counter()
        command = tuple(command)
        try:
            completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False, timeout=timeout_seconds)
            status = ExecutionStatus.COMPLETED if completed.returncode == 0 else ExecutionStatus.FAILED
            return ProcessResult(command, status, completed.stdout, completed.stderr, completed.returncode, (perf_counter() - started) * 1000)
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            return ProcessResult(command, ExecutionStatus.TIMED_OUT, stdout, stderr, None, (perf_counter() - started) * 1000)
        except OSError as exc:
            return ProcessResult(command, ExecutionStatus.SPAWN_ERROR, "", str(exc), None, (perf_counter() - started) * 1000)
