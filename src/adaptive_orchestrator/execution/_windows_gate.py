"""Standalone, stdlib-only launch gate for race-free Windows Job assignment.

This file is executed by absolute path with ``python -I -S``.  Keep it free of
package imports: the isolated interpreter intentionally cannot depend on the
repository, an editable install, or user site customisation.
"""

from __future__ import annotations

import errno
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


PROTOCOL_VERSION = 1
CONFIG_FILE = "request.json"
GUARD_FILE = "parent.guard"
READY_FILE = "ready.json"
RELEASE_FILE = "release.json"
OUTCOME_FILE = "outcome.json"

SPAWN_ERROR_EXIT_CODE = 120
PROTOCOL_ERROR_EXIT_CODE = 121
_POLL_SECONDS = 0.02
_MAX_JSON_BYTES = 1024 * 1024


def _is_lock_contention(error: OSError) -> bool:
    return error.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK} or getattr(
        error,
        "winerror",
        None,
    ) in {32, 33}


def _valid_token(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _read_json(path: Path) -> Any:
    if path.stat().st_size > _MAX_JSON_BYTES:
        raise ValueError(f"protocol file is larger than {_MAX_JSON_BYTES} bytes")
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _atomic_write_json(path: Path, value: object) -> None:
    """Publish one protocol marker only after its complete payload is durable."""
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            descriptor = -1
            # ASCII escaping round-trips every Python string accepted by JSON,
            # including unpaired surrogates that cannot be UTF-8 encoded.
            json.dump(value, stream, ensure_ascii=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _guard_is_held(path: Path) -> bool:
    """Return true only while another process owns the guard-file lock."""
    try:
        stream = path.open("r+b", buffering=0)
    except OSError:
        return False

    with stream:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                if _is_lock_contention(exc):
                    return True
                raise
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            return False

        # This branch also makes the otherwise Windows-only protocol directly
        # testable on POSIX CI without weakening the production handshake.
        import fcntl

        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if _is_lock_contention(exc):
                return True
            raise
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        return False


def _protocol_marker(token: str, kind: str, **values: object) -> dict[str, object]:
    return {"protocol": PROTOCOL_VERSION, "token": token, "kind": kind, **values}


def _write_protocol_error(control_dir: Path, token: str | None, error: str) -> None:
    if token is None or not _valid_token(token):
        return
    try:
        _atomic_write_json(
            control_dir / OUTCOME_FILE,
            _protocol_marker(token, "protocol_error", error=error[:8192]),
        )
    except OSError:
        pass


def _load_request(control_dir: Path) -> tuple[str, list[str]]:
    request = _read_json(control_dir / CONFIG_FILE)
    if not isinstance(request, dict) or set(request) != {"protocol", "token", "argv"}:
        raise ValueError("invalid request fields")
    if request["protocol"] != PROTOCOL_VERSION or not _valid_token(request["token"]):
        raise ValueError("invalid request protocol or token")
    argv = request["argv"]
    if not isinstance(argv, list) or not argv or not all(isinstance(argument, str) for argument in argv):
        raise ValueError("argv must be a non-empty list of strings")
    return request["token"], argv


def _valid_release(path: Path, token: str) -> bool:
    release = _read_json(path)
    return (
        isinstance(release, dict)
        and set(release) == {"protocol", "token", "kind"}
        and release["protocol"] == PROTOCOL_VERSION
        and release["token"] == token
        and release["kind"] == "release"
    )


def run_gate(control_dir: Path) -> int:
    token: str | None = None
    try:
        token, argv = _load_request(control_dir)
        guard_path = control_dir / GUARD_FILE
        if not _guard_is_held(guard_path):
            raise RuntimeError("parent guard is not held")

        _atomic_write_json(
            control_dir / READY_FILE,
            _protocol_marker(token, "ready", gate_pid=os.getpid()),
        )

        release_path = control_dir / RELEASE_FILE
        while True:
            if release_path.exists():
                if not _valid_release(release_path, token):
                    raise RuntimeError("invalid release marker")
                # The release marker is written only after Job assignment.  A
                # final guard check closes the remaining parent-death window.
                if not _guard_is_held(guard_path):
                    raise RuntimeError("parent guard was released before launch")
                break
            if not _guard_is_held(guard_path):
                raise RuntimeError("parent exited before launch release")
            time.sleep(_POLL_SECONDS)

        try:
            # Deliberately inherit cwd, environment, stdin, stdout, and stderr
            # from the gate.  The original argv is passed as a sequence and is
            # never reconstructed through a command shell.
            target = subprocess.Popen(
                argv,
                stdin=sys.stdin,
                stdout=sys.stdout,
                stderr=sys.stderr,
                close_fds=True,
            )
        except (OSError, ValueError) as exc:
            _atomic_write_json(
                control_dir / OUTCOME_FILE,
                _protocol_marker(token, "spawn_error", error=f"{type(exc).__name__}: {exc}"[:8192]),
            )
            return SPAWN_ERROR_EXIT_CODE

        return_code = target.wait()
        _atomic_write_json(
            control_dir / OUTCOME_FILE,
            _protocol_marker(token, "completed", return_code=return_code),
        )
        return 0
    except BaseException as exc:
        _write_protocol_error(control_dir, token, f"{type(exc).__name__}: {exc}")
        return PROTOCOL_ERROR_EXIT_CODE


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1:
        return PROTOCOL_ERROR_EXIT_CODE
    try:
        control_dir = Path(arguments[0])
    except (TypeError, ValueError):
        return PROTOCOL_ERROR_EXIT_CODE
    return run_gate(control_dir)


if __name__ == "__main__":
    raise SystemExit(main())
