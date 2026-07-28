from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Sequence

from adaptive_orchestrator.execution import _windows_gate as gate_protocol
from adaptive_orchestrator.execution._windows_job import WindowsJob


_READY_TIMEOUT_SECONDS = 10.0
_POLL_SECONDS = 0.01
_CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)


@dataclass(frozen=True, slots=True)
class WindowsProcessOutcome:
    kind: str
    return_code: int | None = None
    error: str | None = None


class _ParentGuard:
    """A parent-owned byte lock that an unreleased gate can monitor."""

    __slots__ = ("_stream",)

    def __init__(self, stream: BinaryIO) -> None:
        self._stream: BinaryIO | None = stream

    @classmethod
    def acquire(cls, path: Path) -> _ParentGuard:
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        descriptor = os.open(path, flags, 0o600)
        stream: BinaryIO | None = None
        try:
            os.set_inheritable(descriptor, False)
            os.write(descriptor, b"\0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            stream = os.fdopen(descriptor, "r+b", buffering=0)
            descriptor = -1
            cls._lock(stream)
            return cls(stream)
        except BaseException:
            if stream is not None:
                stream.close()
            elif descriptor >= 0:
                os.close(descriptor)
            raise

    @staticmethod
    def _lock(stream: BinaryIO) -> None:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            return

        # The POSIX branch exists only to exercise the launch protocol in CI.
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock(stream: BinaryIO) -> None:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            return

        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def release(self) -> None:
        stream = self._stream
        if stream is None:
            return
        try:
            self._unlock(stream)
        finally:
            stream.close()
            self._stream = None


class WindowsProcessLaunch:
    """Contain a requested Windows command before allowing it to start."""

    __slots__ = (
        "_assigned",
        "_control_dir",
        "_guard",
        "_job",
        "_released",
        "_temporary_directory",
        "_token",
        "process",
    )

    def __init__(
        self,
        *,
        process: subprocess.Popen[str],
        job: WindowsJob,
        guard: _ParentGuard,
        temporary_directory: tempfile.TemporaryDirectory[str],
        token: str,
    ) -> None:
        self.process = process
        self._job: WindowsJob | None = job
        self._guard: _ParentGuard | None = guard
        self._temporary_directory: tempfile.TemporaryDirectory[str] | None = temporary_directory
        self._control_dir = Path(temporary_directory.name)
        self._token = token
        self._assigned = False
        self._released = False

    @classmethod
    def prepare(cls, command: Sequence[str], cwd: Path) -> WindowsProcessLaunch:
        argv = tuple(command)
        if not argv or not all(isinstance(argument, str) for argument in argv):
            raise OSError("command must be a non-empty sequence of strings")

        temporary_directory = tempfile.TemporaryDirectory(prefix="aao-windows-launch-")
        control_dir = Path(temporary_directory.name)
        token = secrets.token_hex(32)
        guard: _ParentGuard | None = None
        job: WindowsJob | None = None
        launch: WindowsProcessLaunch | None = None
        try:
            gate_protocol._atomic_write_json(
                control_dir / gate_protocol.CONFIG_FILE,
                {
                    "protocol": gate_protocol.PROTOCOL_VERSION,
                    "token": token,
                    "argv": list(argv),
                },
            )
            guard = _ParentGuard.acquire(control_dir / gate_protocol.GUARD_FILE)
            job = WindowsJob.create()
            process = subprocess.Popen(
                (
                    sys.executable,
                    "-I",
                    "-S",
                    str(Path(gate_protocol.__file__).resolve()),
                    str(control_dir),
                ),
                cwd=cwd,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,
                creationflags=_CREATE_NEW_PROCESS_GROUP,
                close_fds=True,
            )
            launch = cls(
                process=process,
                job=job,
                guard=guard,
                temporary_directory=temporary_directory,
                token=token,
            )
            process_handle = getattr(process, "_handle", None)
            if process_handle is None:
                raise OSError("Windows launch gate has no assignable native process handle")
            # Assign the exact handle returned by CreateProcess. Reopening by
            # PID would introduce an avoidable exit/PID-reuse race here.
            job.assign_process_handle(process_handle)
            launch._assigned = True
            launch._wait_until_ready()
            return launch
        except BaseException:
            if launch is not None:
                launch.terminate_and_reap()
                launch._close_pipes()
            else:
                if job is not None:
                    try:
                        job.close()
                    except OSError:
                        pass
                if guard is not None:
                    try:
                        guard.release()
                    except OSError:
                        pass
                try:
                    temporary_directory.cleanup()
                except OSError:
                    pass
            raise

    def _wait_until_ready(self) -> None:
        ready_path = self._control_dir / gate_protocol.READY_FILE
        deadline = time.monotonic() + _READY_TIMEOUT_SECONDS
        while True:
            if ready_path.exists():
                try:
                    ready = gate_protocol._read_json(ready_path)
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    raise OSError(f"invalid Windows launch ready marker: {exc}") from exc
                expected_keys = {"protocol", "token", "kind", "gate_pid"}
                gate_pid = ready.get("gate_pid") if isinstance(ready, dict) else None
                if (
                    not isinstance(ready, dict)
                    or set(ready) != expected_keys
                    or ready.get("protocol") != gate_protocol.PROTOCOL_VERSION
                    or ready.get("token") != self._token
                    or ready.get("kind") != "ready"
                    or isinstance(gate_pid, bool)
                    or gate_pid != self.process.pid
                ):
                    raise OSError("invalid Windows launch ready marker")
                return

            return_code = self.process.poll()
            if return_code is not None:
                detail = self._untrusted_error_detail()
                suffix = f": {detail}" if detail else ""
                raise OSError(f"Windows launch gate exited before readiness ({return_code}){suffix}")
            if time.monotonic() >= deadline:
                raise OSError("Windows launch gate did not become ready within 10 seconds")
            time.sleep(_POLL_SECONDS)

    def release(self) -> None:
        if self._released:
            return
        if not self._assigned or self._job is None:
            raise RuntimeError("Windows launch gate is not assigned to a Job")
        if self.process.poll() is not None:
            raise OSError("Windows launch gate exited before release")
        gate_protocol._atomic_write_json(
            self._control_dir / gate_protocol.RELEASE_FILE,
            {
                "protocol": gate_protocol.PROTOCOL_VERSION,
                "token": self._token,
                "kind": "release",
            },
        )
        self._released = True

    def outcome(self) -> WindowsProcessOutcome:
        if not self._released:
            return WindowsProcessOutcome("protocol_error", error="Windows target was never released")
        if self.process.poll() is None:
            return WindowsProcessOutcome("protocol_error", error="Windows launch gate is still running")

        outcome_path = self._control_dir / gate_protocol.OUTCOME_FILE
        try:
            raw = gate_protocol._read_json(outcome_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return WindowsProcessOutcome("protocol_error", error=f"invalid Windows launch outcome: {exc}")
        if (
            not isinstance(raw, dict)
            or raw.get("protocol") != gate_protocol.PROTOCOL_VERSION
            or raw.get("token") != self._token
        ):
            return WindowsProcessOutcome("protocol_error", error="invalid Windows launch outcome identity")

        kind = raw.get("kind")
        gate_return_code = self.process.returncode
        if kind == "completed":
            return_code = raw.get("return_code")
            if (
                set(raw) != {"protocol", "token", "kind", "return_code"}
                or isinstance(return_code, bool)
                or not isinstance(return_code, int)
                or not -0x80000000 <= return_code <= 0xFFFFFFFF
                or gate_return_code != 0
            ):
                return WindowsProcessOutcome("protocol_error", error="invalid completed Windows launch outcome")
            return WindowsProcessOutcome("completed", return_code=return_code)

        if kind in {"spawn_error", "protocol_error"}:
            error = raw.get("error")
            expected_gate_code = (
                gate_protocol.SPAWN_ERROR_EXIT_CODE
                if kind == "spawn_error"
                else gate_protocol.PROTOCOL_ERROR_EXIT_CODE
            )
            if (
                set(raw) != {"protocol", "token", "kind", "error"}
                or not isinstance(error, str)
                or not error
                or len(error) > 8192
                or gate_return_code != expected_gate_code
            ):
                return WindowsProcessOutcome("protocol_error", error="invalid failed Windows launch outcome")
            return WindowsProcessOutcome(kind, error=error)

        return WindowsProcessOutcome("protocol_error", error="unknown Windows launch outcome kind")

    def _untrusted_error_detail(self) -> str | None:
        try:
            raw = gate_protocol._read_json(self._control_dir / gate_protocol.OUTCOME_FILE)
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        error = raw.get("error")
        if raw.get("token") != self._token or not isinstance(error, str):
            return None
        return error[:8192]

    def finish_normal(self) -> None:
        outcome = self.outcome()
        if outcome.kind != "completed":
            raise RuntimeError("only a completed Windows launch can be disarmed")
        job = self._job
        if job is None:
            raise RuntimeError("Windows launch Job is already closed")
        try:
            job.disarm()
            job.close()
            self._job = None
        except BaseException:
            self.terminate_and_reap()
            raise
        self._release_guard_and_files()

    def terminate_and_reap(self) -> None:
        job = self._job
        if job is not None:
            try:
                job.terminate()
            except (OSError, RuntimeError):
                pass
            try:
                job.close()
            except (OSError, RuntimeError):
                pass
            if job.closed:
                self._job = None

        if self.process.poll() is None:
            try:
                self.process.kill()
            except (OSError, ProcessLookupError):
                pass
        try:
            self.process.wait()
        except (OSError, ProcessLookupError):
            pass
        self._release_guard_and_files()

    def close(self) -> None:
        if self._job is not None or self.process.poll() is None:
            self.terminate_and_reap()
        else:
            self._release_guard_and_files()

    def _release_guard_and_files(self) -> None:
        guard = self._guard
        if guard is not None:
            try:
                guard.release()
            except OSError:
                pass
            self._guard = None
        temporary_directory = self._temporary_directory
        if temporary_directory is not None:
            try:
                temporary_directory.cleanup()
            except OSError:
                pass
            self._temporary_directory = None

    def _close_pipes(self) -> None:
        for stream in (self.process.stdout, self.process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
