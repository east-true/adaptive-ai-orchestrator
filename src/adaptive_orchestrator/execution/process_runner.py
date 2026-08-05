from __future__ import annotations

import os
import signal
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Callable, Protocol, Sequence

from adaptive_orchestrator.core.domain import ExecutionStatus


_WINDOWS_OUTPUT_DRAIN_GRACE_SECONDS = 1.0

# A descendant that placed itself in its own session keeps the inherited stdout
# and stderr pipes open, so the reader threads never observe EOF and killing the
# owned process group cannot reach it. Without a bound, the final drain would
# hold `run` open for as long as that detached process lives, which defeats the
# caller's timeout entirely. Completing normally closes the pipes at once, so
# this grace only elapses when something really is still holding them.
_DETACHED_OUTPUT_DRAIN_GRACE_SECONDS = 2.0


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


class _WindowsOutcome(Protocol):
    kind: str
    return_code: int | None
    error: str | None


class _WindowsLaunch(Protocol):
    process: subprocess.Popen[str]

    def release(self) -> None: ...

    def outcome(self) -> _WindowsOutcome: ...

    def finish_normal(self) -> None: ...

    def terminate_and_reap(self) -> None: ...

    def close(self) -> None: ...


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

    @staticmethod
    def _kill_and_reap(
        process: subprocess.Popen[str],
        windows_launch: _WindowsLaunch | None = None,
    ) -> None:
        """Stop the owned process tree where supported, then reap its root."""
        if windows_launch is not None:
            windows_launch.terminate_and_reap()
            return
        if os.name == "posix":
            try:
                # POSIX children are launched as session leaders below, so the
                # child's PID is also the ID of a group that cannot include the
                # orchestrator or an unrelated shell session.
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError:
                # Retain a direct-child fallback for an unusual platform or a
                # child that changed its process-group state before cleanup.
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
        else:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        process.wait()

    @staticmethod
    def _readers_finished_within(
        readers: Sequence[threading.Thread],
        timeout_seconds: float,
    ) -> bool:
        deadline = perf_counter() + timeout_seconds
        for reader in readers:
            reader.join(timeout=max(0.0, deadline - perf_counter()))
        return not any(reader.is_alive() for reader in readers)

    def run(self, command: Sequence[str], cwd: Path, timeout_seconds: float | None) -> ProcessResult:
        started = perf_counter()
        command = tuple(command)
        windows_launch: _WindowsLaunch | None = None
        try:
            if os.name == "nt":
                # The import is lazy so POSIX-only installations never load
                # Windows APIs. The gate is assigned through Popen's native
                # handle before release, so the target cannot run uncontained
                # and no PID needs to be reopened.
                from adaptive_orchestrator.execution._windows_process import WindowsProcessLaunch

                windows_launch = WindowsProcessLaunch.prepare(command, cwd)
                process = windows_launch.process
            else:
                process = subprocess.Popen(
                    command,
                    cwd=cwd,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=1,
                    # A dedicated POSIX session makes timeout/interrupt cleanup
                    # local to this invocation without touching sibling shells.
                    start_new_session=os.name == "posix",
                )
        except (OSError, ValueError) as exc:
            return ProcessResult(command, ExecutionStatus.SPAWN_ERROR, "", str(exc), None, (perf_counter() - started) * 1000)

        assert process.stdout is not None
        assert process.stderr is not None

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        launch_error: str | None = None
        output_truncated = False
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
            if windows_launch is not None:
                # Releasing only after both drains are live also prevents a
                # noisy, immediate target from filling either pipe at startup.
                windows_launch.release()
            return_code = process.wait(timeout=timeout_seconds)
            if windows_launch is not None:
                outcome = windows_launch.outcome()
                if outcome.kind == "completed":
                    return_code = outcome.return_code
                    assert return_code is not None
                    status = ExecutionStatus.COMPLETED if return_code == 0 else ExecutionStatus.FAILED
                    # Keep the Job armed until both redirected streams reach
                    # EOF. A properly detached descendant that closed its
                    # inherited handles can survive normal completion; one
                    # that still owns the pipes is terminated after a bounded
                    # drain instead of hanging this runner forever.
                    if self._readers_finished_within(
                        (stdout_reader, stderr_reader),
                        _WINDOWS_OUTPUT_DRAIN_GRACE_SECONDS,
                    ):
                        windows_launch.finish_normal()
                    else:
                        self._kill_and_reap(process, windows_launch)
                else:
                    self._kill_and_reap(process, windows_launch)
                    status = ExecutionStatus.SPAWN_ERROR
                    return_code = None
                    launch_error = outcome.error or "Windows launch protocol failed"
            else:
                status = ExecutionStatus.COMPLETED if return_code == 0 else ExecutionStatus.FAILED
        except subprocess.TimeoutExpired:
            self._kill_and_reap(process, windows_launch)
            status = ExecutionStatus.TIMED_OUT
            return_code = None
        except OSError as exc:
            self._kill_and_reap(process, windows_launch)
            status = ExecutionStatus.SPAWN_ERROR
            return_code = None
            launch_error = str(exc)
        except BaseException:
            # Do not leave a CLI agent running after the orchestrator is
            # interrupted. Kernel lifecycle telemetry records the terminal
            # interruption while this layer owns child cleanup.
            try:
                self._kill_and_reap(process, windows_launch)
            except BaseException:
                # Preserve the interruption rather than replacing it with a
                # secondary best-effort cleanup failure.
                pass
            raise
        finally:
            output_truncated = not self._readers_finished_within(
                (stdout_reader, stderr_reader),
                _DETACHED_OUTPUT_DRAIN_GRACE_SECONDS,
            )
            if windows_launch is not None:
                try:
                    windows_launch.close()
                except OSError:
                    pass

        # The reader threads are daemons and may still be appending to a pipe an
        # abandoned descendant holds; copy before joining so the result is built
        # from one stable snapshot.
        stdout = "".join(tuple(stdout_chunks))
        stderr = "".join(tuple(stderr_chunks))
        notes = [note for note in (launch_error, self._truncation_note(output_truncated)) if note]
        for note in notes:
            if stderr and not stderr.endswith("\n"):
                stderr += "\n"
            stderr += note
        return ProcessResult(
            command,
            status,
            stdout,
            stderr,
            return_code,
            (perf_counter() - started) * 1000,
        )

    @staticmethod
    def _truncation_note(output_truncated: bool) -> str | None:
        """Say so when output capture was cut short, rather than silently truncating."""
        if not output_truncated:
            return None
        return (
            "adaptive-orchestrator: stopped collecting output after "
            f"{_DETACHED_OUTPUT_DRAIN_GRACE_SECONDS:g}s because a detached descendant still holds "
            "this command's output pipes; the captured output may be incomplete."
        )
