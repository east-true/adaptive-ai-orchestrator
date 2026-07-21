from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Callable, Protocol, Sequence

from adaptive_orchestrator.core.domain import ExecutionStatus


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

    def __init__(self, on_output_line: Callable[[str], None] | None = None) -> None:
        self._on_output_line = on_output_line

    @staticmethod
    def _read_stream(stream, sink: list[str], on_line: Callable[[str], None] | None = None) -> None:
        try:
            for line in iter(stream.readline, ""):
                sink.append(line)
                if on_line is not None:
                    on_line(line)
        finally:
            stream.close()

    def run(self, command: Sequence[str], cwd: Path, timeout_seconds: float | None) -> ProcessResult:
        started = perf_counter()
        command = tuple(command)
        try:
            process = subprocess.Popen(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1)
            assert process.stdout is not None
            assert process.stderr is not None

            stdout_chunks: list[str] = []
            stderr_chunks: list[str] = []
            # Two reader threads keep stdout and stderr draining concurrently so neither pipe can block the child.
            stdout_reader = threading.Thread(
                target=self._read_stream,
                args=(process.stdout, stdout_chunks, self._on_output_line),
                daemon=True,
            )
            stderr_reader = threading.Thread(target=self._read_stream, args=(process.stderr, stderr_chunks), daemon=True)
            stdout_reader.start()
            stderr_reader.start()

            try:
                return_code = process.wait(timeout=timeout_seconds)
                status = ExecutionStatus.COMPLETED if return_code == 0 else ExecutionStatus.FAILED
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                status = ExecutionStatus.TIMED_OUT
                return_code = None
            except BaseException:
                # Do not leave a CLI agent running after the orchestrator is
                # interrupted. Kernel lifecycle telemetry records the terminal
                # interruption while this layer owns child cleanup.
                process.kill()
                process.wait()
                raise
            finally:
                stdout_reader.join()
                stderr_reader.join()

            return ProcessResult(command, status, "".join(stdout_chunks), "".join(stderr_chunks), return_code, (perf_counter() - started) * 1000)
        except OSError as exc:
            return ProcessResult(command, ExecutionStatus.SPAWN_ERROR, "", str(exc), None, (perf_counter() - started) * 1000)
