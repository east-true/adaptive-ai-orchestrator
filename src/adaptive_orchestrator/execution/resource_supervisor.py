from __future__ import annotations

import codecs
import errno
import hashlib
import json
import math
import os
import resource
import signal
import stat
import subprocess
import sys
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from time import monotonic
from typing import Callable, Mapping, Sequence

from adaptive_orchestrator.core.domain import ExecutionStatus
from adaptive_orchestrator.execution.process_runner import ProcessResult, ProcessRunner


RESOURCE_SUPERVISOR_SCHEMA = "phase2b-posix-resource-supervisor-v2"
_PROC_ROOT = Path("/proc")
_FIXED_FAILURE_PREFIX = "adaptive-orchestrator resource supervisor: killed invocation: "
_READ_CHUNK_BYTES = 64 * 1024
_MAX_CONSECUTIVE_PROC_USAGE_OBSERVATION_FAILURES = 3
_OWNED_CLOSE_ATTEMPTS = 8
_RLIMIT_NPROC_HOST_RACE_RESERVE = 8


class ResourceCapabilityError(RuntimeError):
    """The host cannot enforce every required fallback resource control."""


@dataclass(frozen=True, slots=True)
class ResourceCaps:
    """Pinned limits for one untrusted process-tree invocation.

    RLIMIT values are inherited kernel backstops. Aggregate values are sampled
    by the host-side watchdog and therefore are not described as cgroup-hard
    limits. ``max_processes`` is subtree-local while ``rlimit_nproc`` is kept
    separate because Linux accounts RLIMIT_NPROC against the real UID.
    """

    rlimit_nproc: int
    rlimit_address_space_bytes: int
    rlimit_file_size_bytes: int
    rlimit_open_files: int
    rlimit_core_bytes: int
    rlimit_cpu_seconds: int
    rlimit_message_queue_bytes: int
    rlimit_realtime_priority: int
    rlimit_memlock_bytes: int
    max_processes: int
    max_aggregate_rss_bytes: int
    max_aggregate_cpu_seconds: float
    max_aggregate_write_bytes: int
    max_stdout_bytes: int
    max_stderr_bytes: int
    nice_increment: int = 10
    poll_interval_seconds: float = 0.05
    disk_poll_interval_seconds: float = 0.25
    termination_grace_seconds: float = 2.0
    namespace_tmp_discovery_grace_seconds: float = 2.0

    def __post_init__(self) -> None:
        positive_integers = {
            "rlimit_nproc": self.rlimit_nproc,
            "rlimit_address_space_bytes": self.rlimit_address_space_bytes,
            "rlimit_file_size_bytes": self.rlimit_file_size_bytes,
            "rlimit_open_files": self.rlimit_open_files,
            "rlimit_cpu_seconds": self.rlimit_cpu_seconds,
            "max_processes": self.max_processes,
            "max_aggregate_rss_bytes": self.max_aggregate_rss_bytes,
            "max_aggregate_write_bytes": self.max_aggregate_write_bytes,
            "max_stdout_bytes": self.max_stdout_bytes,
            "max_stderr_bytes": self.max_stderr_bytes,
        }
        for name, value in positive_integers.items():
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        nonnegative_integers = {
            "rlimit_core_bytes": self.rlimit_core_bytes,
            "rlimit_message_queue_bytes": self.rlimit_message_queue_bytes,
            "rlimit_realtime_priority": self.rlimit_realtime_priority,
            "rlimit_memlock_bytes": self.rlimit_memlock_bytes,
            "nice_increment": self.nice_increment,
        }
        for name, value in nonnegative_integers.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        positive_numbers = {
            "max_aggregate_cpu_seconds": self.max_aggregate_cpu_seconds,
            "poll_interval_seconds": self.poll_interval_seconds,
            "disk_poll_interval_seconds": self.disk_poll_interval_seconds,
            "termination_grace_seconds": self.termination_grace_seconds,
            "namespace_tmp_discovery_grace_seconds": (
                self.namespace_tmp_discovery_grace_seconds
            ),
        }
        for name, value in positive_numbers.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a positive finite number")
            if not math.isfinite(float(value)) or float(value) <= 0:
                raise ValueError(f"{name} must be a positive finite number")
        if self.max_processes > self.rlimit_nproc:
            raise ValueError("max_processes cannot exceed rlimit_nproc")
        if self.nice_increment > 19:
            raise ValueError("nice_increment must be at most 19")

    def as_dict(self) -> dict[str, int | float]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class WatchedRootPolicy:
    label: str
    max_allocated_byte_growth: int
    max_file_count_growth: int
    subtract_baseline: bool = True

    def __post_init__(self) -> None:
        if not self.label or not self.label.replace("-", "").replace("_", "").isalnum():
            raise ValueError("watched-root label must contain only letters, digits, '-' or '_'")
        for name, value in (
            ("max_allocated_byte_growth", self.max_allocated_byte_growth),
            ("max_file_count_growth", self.max_file_count_growth),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

    def as_dict(self) -> dict[str, str | int | bool]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class WatchedRoot:
    path: Path
    policy: WatchedRootPolicy


@dataclass(frozen=True, slots=True)
class ResourceInvocationPolicy:
    name: str
    caps: ResourceCaps
    watched_root_policies: tuple[WatchedRootPolicy, ...]
    namespace_tmp_policy: WatchedRootPolicy | None
    require_bubblewrap_pid_namespace: bool = True

    def __post_init__(self) -> None:
        if not self.name or not self.name.replace("-", "").replace("_", "").isalnum():
            raise ValueError("resource invocation name is not path-safe")
        labels = [item.label for item in self.watched_root_policies]
        if len(labels) != len(set(labels)):
            raise ValueError("watched-root policy labels must be unique")
        if self.namespace_tmp_policy is not None and self.namespace_tmp_policy.subtract_baseline:
            raise ValueError("namespace tmp must use absolute rather than baseline-subtracted accounting")
        if not isinstance(self.require_bubblewrap_pid_namespace, bool):
            raise ValueError("require_bubblewrap_pid_namespace must be boolean")

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "caps": self.caps.as_dict(),
            "watched_root_policies": [item.as_dict() for item in self.watched_root_policies],
            "namespace_tmp_policy": (
                None if self.namespace_tmp_policy is None else self.namespace_tmp_policy.as_dict()
            ),
            "kernel_ancestry_anchor": (
                "bubblewrap-private-pid-namespace-init-plus-die-with-parent"
                if self.require_bubblewrap_pid_namespace
                else "not-required-test-only"
            ),
        }


_MIB = 1024 * 1024
_GIB = 1024 * _MIB
_PHASE2B_WORKSPACE_GROWTH = WatchedRootPolicy(
    label="workspace",
    max_allocated_byte_growth=1 * _GIB,
    max_file_count_growth=100_000,
)
_PHASE2B_HOME_GROWTH = WatchedRootPolicy(
    label="agent-home",
    max_allocated_byte_growth=256 * _MIB,
    max_file_count_growth=25_000,
)
_PHASE2B_NAMESPACE_TMP = WatchedRootPolicy(
    label="namespace-tmp",
    max_allocated_byte_growth=1 * _GIB,
    max_file_count_growth=100_000,
    subtract_baseline=False,
)
PHASE2B_AGENT_RESOURCE_POLICY = ResourceInvocationPolicy(
    name="agent",
    caps=ResourceCaps(
        # Linux charges RLIMIT_NPROC to the real UID, including threads in
        # unrelated host processes.  512 leaves room for the frozen 48-task
        # invocation cap on the Phase 2b host while the independent subtree
        # watchdog remains the actual per-invocation process ceiling.
        rlimit_nproc=512,
        rlimit_address_space_bytes=2 * _GIB,
        rlimit_file_size_bytes=512 * _MIB,
        rlimit_open_files=512,
        rlimit_core_bytes=0,
        rlimit_cpu_seconds=330,
        rlimit_message_queue_bytes=0,
        rlimit_realtime_priority=0,
        rlimit_memlock_bytes=0,
        max_processes=48,
        max_aggregate_rss_bytes=3 * _GIB,
        max_aggregate_cpu_seconds=2_400.0,
        max_aggregate_write_bytes=8 * _GIB,
        max_stdout_bytes=32 * _MIB,
        max_stderr_bytes=32 * _MIB,
        nice_increment=10,
        poll_interval_seconds=0.02,
        disk_poll_interval_seconds=0.5,
        termination_grace_seconds=2.0,
        namespace_tmp_discovery_grace_seconds=2.0,
    ),
    watched_root_policies=(_PHASE2B_WORKSPACE_GROWTH, _PHASE2B_HOME_GROWTH),
    namespace_tmp_policy=_PHASE2B_NAMESPACE_TMP,
    require_bubblewrap_pid_namespace=True,
)
PHASE2B_EVALUATOR_RESOURCE_POLICY = ResourceInvocationPolicy(
    name="evaluator",
    caps=ResourceCaps(
        rlimit_nproc=512,
        rlimit_address_space_bytes=2 * _GIB,
        rlimit_file_size_bytes=256 * _MIB,
        rlimit_open_files=512,
        rlimit_core_bytes=0,
        rlimit_cpu_seconds=135,
        rlimit_message_queue_bytes=0,
        rlimit_realtime_priority=0,
        rlimit_memlock_bytes=0,
        max_processes=32,
        max_aggregate_rss_bytes=2 * _GIB,
        max_aggregate_cpu_seconds=720.0,
        max_aggregate_write_bytes=4 * _GIB,
        max_stdout_bytes=16 * _MIB,
        max_stderr_bytes=16 * _MIB,
        nice_increment=10,
        poll_interval_seconds=0.02,
        disk_poll_interval_seconds=0.5,
        termination_grace_seconds=2.0,
        namespace_tmp_discovery_grace_seconds=2.0,
    ),
    watched_root_policies=(_PHASE2B_WORKSPACE_GROWTH, _PHASE2B_HOME_GROWTH),
    namespace_tmp_policy=_PHASE2B_NAMESPACE_TMP,
    require_bubblewrap_pid_namespace=True,
)
PHASE2B_RESOURCE_INVOCATION_POLICIES = (
    PHASE2B_AGENT_RESOURCE_POLICY,
    PHASE2B_EVALUATOR_RESOURCE_POLICY,
)


@dataclass(frozen=True, slots=True)
class ResourceCapabilityAttestation:
    schema_version: str
    enforcement_backend: str
    platform: str
    procfs_observations: tuple[str, ...]
    inherited_rlimits: tuple[str, ...]
    child_environment: str
    child_stdin: str
    child_nice_increment: int
    process_identity_guard: str
    namespace_tmp_accounting: str
    final_usage_scan: str
    cgroup_v2_mounted: bool
    cgroup_delegated: bool
    cgroup_enforced: bool
    cgroup_unavailable_reason: str
    hard_aggregate_kernel_enforcement: bool
    limitations: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["procfs_observations"] = list(self.procfs_observations)
        value["inherited_rlimits"] = list(self.inherited_rlimits)
        value["limitations"] = list(self.limitations)
        return value


@dataclass(frozen=True, slots=True)
class ResourceObservation:
    schema_version: str
    invocation_name: str
    invocation_policy_sha256: str
    outcome_status: str
    reason: str | None
    cleanup_succeeded: bool | None
    final_usage_scan_completed: bool
    namespace_tmp_pinned_before_exec: bool
    peak_processes: int
    peak_aggregate_rss_bytes: int
    observed_aggregate_cpu_seconds: float
    observed_aggregate_write_bytes: int
    stdout_bytes_seen: int
    stderr_bytes_seen: int
    stdout_truncated: bool
    stderr_truncated: bool

    def as_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["cleanup_status"] = (
            "not-required-or-unobserved"
            if self.cleanup_succeeded is None
            else "succeeded" if self.cleanup_succeeded else "failed"
        )
        value["final_usage_scan_status"] = (
            "completed" if self.final_usage_scan_completed else "not-completed"
        )
        return value


@dataclass(frozen=True, slots=True)
class _ProcessIdentity:
    pid: int
    start_ticks: int


@dataclass(frozen=True, slots=True)
class _ProcStat:
    identity: _ProcessIdentity
    state: str
    parent_pid: int
    process_group: int
    session: int
    cpu_ticks: int


@dataclass(frozen=True, slots=True)
class _Usage:
    allocated_bytes: int
    files: int


@dataclass(frozen=True, slots=True)
class _WatchedRootHandle:
    configured_path: Path
    scan_path: Path
    policy: WatchedRootPolicy
    file_descriptor: int
    identity: tuple[int, int]


@dataclass(frozen=True, slots=True)
class _PinnedNamespaceTmp:
    scan_path: Path
    policy: WatchedRootPolicy
    file_descriptor: int
    identity: tuple[int, int]


@dataclass(frozen=True, slots=True)
class _DescriptorIdentity:
    """Identity of the open file description currently occupying an FD."""

    device: int
    inode: int
    mode: int
    device_type: int


@dataclass(frozen=True, slots=True)
class _DescriptorCloseResult:
    closed_or_replaced: bool
    quarantined: bool
    error: BaseException | None


# A persistently unclosable descriptor/stream must remain explicitly owned.
# Keeping a strong reference prevents a later destructor from closing a reused
# numeric FD.  Entries are exceptional fail-closed evidence, not a retry queue:
# retrying later without the caller's terminal context could release a held
# pre-exec barrier or close an unrelated descriptor after number reuse.
_QUARANTINED_OWNED_DESCRIPTORS: dict[int, _DescriptorIdentity | None] = {}
_QUARANTINED_OWNED_STREAMS: list[object] = []
_QUARANTINE_LOCK = threading.Lock()


class _OutputCapture:
    def __init__(
        self,
        maximum_bytes: int,
        reason: str,
        violation: "_Violation",
        on_line: Callable[[str], None] | None,
    ) -> None:
        self._maximum_bytes = maximum_bytes
        self._reason = reason
        self._violation = violation
        self._on_line = on_line
        self._chunks: list[bytes] = []
        self._stored_bytes = 0
        self._seen_bytes = 0
        self._truncated = False
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._line_buffer = ""
        self._lock = threading.Lock()

    def consume(self, chunk: bytes) -> None:
        callback_lines: tuple[str, ...] = ()
        with self._lock:
            self._seen_bytes += len(chunk)
            remaining = max(0, self._maximum_bytes - self._stored_bytes)
            retained = chunk[:remaining]
            if retained:
                self._chunks.append(retained)
                self._stored_bytes += len(retained)
                if self._on_line is not None:
                    decoded = self._decoder.decode(retained, final=False)
                    combined = self._line_buffer + decoded
                    lines = combined.splitlines(keepends=True)
                    if lines and not lines[-1].endswith(("\n", "\r")):
                        self._line_buffer = lines.pop()
                    else:
                        self._line_buffer = ""
                    callback_lines = tuple(lines)
            if len(chunk) > remaining:
                self._truncated = True
                self._violation.set(self._reason)
        if self._on_line is not None:
            for line in callback_lines:
                try:
                    self._on_line(line)
                except BaseException:
                    self._violation.set("stdout-callback-failed")

    def finish_callback(self) -> None:
        if self._on_line is None:
            return
        with self._lock:
            tail = self._decoder.decode(b"", final=True)
            pending = self._line_buffer + tail
            self._line_buffer = ""
        if pending:
            try:
                self._on_line(pending)
            except BaseException:
                self._violation.set("stdout-callback-failed")

    def snapshot(self) -> tuple[str, int, bool]:
        with self._lock:
            raw = b"".join(self._chunks)
            return raw.decode("utf-8", errors="replace"), self._seen_bytes, self._truncated


class _OutputReaderState:
    """Cross-thread terminal evidence for one owned output stream."""

    def __init__(self) -> None:
        self._errors: list[BaseException] = []
        self._terminal = threading.Event()
        self._stream_closed = False
        self._lock = threading.Lock()

    def record_error(self, error: BaseException) -> None:
        with self._lock:
            self._errors.append(error)

    def finish(self, *, stream_closed: bool) -> None:
        with self._lock:
            self._stream_closed = stream_closed
            self._terminal.set()

    @property
    def has_error(self) -> bool:
        with self._lock:
            return bool(self._errors)

    @property
    def terminal(self) -> bool:
        return self._terminal.is_set()

    @property
    def stream_closed(self) -> bool:
        with self._lock:
            return self._stream_closed


class _Violation:
    def __init__(self) -> None:
        self._reason: str | None = None
        self._event = threading.Event()
        self._lock = threading.Lock()

    def set(self, reason: str) -> None:
        with self._lock:
            if self._reason is None:
                self._reason = reason
                self._event.set()

    @property
    def reason(self) -> str | None:
        with self._lock:
            return self._reason

    def wait(self, timeout: float) -> None:
        self._event.wait(timeout)


def _canonical_sha256(value: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def resource_policy_descriptor(
    policies: Sequence[ResourceInvocationPolicy],
    attestation: ResourceCapabilityAttestation,
) -> dict[str, object]:
    """Return a path-free descriptor suitable for exact manifest hash pinning."""

    descriptor: dict[str, object] = {
        "schema_version": RESOURCE_SUPERVISOR_SCHEMA,
        "invocations": [item.as_dict() for item in policies],
        "capability_attestation": attestation.as_dict(),
    }
    descriptor["policy_sha256"] = _canonical_sha256(descriptor)
    return descriptor


def _rlimit_bindings(caps: ResourceCaps) -> tuple[tuple[str, int, int], ...]:
    configured = (
        ("RLIMIT_NPROC", "RLIMIT_NPROC", caps.rlimit_nproc),
        ("RLIMIT_AS", "RLIMIT_AS", caps.rlimit_address_space_bytes),
        ("RLIMIT_FSIZE", "RLIMIT_FSIZE", caps.rlimit_file_size_bytes),
        ("RLIMIT_NOFILE", "RLIMIT_NOFILE", caps.rlimit_open_files),
        ("RLIMIT_CORE", "RLIMIT_CORE", caps.rlimit_core_bytes),
        ("RLIMIT_CPU", "RLIMIT_CPU", caps.rlimit_cpu_seconds),
        ("RLIMIT_MSGQUEUE", "RLIMIT_MSGQUEUE", caps.rlimit_message_queue_bytes),
        ("RLIMIT_RTPRIO", "RLIMIT_RTPRIO", caps.rlimit_realtime_priority),
        ("RLIMIT_MEMLOCK", "RLIMIT_MEMLOCK", caps.rlimit_memlock_bytes),
    )
    result: list[tuple[str, int, int]] = []
    for public_name, attribute, value in configured:
        identifier = getattr(resource, attribute, None)
        if identifier is None:
            raise ResourceCapabilityError(f"required rlimit is unavailable: {public_name}")
        result.append((public_name, identifier, value))
    return tuple(result)


def _path_has_symlink(path: Path) -> bool:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if stat.S_ISLNK(current.lstat().st_mode):
            return True
    return False


def _validate_watched_root(root: WatchedRoot) -> Path:
    configured = root.path.expanduser().absolute()
    if _path_has_symlink(configured):
        raise ResourceCapabilityError(f"watched root contains a symlink: {root.policy.label}")
    resolved = configured.resolve(strict=True)
    observed = resolved.stat(follow_symlinks=False)
    if not stat.S_ISDIR(observed.st_mode):
        raise ResourceCapabilityError(f"watched root is not a directory: {root.policy.label}")
    if observed.st_uid != os.geteuid():
        raise ResourceCapabilityError(f"watched root ownership differs: {root.policy.label}")
    return resolved


def _open_watched_root(root: WatchedRoot) -> _WatchedRootHandle:
    resolved = _validate_watched_root(root)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(resolved, flags)
    try:
        opened = os.fstat(descriptor)
        current = resolved.stat(follow_symlinks=False)
        identity = (opened.st_dev, opened.st_ino)
        if identity != (current.st_dev, current.st_ino):
            raise ResourceCapabilityError(
                f"watched root changed while it was opened: {root.policy.label}"
            )
        if opened.st_uid != os.geteuid() or not stat.S_ISDIR(opened.st_mode):
            raise ResourceCapabilityError(
                f"watched root descriptor is not an owned directory: {root.policy.label}"
            )
        return _WatchedRootHandle(
            configured_path=resolved,
            scan_path=Path(f"/proc/self/fd/{descriptor}"),
            policy=root.policy,
            file_descriptor=descriptor,
            identity=identity,
        )
    except BaseException:
        _close_after_fork(descriptor)
        raise


def _watched_root_stable(root: _WatchedRootHandle) -> bool:
    try:
        by_path = root.configured_path.stat(follow_symlinks=False)
        by_descriptor = os.fstat(root.file_descriptor)
    except OSError:
        return False
    return (
        (by_path.st_dev, by_path.st_ino) == root.identity
        and (by_descriptor.st_dev, by_descriptor.st_ino) == root.identity
        and stat.S_ISDIR(by_path.st_mode)
        and stat.S_ISDIR(by_descriptor.st_mode)
    )


def _descriptor_identity(
    descriptor: int,
) -> tuple[_DescriptorIdentity | None, BaseException | None]:
    """Observe an FD identity, distinguishing EBADF from an interrupted probe."""

    first_error: BaseException | None = None
    for _attempt in range(_OWNED_CLOSE_ATTEMPTS):
        try:
            observed = os.fstat(descriptor)
            return (
                _DescriptorIdentity(
                    device=observed.st_dev,
                    inode=observed.st_ino,
                    mode=observed.st_mode,
                    device_type=observed.st_rdev,
                ),
                first_error,
            )
        except OSError as exc:
            if exc.errno == errno.EBADF:
                return None, None
            if first_error is None:
                first_error = exc
        except BaseException as exc:
            if first_error is None:
                first_error = exc
    return None, first_error or RuntimeError("owned descriptor identity unavailable")


def _quarantine_owned_descriptor(
    descriptor: int,
    identity: _DescriptorIdentity | None,
) -> None:
    with _QUARANTINE_LOCK:
        _QUARANTINED_OWNED_DESCRIPTORS[descriptor] = identity


def _close_owned_descriptor(
    descriptor: int,
    *,
    expected_identity: _DescriptorIdentity | None = None,
    defer_base_exception: bool = False,
) -> _DescriptorCloseResult:
    """Close exactly the owned FD, retrying interruptions without FD-reuse risk.

    POSIX ``close`` may have completed even when a wrapper or signal path raises.
    We therefore compare the descriptor identity before every retry.  EBADF or a
    different identity proves that the original owned description is gone and
    must not be closed again.  If identity/close remains unverifiable, retain an
    explicit quarantine record and report failure instead of claiming cleanup.
    """

    if descriptor < 0:
        return _DescriptorCloseResult(True, False, None)
    identity = expected_identity
    identity_error: BaseException | None = None
    if identity is None:
        identity, identity_error = _descriptor_identity(descriptor)
        if identity is None:
            if identity_error is None:
                return _DescriptorCloseResult(True, False, None)
            _quarantine_owned_descriptor(descriptor, None)
            return _DescriptorCloseResult(False, True, identity_error)
    first_error: BaseException | None = identity_error
    if (
        defer_base_exception
        and first_error is not None
        and not isinstance(first_error, Exception)
    ):
        return _DescriptorCloseResult(False, False, first_error)
    for _attempt in range(_OWNED_CLOSE_ATTEMPTS):
        current, current_error = _descriptor_identity(descriptor)
        if current_error is not None and first_error is None:
            first_error = current_error
        if (
            defer_base_exception
            and current_error is not None
            and not isinstance(current_error, Exception)
        ):
            return _DescriptorCloseResult(False, False, current_error)
        if current is None:
            if current_error is None:
                return _DescriptorCloseResult(True, False, first_error)
            if first_error is None:
                first_error = current_error
            _quarantine_owned_descriptor(descriptor, identity)
            return _DescriptorCloseResult(False, True, first_error)
        if current != identity:
            # The original description was closed and this number was reused.
            # The replacement is not ours and must remain untouched.
            return _DescriptorCloseResult(True, False, first_error)
        try:
            os.close(descriptor)
            return _DescriptorCloseResult(True, False, first_error)
        except OSError as exc:
            if exc.errno == errno.EBADF:
                return _DescriptorCloseResult(True, False, None)
            if first_error is None:
                first_error = exc
        except BaseException as exc:
            if first_error is None:
                first_error = exc
            if defer_base_exception:
                # The caller retains the descriptor and will retry only after
                # its safety boundary (for example killing a blocked bwrap
                # child) has completed.
                return _DescriptorCloseResult(False, False, first_error)
        after, after_error = _descriptor_identity(descriptor)
        if after_error is not None and first_error is None:
            first_error = after_error
        if after is None:
            if after_error is None:
                return _DescriptorCloseResult(True, False, first_error)
            if first_error is None:
                first_error = after_error
            _quarantine_owned_descriptor(descriptor, identity)
            return _DescriptorCloseResult(False, True, first_error)
        if after != identity:
            return _DescriptorCloseResult(True, False, first_error)
    _quarantine_owned_descriptor(descriptor, identity)
    return _DescriptorCloseResult(
        False,
        True,
        first_error or RuntimeError("owned descriptor close could not be verified"),
    )


def _close_after_fork(descriptor: int) -> BaseException | None:
    """Return the first close diagnostic, even when a retry closes the FD."""

    result = _close_owned_descriptor(descriptor)
    return result.error


def _close_owned_descriptors(descriptors: Sequence[int]) -> bool:
    """Visit every owned FD and report whether each original description left."""

    outcomes = tuple(_close_owned_descriptor(descriptor) for descriptor in descriptors)
    return all(item.closed_or_replaced for item in outcomes)


def _close_owned_descriptors_report(
    descriptors: Sequence[int],
) -> tuple[bool, BaseException | None]:
    """Visit all FDs and retain the first transient or persistent diagnostic."""

    outcomes = tuple(_close_owned_descriptor(descriptor) for descriptor in descriptors)
    first_error = next(
        (item.error for item in outcomes if item.error is not None),
        None,
    )
    return all(item.closed_or_replaced for item in outcomes), first_error


def _close_owned_descriptors_strict(descriptors: Sequence[int]) -> bool:
    """Visit all FDs and reject even transient cleanup diagnostics."""

    closed, first_error = _close_owned_descriptors_report(descriptors)
    return closed and first_error is None


def _close_owned_stream_best_effort(
    stream: object,
    *,
    strict: bool = False,
) -> bool:
    """Retry stream closure and quarantine an unverifiably live pipe."""

    descriptor: int | None = None
    identity: _DescriptorIdentity | None = None
    had_error = False
    try:
        descriptor = stream.fileno()  # type: ignore[attr-defined]
    except (OSError, ValueError):
        return True
    except BaseException:
        had_error = True
        pass
    if descriptor is not None:
        identity, identity_error = _descriptor_identity(descriptor)
        had_error = identity_error is not None
        if identity is None and identity_error is None:
            return True
    for _attempt in range(_OWNED_CLOSE_ATTEMPTS):
        try:
            stream.close()  # type: ignore[attr-defined]
        except BaseException:
            had_error = True
            pass
        try:
            if bool(stream.closed):  # type: ignore[attr-defined]
                return not (strict and had_error)
        except BaseException:
            had_error = True
            pass
        if descriptor is not None and identity is not None:
            current, current_error = _descriptor_identity(descriptor)
            had_error = had_error or current_error is not None
            if current is None and current_error is None:
                return not (strict and had_error)
            if current is not None and current != identity:
                return not (strict and had_error)
    with _QUARANTINE_LOCK:
        _QUARANTINED_OWNED_STREAMS.append(stream)
    return False


def _terminate_and_reap_probe_child(child: int) -> BaseException | None:
    """Best-effort SIGKILL/reap, returning cleanup error data without raising."""

    first_error: BaseException | None = None
    killed_or_gone = False
    for _attempt in range(2):
        try:
            os.kill(child, signal.SIGKILL)
            killed_or_gone = True
            break
        except ProcessLookupError:
            killed_or_gone = True
            break
        except BaseException as exc:
            if first_error is None:
                first_error = exc
    if not killed_or_gone and first_error is None:
        first_error = RuntimeError("probe child could not be signaled")

    for _attempt in range(8):
        try:
            waited, _status = os.waitpid(child, 0)
            if waited == child:
                return first_error
        except ChildProcessError:
            return first_error
        except OSError as exc:
            if exc.errno == errno.EINTR:
                continue
            if first_error is None:
                first_error = exc
        except BaseException as exc:
            if first_error is None:
                first_error = exc
    if first_error is None:
        first_error = RuntimeError("probe child could not be reaped")
    return first_error


def _probe_child_procfs() -> None:
    read_fd, write_fd = os.pipe()
    try:
        child = os.fork()
    except BaseException:
        _close_after_fork(read_fd)
        _close_after_fork(write_fd)
        raise
    if child == 0:  # pragma: no cover - parent observes the result
        try:
            if _close_after_fork(read_fd) is not None:
                os._exit(122)
            os.write(write_fd, b"1")
            signal.pause()
        finally:
            os._exit(0)
    try:
        close_result = _close_owned_descriptor(
            write_fd,
            defer_base_exception=True,
        )
        if not close_result.closed_or_replaced or close_result.error is not None:
            raise close_result.error or RuntimeError(
                "procfs capability write descriptor cleanup failed"
            )
        if os.read(read_fd, 1) != b"1":
            raise ResourceCapabilityError("procfs capability child did not start")
        for relative in ("stat", "status", "io"):
            with (_PROC_ROOT / str(child) / relative).open("rb") as stream:
                if not stream.read(1):
                    raise ResourceCapabilityError(f"procfs child {relative} is empty")
        os.stat(_PROC_ROOT / str(child) / "root")
        tmp_descriptor: int | None = None
        try:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            tmp_descriptor = os.open(
                _PROC_ROOT / str(child) / "root" / "tmp",
                flags,
            )
            opened_tmp = os.fstat(tmp_descriptor)
            if not stat.S_ISDIR(opened_tmp.st_mode):
                raise ResourceCapabilityError(
                    "procfs child root/tmp is not a directory"
                )
        finally:
            if tmp_descriptor is not None:
                close_error = _close_after_fork(tmp_descriptor)
                if close_error is not None:
                    raise ResourceCapabilityError(
                        "procfs child root/tmp descriptor cleanup failed"
                    ) from close_error
        children = _PROC_ROOT / str(child) / "task" / str(child) / "children"
        children.read_text(encoding="ascii")
        if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
            raise ResourceCapabilityError("identity-safe pidfd signaling is unavailable")
        pidfd = os.pidfd_open(child, 0)
        close_error = _close_after_fork(pidfd)
        if close_error is not None:
            raise ResourceCapabilityError(
                "procfs child pidfd cleanup failed"
            ) from close_error
    except (OSError, UnicodeError) as exc:
        _close_after_fork(read_fd)
        _close_after_fork(write_fd)
        _terminate_and_reap_probe_child(child)
        raise ResourceCapabilityError("required child procfs observations are unavailable") from exc
    except BaseException:
        _close_after_fork(read_fd)
        _close_after_fork(write_fd)
        _terminate_and_reap_probe_child(child)
        raise
    cleanup_errors = tuple(
        error
        for error in (
            _close_after_fork(read_fd),
            _close_after_fork(write_fd),
            _terminate_and_reap_probe_child(child),
        )
        if error is not None
    )
    if cleanup_errors:
        raise ResourceCapabilityError(
            "required child procfs probe cleanup failed"
        ) from cleanup_errors[0]


def _real_uid_task_count() -> int:
    """Count numeric /proc/<pid>/task entries for this real UID.

    Linux applies RLIMIT_NPROC to tasks (threads), not merely thread-group
    leaders.  Vanishing processes/tasks are ordinary races; malformed or
    persistently unreadable live metadata is a capability failure rather than
    permission to undercount.
    """

    real_uid = os.getuid()
    count = 0
    try:
        process_entries = tuple(_PROC_ROOT.iterdir())
    except OSError as exc:
        raise ResourceCapabilityError("real-UID task inventory is unavailable") from exc
    for entry in process_entries:
        if not entry.name.isdigit():
            continue
        try:
            status = (entry / "status").read_text(
                encoding="ascii",
                errors="strict",
            )
        except (FileNotFoundError, ProcessLookupError):
            continue
        except (OSError, UnicodeError) as exc:
            # A procfs hidepid policy or malformed live status can otherwise
            # make the RLIMIT_NPROC reserve assertion falsely optimistic.
            if entry.exists():
                raise ResourceCapabilityError(
                    "real-UID task owner inventory is unavailable"
                ) from exc
            continue
        owner: int | None = None
        try:
            for line in status.splitlines():
                if line.startswith("Uid:"):
                    fields = line.split()
                    if len(fields) < 2:
                        raise ValueError("short proc Uid record")
                    owner = int(fields[1])
                    break
        except ValueError as exc:
            raise ResourceCapabilityError(
                "real-UID task owner inventory is malformed"
            ) from exc
        if owner is None:
            if entry.exists():
                raise ResourceCapabilityError(
                    "real-UID task owner inventory lacks Uid"
                )
            continue
        if owner != real_uid:
            continue
        try:
            tasks = tuple((entry / "task").iterdir())
        except (FileNotFoundError, ProcessLookupError):
            continue
        except OSError as exc:
            if entry.exists():
                raise ResourceCapabilityError(
                    "real-UID task inventory is unavailable"
                ) from exc
            continue
        count += sum(1 for task in tasks if task.name.isdigit())
    return count


def _probe_rlimits(caps: ResourceCaps) -> tuple[str, ...]:
    bindings = _rlimit_bindings(caps)
    # Take the larger of two race-tolerant snapshots, then reserve room for
    # the entire frozen subtree cap plus a small host-side invocation margin.
    current_task_count = max(_real_uid_task_count(), _real_uid_task_count())
    invocation_reserve = caps.max_processes + _RLIMIT_NPROC_HOST_RACE_RESERVE
    if current_task_count + invocation_reserve > caps.rlimit_nproc:
        raise ResourceCapabilityError(
            "RLIMIT_NPROC lacks reserve above the current real-UID task count"
        )
    for public_name, identifier, requested in bindings:
        _soft, hard = resource.getrlimit(identifier)
        if hard != resource.RLIM_INFINITY and requested > hard:
            raise ResourceCapabilityError(f"configured {public_name} exceeds the inherited hard limit")
    child = os.fork()
    if child == 0:  # pragma: no cover - parent observes the exit status
        try:
            for _name, identifier, requested in bindings:
                resource.setrlimit(identifier, (requested, requested))
            os.nice(caps.nice_increment)
        except BaseException:
            os._exit(121)
        os._exit(0)
    try:
        while True:
            try:
                _pid, status_code = os.waitpid(child, 0)
                break
            except OSError as exc:
                if exc.errno != errno.EINTR:
                    raise
    except BaseException:
        _terminate_and_reap_probe_child(child)
        raise
    if not os.WIFEXITED(status_code) or os.WEXITSTATUS(status_code) != 0:
        raise ResourceCapabilityError("required child rlimit/nice operations failed")
    return tuple(name for name, _identifier, _requested in bindings)


def _cgroup_observation() -> tuple[bool, bool, str]:
    controllers = Path("/sys/fs/cgroup/cgroup.controllers")
    mounted = controllers.is_file()
    if not mounted:
        return False, False, "cgroup-v2-not-mounted"
    try:
        membership = Path("/proc/self/cgroup").read_text(encoding="ascii").splitlines()
        relative = next(line.split("::", 1)[1] for line in membership if "::" in line)
    except (OSError, StopIteration, IndexError):
        return True, False, "cgroup-v2-membership-unavailable"
    current = Path("/sys/fs/cgroup") / relative.lstrip("/")
    delegated = (
        os.access(current, os.W_OK)
        and os.access(current / "cgroup.procs", os.W_OK)
        and os.access(current / "cgroup.subtree_control", os.W_OK)
    )
    if delegated:
        return True, True, "cgroup-v2-delegated-but-not-used-by-fallback-supervisor"
    if not os.access(Path("/sys/fs/cgroup"), os.W_OK):
        return True, False, "cgroup-v2-mounted-read-only-without-delegation"
    return True, False, "cgroup-v2-current-scope-not-delegated"


def probe_resource_capabilities(
    caps: ResourceCaps,
    watched_roots: Sequence[WatchedRoot],
) -> ResourceCapabilityAttestation:
    """Verify the exact fallback controls, raising instead of running partially."""

    if (
        os.name != "posix"
        or not sys.platform.startswith("linux")
        or not _PROC_ROOT.is_dir()
        or not Path("/sys").exists()
    ):
        raise ResourceCapabilityError("the Phase 2b resource supervisor requires Linux procfs")
    if not hasattr(os, "killpg") or not hasattr(os, "fork"):
        raise ResourceCapabilityError("required POSIX process-tree operations are unavailable")
    labels = [root.policy.label for root in watched_roots]
    if len(labels) != len(set(labels)):
        raise ResourceCapabilityError("watched-root labels must be unique")
    for root in watched_roots:
        _validate_watched_root(root)
    _probe_child_procfs()
    rlimits = _probe_rlimits(caps)
    cgroup_mounted, cgroup_delegated, cgroup_reason = _cgroup_observation()
    return ResourceCapabilityAttestation(
        schema_version=RESOURCE_SUPERVISOR_SCHEMA,
        enforcement_backend="inherited-rlimits-plus-host-procfs-watchdog",
        platform="linux-posix-procfs",
        procfs_observations=(
            "stat",
            "status",
            "io",
            "root/tmp-directory-fd",
            "task/children",
        ),
        inherited_rlimits=rlimits,
        child_environment="empty",
        child_stdin="devnull",
        child_nice_increment=caps.nice_increment,
        process_identity_guard="pid-start-ticks-plus-pidfd-signaling",
        namespace_tmp_accounting=(
            "bubblewrap-pre-exec-block-fd-barrier-plus-pinned-directory-fd"
        ),
        final_usage_scan="required-after-process-tree-cleanup-before-result",
        cgroup_v2_mounted=cgroup_mounted,
        cgroup_delegated=cgroup_delegated,
        cgroup_enforced=False,
        cgroup_unavailable_reason=cgroup_reason,
        hard_aggregate_kernel_enforcement=False,
        limitations=(
            "RLIMIT_NPROC is accounted against the real UID rather than only this subtree.",
            "Aggregate RSS, process count, CPU, I/O and disk usage are sampled watchdog limits, not cgroup-hard ceilings.",
            "Processes that start and exit between procfs samples can be absent from aggregate CPU and write-byte observations.",
            "Allocated-block accounting has a mandatory final scan but does not impose a filesystem project quota and can overshoot before cleanup.",
        ),
    )


def _apply_child_limits(caps: ResourceCaps) -> None:
    for _name, identifier, requested in _rlimit_bindings(caps):
        resource.setrlimit(identifier, (requested, requested))
    os.nice(caps.nice_increment)


def _validate_kernel_ancestry_anchor(command: Sequence[str]) -> None:
    if not command:
        raise ResourceCapabilityError("resource-contained command is empty")
    executable = Path(command[0]).expanduser()
    try:
        resolved = executable.resolve(strict=True)
        bubblewrap = Path("/usr/bin/bwrap").resolve(strict=True)
    except OSError as exc:
        raise ResourceCapabilityError("bubblewrap ancestry anchor is unavailable") from exc
    if resolved != bubblewrap:
        raise ResourceCapabilityError("resource-contained command is not the pinned bubblewrap launcher")
    arguments = tuple(command[1:])
    try:
        separator = arguments.index("--")
    except ValueError as exc:
        raise ResourceCapabilityError("bubblewrap command lacks an executable separator") from exc
    namespace_arguments = arguments[:separator]
    required = {"--die-with-parent", "--new-session"}
    if not required.issubset(namespace_arguments):
        raise ResourceCapabilityError("bubblewrap command lacks its parent-death/session anchor")
    if not ({"--unshare-all", "--unshare-pid"} & set(namespace_arguments)):
        raise ResourceCapabilityError("bubblewrap command lacks a private PID namespace")
    if any(
        token in {"--block-fd", "--userns-block-fd", "--info-fd", "--json-status-fd"}
        or token.startswith(("--block-fd=", "--userns-block-fd=", "--info-fd=", "--json-status-fd="))
        for token in namespace_arguments
    ):
        raise ResourceCapabilityError(
            "bubblewrap command contains an unmanaged synchronization descriptor"
        )
    required_read_only_remounts = (("--remount-ro", "/"), ("--remount-ro", "/dev"))
    remount_indices: list[int] = []
    for pair in required_read_only_remounts:
        matches = [
            index
            for index in range(max(0, len(namespace_arguments) - 1))
            if namespace_arguments[index : index + 2] == pair
        ]
        if len(matches) != 1:
            raise ResourceCapabilityError(
                "bubblewrap command lacks its final read-only root/dev remount"
            )
        remount_indices.append(matches[0])
    mount_options = {
        "--bind",
        "--bind-try",
        "--dev",
        "--dev-bind",
        "--dev-bind-try",
        "--dir",
        "--file",
        "--mqueue",
        "--overlay",
        "--proc",
        "--remount-ro",
        "--ro-bind",
        "--ro-bind-try",
        "--symlink",
        "--tmp-overlay",
        "--tmpfs",
    }
    mount_option_indices = [
        index
        for index, token in enumerate(namespace_arguments)
        if token in mount_options
    ]
    if mount_option_indices[-2:] != remount_indices:
        raise ResourceCapabilityError(
            "bubblewrap root/dev read-only remounts are not the final mount operations"
        )


def _with_pre_exec_block_fd(command: Sequence[str], descriptor: int) -> tuple[str, ...]:
    """Insert a trusted bwrap barrier without changing the recorded command."""

    values = tuple(command)
    try:
        boundary = values.index("--")
    except ValueError as exc:  # pragma: no cover - ancestry validation owns this
        raise ResourceCapabilityError("bubblewrap command lacks an executable separator") from exc
    outer = values[1:boundary]
    if not any(
        outer[index : index + 2] == ("--tmpfs", "/tmp")
        for index in range(max(0, len(outer) - 1))
    ):
        raise ResourceCapabilityError(
            "namespace tmp accounting requires bubblewrap --tmpfs /tmp"
        )
    return (*values[:boundary], "--block-fd", str(descriptor), *values[boundary:])


def _host_tmp_identity() -> tuple[int, int]:
    observed = Path("/tmp").stat()
    return observed.st_dev, observed.st_ino


def _pin_namespace_tmp_before_exec(
    root_identity: _ProcessIdentity,
    policy: WatchedRootPolicy,
    process: subprocess.Popen[bytes],
    timeout_seconds: float,
) -> tuple[_PinnedNamespaceTmp, set[_ProcessIdentity]]:
    """Pin the bwrap tmpfs while its command is stopped at ``--block-fd``."""

    deadline = monotonic() + timeout_seconds
    owned: set[_ProcessIdentity] = {root_identity}
    host_identity = _host_tmp_identity()
    while monotonic() < deadline:
        if process.poll() is not None:
            raise ResourceCapabilityError(
                "bubblewrap exited before namespace tmp could be pinned"
            )
        table = _scan_process_table()
        current_root = table.get(root_identity.pid)
        if current_root is None or current_root.identity != root_identity:
            raise ResourceCapabilityError(
                "bubblewrap identity changed before namespace tmp was pinned"
            )
        owned = _owned_processes(root_identity, owned, table)
        for identity in sorted(owned, key=lambda item: item.pid):
            candidate = _PROC_ROOT / str(identity.pid) / "root" / "tmp"
            descriptor: int | None = None
            try:
                observed = candidate.stat()
                candidate_identity = (observed.st_dev, observed.st_ino)
                if candidate_identity == host_identity or not stat.S_ISDIR(observed.st_mode):
                    continue
                flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                descriptor = os.open(candidate, flags)
                opened = os.fstat(descriptor)
                opened_identity = (opened.st_dev, opened.st_ino)
                if opened_identity != candidate_identity or not stat.S_ISDIR(opened.st_mode):
                    if not _close_owned_descriptors((descriptor,)):
                        raise ResourceCapabilityError(
                            "namespace tmp candidate descriptor cleanup failed"
                        )
                    descriptor = None
                    continue
                return (
                    _PinnedNamespaceTmp(
                        scan_path=Path(f"/proc/self/fd/{descriptor}"),
                        policy=policy,
                        file_descriptor=descriptor,
                        identity=opened_identity,
                    ),
                    owned,
                )
            except (FileNotFoundError, PermissionError, ProcessLookupError):
                if descriptor is not None:
                    if not _close_owned_descriptors((descriptor,)):
                        raise ResourceCapabilityError(
                            "namespace tmp candidate descriptor cleanup failed"
                        )
                continue
            except OSError:
                if descriptor is not None:
                    _close_owned_descriptors((descriptor,))
                raise
            except BaseException:
                if descriptor is not None:
                    _close_owned_descriptors((descriptor,))
                raise
        threading.Event().wait(0.005)
    raise ResourceCapabilityError(
        "namespace tmp was unavailable at the bubblewrap pre-exec barrier"
    )


def _read_proc_stat(pid: int) -> _ProcStat:
    raw = (_PROC_ROOT / str(pid) / "stat").read_text(encoding="ascii", errors="strict")
    close = raw.rfind(")")
    if close < 0:
        raise OSError("malformed proc stat")
    fields = raw[close + 2 :].split()
    if len(fields) < 22:
        raise OSError("short proc stat")
    return _ProcStat(
        identity=_ProcessIdentity(pid=pid, start_ticks=int(fields[19])),
        state=fields[0],
        parent_pid=int(fields[1]),
        process_group=int(fields[2]),
        session=int(fields[3]),
        cpu_ticks=int(fields[11]) + int(fields[12]),
    )


def _read_rss_bytes(pid: int) -> int:
    status = (_PROC_ROOT / str(pid) / "status").read_text(
        encoding="ascii", errors="strict"
    )
    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            fields = line.split()
            if len(fields) >= 2:
                return int(fields[1]) * 1024
    return 0


def _read_write_bytes(pid: int) -> int:
    payload = (_PROC_ROOT / str(pid) / "io").read_text(encoding="ascii", errors="strict")
    for line in payload.splitlines():
        if line.startswith("write_bytes:"):
            return int(line.split(":", 1)[1].strip())
    raise OSError("proc io lacks write_bytes")


def _scan_process_table() -> dict[int, _ProcStat]:
    table: dict[int, _ProcStat] = {}
    for entry in _PROC_ROOT.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            table[pid] = _read_proc_stat(pid)
        except (FileNotFoundError, PermissionError, ProcessLookupError, OSError, ValueError):
            continue
    return table


def _owned_processes(
    root_identity: _ProcessIdentity,
    previously_owned: set[_ProcessIdentity],
    table: Mapping[int, _ProcStat],
) -> set[_ProcessIdentity]:
    owned: set[_ProcessIdentity] = set()
    current_root = table.get(root_identity.pid)
    if current_root is not None and current_root.identity == root_identity:
        owned.add(root_identity)
    for identity in previously_owned:
        current = table.get(identity.pid)
        if current is not None and current.identity == identity:
            owned.add(identity)
    changed = True
    while changed:
        parent_pids = {item.pid for item in owned}
        additions = {
            sample.identity
            for sample in table.values()
            if sample.parent_pid in parent_pids and sample.identity not in owned
        }
        changed = bool(additions)
        owned.update(additions)
    return owned


def _scan_usage(path: Path, *, stop_after_bytes: int, stop_after_files: int) -> _Usage:
    allocated = 0
    files = 0
    stack = [path]
    seen: set[tuple[int, int]] = set()
    while stack:
        current = stack.pop()
        try:
            # The scan root can intentionally be an already-pinned
            # /proc/self/fd/<n> magic symlink. Follow that one descriptor, but
            # never follow a candidate-created symlink below the root.
            observed = current.stat(follow_symlinks=current == path)
        except FileNotFoundError:
            continue
        if current != path:
            # File-count policy measures directory entries. Hard links share an
            # inode and allocated blocks, but every name must count before
            # inode de-duplication.
            files += 1
            if files > stop_after_files:
                return _Usage(allocated_bytes=allocated, files=files)
        identity = (observed.st_dev, observed.st_ino)
        if identity in seen:
            continue
        seen.add(identity)
        allocated += observed.st_blocks * 512
        if allocated > stop_after_bytes or files > stop_after_files:
            return _Usage(allocated_bytes=allocated, files=files)
        if not stat.S_ISDIR(observed.st_mode) or stat.S_ISLNK(observed.st_mode):
            continue
        try:
            with os.scandir(current) as entries:
                stack.extend(Path(entry.path) for entry in entries)
        except FileNotFoundError:
            continue
    return _Usage(allocated_bytes=allocated, files=files)


def _usage_reason(
    label: str,
    current: _Usage,
    baseline: _Usage,
    policy: WatchedRootPolicy,
) -> str | None:
    allocated = current.allocated_bytes - (
        baseline.allocated_bytes if policy.subtract_baseline else 0
    )
    files = current.files - (baseline.files if policy.subtract_baseline else 0)
    if allocated > policy.max_allocated_byte_growth:
        return f"watched-root-allocated-byte-limit-exceeded:{label}"
    if files > policy.max_file_count_growth:
        return f"watched-root-file-count-limit-exceeded:{label}"
    return None


def _scan_watched_root_limit(
    root: _WatchedRootHandle,
    baseline: _Usage,
) -> str | None:
    if not _watched_root_stable(root):
        return f"watched-root-identity-changed:{root.policy.label}"
    current = _scan_usage(
        root.scan_path,
        stop_after_bytes=(
            baseline.allocated_bytes + root.policy.max_allocated_byte_growth + 1
        ),
        stop_after_files=baseline.files + root.policy.max_file_count_growth + 1,
    )
    return _usage_reason(root.policy.label, current, baseline, root.policy)


def _scan_pinned_namespace_tmp_limit(root: _PinnedNamespaceTmp) -> str | None:
    opened = os.fstat(root.file_descriptor)
    if (
        (opened.st_dev, opened.st_ino) != root.identity
        or not stat.S_ISDIR(opened.st_mode)
    ):
        return f"watched-root-identity-changed:{root.policy.label}"
    current = _scan_usage(
        root.scan_path,
        stop_after_bytes=root.policy.max_allocated_byte_growth + 1,
        stop_after_files=root.policy.max_file_count_growth + 1,
    )
    return _usage_reason(root.policy.label, current, _Usage(0, 0), root.policy)


def _scan_all_final_usage(
    root_handles: Sequence[_WatchedRootHandle],
    baselines: Mapping[str, _Usage],
    namespace_tmp: _PinnedNamespaceTmp | None,
    violation: _Violation,
) -> bool:
    """Scan every pinned root, preserving the first violation reason."""

    scan_failed = False
    for item in root_handles:
        try:
            final_reason = _scan_watched_root_limit(
                item, baselines[item.policy.label]
            )
            if final_reason is not None:
                violation.set(final_reason)
                if final_reason.startswith("watched-root-identity-changed:"):
                    scan_failed = True
        except (OSError, PermissionError):
            scan_failed = True
            violation.set("resource-final-usage-scan-failed")
    if namespace_tmp is not None:
        try:
            final_reason = _scan_pinned_namespace_tmp_limit(namespace_tmp)
            if final_reason is not None:
                violation.set(final_reason)
                if final_reason.startswith("watched-root-identity-changed:"):
                    scan_failed = True
        except (OSError, PermissionError):
            scan_failed = True
            violation.set("resource-final-usage-scan-failed")
    return not scan_failed


def _read_stream(
    stream,
    capture: _OutputCapture,
    state: _OutputReaderState,
) -> None:
    try:
        while True:
            chunk = stream.read(_READ_CHUNK_BYTES)
            if not chunk:
                break
            capture.consume(chunk)
    except BaseException as exc:
        state.record_error(exc)
    finally:
        try:
            capture.finish_callback()
        except BaseException as exc:
            state.record_error(exc)
        stream_closed = False
        try:
            stream_closed = _close_owned_stream_best_effort(
                stream,
                strict=True,
            )
            if not stream_closed:
                state.record_error(
                    RuntimeError("owned output stream cleanup was not verified")
                )
        except BaseException as exc:  # pragma: no cover - helper is total
            state.record_error(exc)
        finally:
            state.finish(stream_closed=stream_closed)


def _join_output_readers(
    readers: Sequence[threading.Thread],
    states: Sequence[_OutputReaderState],
    deadline: float,
) -> tuple[bool, BaseException | None]:
    """Visit every reader and return complete terminal evidence plus first error."""

    first_error: BaseException | None = None
    for reader in readers:
        try:
            reader.join(timeout=max(0.0, deadline - monotonic()))
        except BaseException as exc:
            if first_error is None:
                first_error = exc
    all_stopped = True
    for reader in readers:
        try:
            if reader.is_alive():
                all_stopped = False
        except BaseException as exc:
            all_stopped = False
            if first_error is None:
                first_error = exc
    state_complete = len(readers) == len(states) and all(
        state.terminal
        and state.stream_closed
        and not state.has_error
        for state in states
    )
    return all_stopped and state_complete, first_error


class SupervisedProcessRunner(ProcessRunner):
    """Linux runner with fail-closed fallback controls for untrusted bwrap trees."""

    def __init__(
        self,
        policies: Sequence[ResourceInvocationPolicy],
        watched_root_paths: Mapping[str, Path],
        *,
        on_output_line: Callable[[str], None] | None = None,
    ) -> None:
        if not policies:
            raise ValueError("at least one resource invocation policy is required")
        self._policies = tuple(policies)
        self._watched_root_paths = dict(watched_root_paths)
        self._on_output_line = on_output_line
        self._invocations = 0
        self.last_observation: ResourceObservation | None = None
        # A barrier is retained only in the pathological case where even a
        # direct SIGKILL/wait fallback cannot prove that the pre-exec bwrap
        # root is dead.  Retaining the writer is safer than authorizing the
        # untrusted payload to cross the barrier.
        self._quarantined_pre_exec_barriers: list[
            tuple[int, subprocess.Popen[bytes]]
        ] = []
        self._active_failure_finalizer: Callable[[BaseException], None] | None = None
        expected_labels = {item.label for policy in policies for item in policy.watched_root_policies}
        if set(self._watched_root_paths) != expected_labels:
            raise ValueError("watched-root paths do not exactly match policy labels")

    def _set_observation(
        self,
        policy: ResourceInvocationPolicy,
        *,
        outcome_status: ExecutionStatus,
        reason: str | None,
        cleanup_succeeded: bool | None,
        final_usage_scan_completed: bool,
        namespace_tmp_pinned_before_exec: bool,
        peak_processes: int = 0,
        peak_aggregate_rss_bytes: int = 0,
        observed_aggregate_cpu_seconds: float = 0.0,
        observed_aggregate_write_bytes: int = 0,
        stdout_bytes_seen: int = 0,
        stderr_bytes_seen: int = 0,
        stdout_truncated: bool = False,
        stderr_truncated: bool = False,
    ) -> None:
        self.last_observation = ResourceObservation(
            schema_version=RESOURCE_SUPERVISOR_SCHEMA,
            invocation_name=policy.name,
            invocation_policy_sha256=_canonical_sha256(policy.as_dict()),
            outcome_status=outcome_status.value,
            reason=reason,
            cleanup_succeeded=cleanup_succeeded,
            final_usage_scan_completed=final_usage_scan_completed,
            namespace_tmp_pinned_before_exec=namespace_tmp_pinned_before_exec,
            peak_processes=peak_processes,
            peak_aggregate_rss_bytes=peak_aggregate_rss_bytes,
            observed_aggregate_cpu_seconds=observed_aggregate_cpu_seconds,
            observed_aggregate_write_bytes=observed_aggregate_write_bytes,
            stdout_bytes_seen=stdout_bytes_seen,
            stderr_bytes_seen=stderr_bytes_seen,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
        )

    def run(
        self,
        command: Sequence[str],
        cwd: Path,
        timeout_seconds: float | None,
    ) -> ProcessResult:
        """Run once, preserving any BaseException after spawned-tree cleanup."""

        self._active_failure_finalizer = None
        try:
            return self._run_impl(command, cwd, timeout_seconds)
        except BaseException as interrupted:
            finalizer = self._active_failure_finalizer
            if finalizer is not None:
                try:
                    finalizer(interrupted)
                except BaseException:
                    # Cleanup/evidence failures are data recorded by the
                    # finalizer when possible; they never replace the host
                    # interruption which initiated terminal handling.
                    pass
            raise
        finally:
            self._active_failure_finalizer = None

    def _run_impl(
        self,
        command: Sequence[str],
        cwd: Path,
        timeout_seconds: float | None,
    ) -> ProcessResult:
        started = monotonic()
        original = tuple(command)
        if self._invocations >= len(self._policies):
            self.last_observation = None
            return ProcessResult(
                original,
                ExecutionStatus.SPAWN_ERROR,
                "",
                "resource invocation policy sequence exhausted",
                None,
                (monotonic() - started) * 1000,
            )
        policy = self._policies[self._invocations]
        self._invocations += 1
        roots = tuple(
            WatchedRoot(self._watched_root_paths[item.label], item)
            for item in policy.watched_root_policies
        )
        opened_root_handles: list[_WatchedRootHandle] = []
        root_handles: tuple[_WatchedRootHandle, ...] = ()
        try:
            if policy.require_bubblewrap_pid_namespace:
                _validate_kernel_ancestry_anchor(original)
            configured_workspace = self._watched_root_paths.get("workspace")
            if (
                configured_workspace is not None
                and cwd.resolve(strict=True)
                != configured_workspace.expanduser().resolve(strict=True)
            ):
                raise ResourceCapabilityError(
                    "resource-contained cwd differs from its watched workspace"
                )
            probe_resource_capabilities(policy.caps, roots)
            for item in roots:
                opened_root_handles.append(_open_watched_root(item))
            root_handles = tuple(opened_root_handles)
            baselines = {
                item.policy.label: _scan_usage(
                    item.scan_path,
                    stop_after_bytes=2**63 - 1,
                    stop_after_files=2**63 - 1,
                )
                for item in root_handles
            }
        except (OSError, ResourceCapabilityError, ValueError) as exc:
            cleanup_completed = _close_owned_descriptors(
                tuple(item.file_descriptor for item in opened_root_handles)
            )
            self._set_observation(
                policy,
                outcome_status=ExecutionStatus.SPAWN_ERROR,
                reason="resource-capability-probe-failed",
                cleanup_succeeded=None if cleanup_completed else False,
                final_usage_scan_completed=False,
                namespace_tmp_pinned_before_exec=False,
            )
            return ProcessResult(
                original,
                ExecutionStatus.SPAWN_ERROR,
                "",
                f"resource capability probe failed: {exc}",
                None,
                (monotonic() - started) * 1000,
            )
        except BaseException as interrupted:
            cleanup_completed = _close_owned_descriptors(
                tuple(item.file_descriptor for item in opened_root_handles)
            )
            try:
                self._set_observation(
                    policy,
                    outcome_status=ExecutionStatus.FAILED,
                    reason=f"supervisor-interrupted:{type(interrupted).__name__}",
                    cleanup_succeeded=None if cleanup_completed else False,
                    final_usage_scan_completed=False,
                    namespace_tmp_pinned_before_exec=False,
                )
            except BaseException:
                pass
            raise
        block_read_fd: int | None = None
        block_write_fd: int | None = None
        launch_command = original
        try:
            if policy.namespace_tmp_policy is not None:
                block_read_fd, block_write_fd = os.pipe()
                launch_command = _with_pre_exec_block_fd(original, block_read_fd)
            process = subprocess.Popen(
                launch_command,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={},
                start_new_session=True,
                pass_fds=(() if block_read_fd is None else (block_read_fd,)),
                preexec_fn=lambda: _apply_child_limits(policy.caps),
            )
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            cleanup_completed = _close_owned_descriptors(
                (
                    *(
                        descriptor
                        for descriptor in (block_read_fd, block_write_fd)
                        if descriptor is not None
                    ),
                    *(item.file_descriptor for item in root_handles),
                )
            )
            self._set_observation(
                policy,
                outcome_status=ExecutionStatus.SPAWN_ERROR,
                reason="resource-contained-spawn-failed",
                cleanup_succeeded=None if cleanup_completed else False,
                final_usage_scan_completed=False,
                namespace_tmp_pinned_before_exec=False,
            )
            return ProcessResult(
                original,
                ExecutionStatus.SPAWN_ERROR,
                "",
                f"resource-contained spawn failed: {exc}",
                None,
                (monotonic() - started) * 1000,
            )
        except BaseException as interrupted:
            cleanup_completed = _close_owned_descriptors(
                (
                    *(
                        descriptor
                        for descriptor in (block_read_fd, block_write_fd)
                        if descriptor is not None
                    ),
                    *(item.file_descriptor for item in root_handles),
                )
            )
            try:
                self._set_observation(
                    policy,
                    outcome_status=ExecutionStatus.FAILED,
                    reason=f"supervisor-interrupted:{type(interrupted).__name__}",
                    cleanup_succeeded=None if cleanup_completed else False,
                    final_usage_scan_completed=False,
                    namespace_tmp_pinned_before_exec=False,
                )
            except BaseException:
                pass
            raise
        violation = _Violation()
        stdout_capture: _OutputCapture | None = None
        stderr_capture: _OutputCapture | None = None
        readers: tuple[threading.Thread, ...] = ()
        reader_states: tuple[_OutputReaderState, ...] = ()
        root_pidfd: int | None = None
        owned: set[_ProcessIdentity] = set()
        namespace_tmp: _PinnedNamespaceTmp | None = None
        peak_processes = 1
        peak_rss = 0
        aggregate_cpu = 0.0
        aggregate_write = 0
        terminal_finalized = False

        def preserve_interruption_after_spawn(
            interrupted: BaseException,
            *,
            owned_processes: set[_ProcessIdentity],
            pinned_root_pidfd: int | None,
            pinned_namespace_tmp: _PinnedNamespaceTmp | None,
            outcome_status: ExecutionStatus = ExecutionStatus.FAILED,
            peak_process_count: int = 1,
            peak_rss_bytes: int = 0,
            aggregate_cpu_seconds: float = 0.0,
            aggregate_write_bytes: int = 0,
        ) -> None:
            """Best-effort kill, evidence, and descriptor closure before re-raise."""

            nonlocal block_read_fd, block_write_fd, terminal_finalized
            if terminal_finalized:
                return
            terminal_finalized = True
            cleaned = False
            all_scans_returned = False
            descriptor_cleanup_completed = True
            try:
                cleaned = self._kill_owned(
                    process,
                    owned_processes,
                    policy.caps.termination_grace_seconds,
                    root_pidfd=pinned_root_pidfd,
                )
            except BaseException:
                cleaned = False
            # A cleanup helper can fail or pessimistically return False.  Make
            # one independent attempt to kill and reap the namespace root so
            # that the pre-exec barrier is released only after root death is
            # directly observed.  Keep ``cleaned`` pessimistic: root death is
            # not proof that every non-namespace descendant was reaped.
            root_terminated = cleaned
            if not root_terminated:
                try:
                    if pinned_root_pidfd is not None:
                        try:
                            signal.pidfd_send_signal(
                                pinned_root_pidfd, signal.SIGKILL, None, 0
                            )
                        except (OSError, ProcessLookupError, PermissionError):
                            pass
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except (OSError, ProcessLookupError, PermissionError):
                        pass
                    try:
                        process.kill()
                    except (OSError, ProcessLookupError, PermissionError):
                        pass
                    try:
                        process.wait(
                            timeout=policy.caps.termination_grace_seconds
                        )
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                    root_terminated = process.poll() is not None
                except BaseException:
                    root_terminated = False
            # Never release the pre-exec barrier merely because cleanup was
            # attempted.  If root death remains unprovable, quarantine the
            # writer with the process object so the payload stays blocked.
            if block_write_fd is not None:
                if root_terminated:
                    descriptor_cleanup_completed = _close_owned_descriptors(
                        (block_write_fd,)
                    )
                    if not descriptor_cleanup_completed:
                        self._quarantined_pre_exec_barriers.append(
                            (block_write_fd, process)
                        )
                else:
                    self._quarantined_pre_exec_barriers.append(
                        (block_write_fd, process)
                    )
                block_write_fd = None
            try:
                all_scans_returned = _scan_all_final_usage(
                    root_handles,
                    baselines,
                    pinned_namespace_tmp,
                    violation,
                )
            except BaseException:
                violation.set("resource-final-usage-scan-failed")
                all_scans_returned = False
            drain_deadline = monotonic() + policy.caps.termination_grace_seconds
            readers_terminal, _reader_join_error = _join_output_readers(
                readers,
                reader_states,
                drain_deadline,
            )
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    descriptor_cleanup_completed = (
                        _close_owned_stream_best_effort(stream)
                        and descriptor_cleanup_completed
                    )
            second_terminal, _second_join_error = _join_output_readers(
                readers,
                reader_states,
                monotonic() + policy.caps.termination_grace_seconds,
            )
            readers_terminal = readers_terminal or second_terminal
            if not readers_terminal:
                descriptor_cleanup_completed = False
            stdout_seen = 0
            stderr_seen = 0
            stdout_truncated = False
            stderr_truncated = False
            if stdout_capture is not None:
                try:
                    _stdout, stdout_seen, stdout_truncated = (
                        stdout_capture.snapshot()
                    )
                except BaseException:
                    pass
            if stderr_capture is not None:
                try:
                    _stderr, stderr_seen, stderr_truncated = (
                        stderr_capture.snapshot()
                    )
                except BaseException:
                    pass
            descriptors = (
                *(() if block_read_fd is None else (block_read_fd,)),
                *(
                    ()
                    if pinned_root_pidfd is None
                    else (pinned_root_pidfd,)
                ),
                *(item.file_descriptor for item in root_handles),
                *(
                    ()
                    if pinned_namespace_tmp is None
                    else (pinned_namespace_tmp.file_descriptor,)
                ),
            )
            descriptor_cleanup_completed = (
                _close_owned_descriptors(descriptors)
                and descriptor_cleanup_completed
            )
            block_read_fd = None
            try:
                self._set_observation(
                    policy,
                    outcome_status=outcome_status,
                    reason=(
                        violation.reason
                        or f"supervisor-interrupted:{type(interrupted).__name__}"
                    ),
                    cleanup_succeeded=(
                        cleaned and descriptor_cleanup_completed
                    ),
                    final_usage_scan_completed=(
                        cleaned
                        and descriptor_cleanup_completed
                        and all_scans_returned
                    ),
                    namespace_tmp_pinned_before_exec=(
                        pinned_namespace_tmp is not None
                    ),
                    peak_processes=peak_process_count,
                    peak_aggregate_rss_bytes=peak_rss_bytes,
                    observed_aggregate_cpu_seconds=aggregate_cpu_seconds,
                    observed_aggregate_write_bytes=aggregate_write_bytes,
                    stdout_bytes_seen=stdout_seen,
                    stderr_bytes_seen=stderr_seen,
                    stdout_truncated=stdout_truncated,
                    stderr_truncated=stderr_truncated,
                )
            except BaseException:
                pass

        # Install the one outer post-Popen finalizer before the first parent
        # operation which can fail.  Every later BaseException therefore
        # reaches the same idempotent kill -> scan -> drain -> evidence path.
        self._active_failure_finalizer = lambda interrupted: (
            preserve_interruption_after_spawn(
                interrupted,
                owned_processes=owned,
                pinned_root_pidfd=root_pidfd,
                pinned_namespace_tmp=namespace_tmp,
                peak_process_count=peak_processes,
                peak_rss_bytes=peak_rss,
                aggregate_cpu_seconds=aggregate_cpu,
                aggregate_write_bytes=aggregate_write,
            )
        )

        if block_read_fd is not None:
            close_result = _close_owned_descriptor(
                block_read_fd,
                defer_base_exception=True,
            )
            if not close_result.closed_or_replaced:
                raise close_result.error or RuntimeError(
                    "pre-exec barrier read descriptor cleanup failed"
                )
            block_read_fd = None
        assert process.stdout is not None
        assert process.stderr is not None
        stdout_capture = _OutputCapture(
            policy.caps.max_stdout_bytes,
            "stdout-byte-limit-exceeded",
            violation,
            self._on_output_line,
        )
        stderr_capture = _OutputCapture(
            policy.caps.max_stderr_bytes,
            "stderr-byte-limit-exceeded",
            violation,
            None,
        )
        reader_states = (_OutputReaderState(), _OutputReaderState())
        readers = (
            threading.Thread(
                target=_read_stream,
                args=(process.stdout, stdout_capture, reader_states[0]),
                daemon=True,
            ),
            threading.Thread(
                target=_read_stream,
                args=(process.stderr, stderr_capture, reader_states[1]),
                daemon=True,
            ),
        )

        try:
            for reader in readers:
                reader.start()
        except BaseException as interrupted:
            preserve_interruption_after_spawn(
                interrupted,
                owned_processes=set(),
                pinned_root_pidfd=None,
                pinned_namespace_tmp=None,
            )
            raise

        try:
            root_pidfd = os.pidfd_open(process.pid, 0)
            root_identity = _read_proc_stat(process.pid).identity
        except (OSError, ValueError) as exc:
            # Keep bwrap's trusted pre-exec barrier held until every process
            # which could cross it has been killed. Closing the writer first
            # would briefly authorize the untrusted payload to execute.
            violation.set("resource-watchdog-child-identification-failed")
            preserve_interruption_after_spawn(
                exc,
                owned_processes=set(),
                pinned_root_pidfd=root_pidfd,
                pinned_namespace_tmp=None,
                outcome_status=ExecutionStatus.SPAWN_ERROR,
            )
            return ProcessResult(
                original,
                ExecutionStatus.SPAWN_ERROR,
                "",
                f"resource watchdog could not identify child: {exc}",
                None,
                (monotonic() - started) * 1000,
            )
        except BaseException as interrupted:
            preserve_interruption_after_spawn(
                interrupted,
                owned_processes=set(),
                pinned_root_pidfd=root_pidfd,
                pinned_namespace_tmp=None,
            )
            raise

        owned = {root_identity}
        if policy.namespace_tmp_policy is not None:
            try:
                namespace_tmp, owned = _pin_namespace_tmp_before_exec(
                    root_identity,
                    policy.namespace_tmp_policy,
                    process,
                    policy.caps.namespace_tmp_discovery_grace_seconds,
                )
                assert block_write_fd is not None
                os.write(block_write_fd, b"1")
            except (OSError, ResourceCapabilityError, ValueError) as exc:
                # A failed pin must never release the bwrap command. Kill the
                # blocked tree first, then close the synchronization writer.
                violation.set("namespace-tmp-pre-exec-pin-failed")
                preserve_interruption_after_spawn(
                    exc,
                    owned_processes=owned,
                    pinned_root_pidfd=root_pidfd,
                    pinned_namespace_tmp=namespace_tmp,
                    outcome_status=ExecutionStatus.SPAWN_ERROR,
                )
                return ProcessResult(
                    original,
                    ExecutionStatus.SPAWN_ERROR,
                    "",
                    f"resource watchdog could not pin namespace tmp: {exc}",
                    None,
                    (monotonic() - started) * 1000,
                )
            except BaseException as interrupted:
                preserve_interruption_after_spawn(
                    interrupted,
                    owned_processes=owned,
                    pinned_root_pidfd=root_pidfd,
                    pinned_namespace_tmp=namespace_tmp,
                )
                raise
            finally:
                if block_write_fd is not None:
                    # Let the outer post-spawn finalizer kill/reap before it
                    # retries a close interrupted before the syscall.  A
                    # retry here would release the untrusted pre-exec barrier.
                    close_result = _close_owned_descriptor(
                        block_write_fd,
                        defer_base_exception=True,
                    )
                    if not close_result.closed_or_replaced:
                        raise close_result.error or RuntimeError(
                            "pre-exec barrier descriptor cleanup failed"
                        )
                    block_write_fd = None
        previous_cpu: dict[_ProcessIdentity, int] = {}
        previous_write: dict[_ProcessIdentity, int] = {}
        usage_observation_failures: dict[_ProcessIdentity, int] = {}
        try:
            ticks_per_second = os.sysconf("SC_CLK_TCK")
        except BaseException as interrupted:
            preserve_interruption_after_spawn(
                interrupted,
                owned_processes=owned,
                pinned_root_pidfd=root_pidfd,
                pinned_namespace_tmp=namespace_tmp,
            )
            raise
        deadline = None if timeout_seconds is None else started + timeout_seconds
        next_disk_scan = started
        timed_out = False
        return_code: int | None = None
        cleanup_succeeded: bool | None = None
        final_usage_scan_completed = False
        try:
            while True:
                now = monotonic()
                if deadline is not None and now >= deadline:
                    timed_out = True
                    break
                if any(state.has_error for state in reader_states):
                    violation.set("process-output-capture-failed")
                    break
                if violation.reason is not None:
                    break
                return_code = process.poll()
                if return_code is not None:
                    # Poll before procfs enrichment so a short, already-exited
                    # command is not mistaken for a watchdog-read failure while
                    # its zombie proc entries are being reaped.
                    table = _scan_process_table()
                    remaining = _owned_processes(root_identity, owned, table)
                    remaining.discard(root_identity)
                    if remaining:
                        cleanup_succeeded = self._kill_owned(
                            process,
                            remaining,
                            policy.caps.termination_grace_seconds,
                            root_pidfd=root_pidfd,
                        )
                        if not cleanup_succeeded:
                            violation.set("process-tree-cleanup-failed")
                    break
                table = _scan_process_table()
                current_root = table.get(root_identity.pid)
                if current_root is None or current_root.identity != root_identity:
                    # The trusted bubblewrap root can exit normally after the
                    # poll above and before this procfs snapshot. Recheck the
                    # direct child before treating a missing entry as a
                    # watchdog failure; a still-running or identity-mismatched
                    # child remains fail-closed.
                    return_code = process.poll()
                    if return_code is not None:
                        remaining = _owned_processes(root_identity, owned, table)
                        remaining.discard(root_identity)
                        if remaining:
                            cleanup_succeeded = self._kill_owned(
                                process,
                                remaining,
                                policy.caps.termination_grace_seconds,
                                root_pidfd=root_pidfd,
                            )
                            if not cleanup_succeeded:
                                violation.set("process-tree-cleanup-failed")
                        break
                    violation.set("resource-watchdog-observation-failed")
                    break
                owned = _owned_processes(root_identity, owned, table)
                observed_owned = [table[item.pid] for item in owned if item.pid in table]
                live = [item for item in observed_owned if item.state != "Z"]
                peak_processes = max(peak_processes, len(observed_owned))
                if len(observed_owned) > policy.caps.max_processes:
                    violation.set("process-count-limit-exceeded")
                    break
                current_cpu: dict[_ProcessIdentity, int] = {}
                current_write: dict[_ProcessIdentity, int] = {}
                rss = 0
                observation_failed = False
                for sample in live:
                    identity = sample.identity
                    current_cpu[identity] = sample.cpu_ticks
                    aggregate_cpu += max(
                        0,
                        sample.cpu_ticks - previous_cpu.get(identity, 0),
                    ) / ticks_per_second
                    try:
                        rss += _read_rss_bytes(identity.pid)
                        write_bytes = _read_write_bytes(identity.pid)
                    except (FileNotFoundError, ProcessLookupError):
                        continue
                    except (OSError, PermissionError, UnicodeError, ValueError):
                        # A process can become a zombie after the table sample
                        # but before its status/io enrichment. Treat that as an
                        # ordinary exit. A user-namespace child can also be
                        # transiently non-dumpable while it execs; tolerate only
                        # a bounded consecutive streak, then fail closed if the
                        # live, same-identity process remains unobservable.
                        try:
                            refreshed = _read_proc_stat(identity.pid)
                        except (FileNotFoundError, ProcessLookupError):
                            usage_observation_failures.pop(identity, None)
                            continue
                        except (OSError, PermissionError, UnicodeError, ValueError):
                            observation_failed = True
                            break
                        if refreshed.identity != identity or refreshed.state == "Z":
                            usage_observation_failures.pop(identity, None)
                            continue
                        failures = usage_observation_failures.get(identity, 0) + 1
                        usage_observation_failures[identity] = failures
                        if (
                            failures
                            >= _MAX_CONSECUTIVE_PROC_USAGE_OBSERVATION_FAILURES
                        ):
                            observation_failed = True
                            break
                        continue
                    usage_observation_failures.pop(identity, None)
                    current_write[identity] = write_bytes
                    aggregate_write += max(
                        0,
                        write_bytes - previous_write.get(identity, 0),
                    )
                if observation_failed:
                    violation.set("resource-watchdog-observation-failed")
                    break
                previous_cpu = current_cpu
                previous_write = current_write
                usage_observation_failures = {
                    identity: failures
                    for identity, failures in usage_observation_failures.items()
                    if identity in owned
                }
                peak_rss = max(peak_rss, rss)
                if rss > policy.caps.max_aggregate_rss_bytes:
                    violation.set("aggregate-rss-byte-limit-exceeded")
                    break
                if aggregate_cpu > policy.caps.max_aggregate_cpu_seconds:
                    violation.set("aggregate-cpu-time-limit-exceeded")
                    break
                if aggregate_write > policy.caps.max_aggregate_write_bytes:
                    violation.set("aggregate-write-byte-limit-exceeded")
                    break
                if now >= next_disk_scan:
                    try:
                        for item in root_handles:
                            reason = _scan_watched_root_limit(
                                item, baselines[item.policy.label]
                            )
                            if reason is not None:
                                violation.set(reason)
                                break
                    except (OSError, PermissionError):
                        violation.set("resource-watchdog-observation-failed")
                    if violation.reason is not None:
                        break
                    if namespace_tmp is not None:
                        try:
                            reason = _scan_pinned_namespace_tmp_limit(namespace_tmp)
                            if reason is not None:
                                violation.set(reason)
                        except (OSError, PermissionError):
                            violation.set("resource-watchdog-observation-failed")
                        if violation.reason is not None:
                            break
                    next_disk_scan = now + policy.caps.disk_poll_interval_seconds
                violation.wait(policy.caps.poll_interval_seconds)
        except BaseException as interrupted:
            preserve_interruption_after_spawn(
                interrupted,
                owned_processes=owned,
                pinned_root_pidfd=root_pidfd,
                pinned_namespace_tmp=namespace_tmp,
                peak_process_count=peak_processes,
                peak_rss_bytes=peak_rss,
                aggregate_cpu_seconds=aggregate_cpu,
                aggregate_write_bytes=aggregate_write,
            )
            raise

        if timed_out or violation.reason is not None:
            try:
                cleaned = self._kill_owned(
                    process,
                    owned,
                    policy.caps.termination_grace_seconds,
                    root_pidfd=root_pidfd,
                )
            except BaseException as interrupted:
                preserve_interruption_after_spawn(
                    interrupted,
                    owned_processes=owned,
                    pinned_root_pidfd=root_pidfd,
                    pinned_namespace_tmp=namespace_tmp,
                    peak_process_count=peak_processes,
                    peak_rss_bytes=peak_rss,
                    aggregate_cpu_seconds=aggregate_cpu,
                    aggregate_write_bytes=aggregate_write,
                )
                raise
            cleanup_succeeded = cleaned
            if not cleaned and violation.reason is None:
                violation.set("process-tree-cleanup-failed")
            return_code = None
        else:
            try:
                return_code = process.wait(timeout=policy.caps.termination_grace_seconds)
                if cleanup_succeeded is None:
                    cleanup_succeeded = True
            except subprocess.TimeoutExpired:
                violation.set("process-reap-timeout")
                try:
                    cleanup_succeeded = self._kill_owned(
                        process,
                        owned,
                        policy.caps.termination_grace_seconds,
                        root_pidfd=root_pidfd,
                    )
                except BaseException as interrupted:
                    preserve_interruption_after_spawn(
                        interrupted,
                        owned_processes=owned,
                        pinned_root_pidfd=root_pidfd,
                        pinned_namespace_tmp=namespace_tmp,
                        peak_process_count=peak_processes,
                        peak_rss_bytes=peak_rss,
                        aggregate_cpu_seconds=aggregate_cpu,
                        aggregate_write_bytes=aggregate_write,
                    )
                    raise
                return_code = None
            except BaseException as interrupted:
                preserve_interruption_after_spawn(
                    interrupted,
                    owned_processes=owned,
                    pinned_root_pidfd=root_pidfd,
                    pinned_namespace_tmp=namespace_tmp,
                    peak_process_count=peak_processes,
                    peak_rss_bytes=peak_rss,
                    aggregate_cpu_seconds=aggregate_cpu,
                    aggregate_write_bytes=aggregate_write,
                )
                raise

        # Sampling alone cannot catch a command which creates excessive data
        # and exits between watchdog ticks. The host roots and the namespace
        # tmpfs were opened before exec, so their complete final state remains
        # available after process-tree cleanup and before any descriptor closes.
        try:
            all_final_scans_returned = _scan_all_final_usage(
                root_handles,
                baselines,
                namespace_tmp,
                violation,
            )
        except BaseException as interrupted:
            preserve_interruption_after_spawn(
                interrupted,
                owned_processes=owned,
                pinned_root_pidfd=root_pidfd,
                pinned_namespace_tmp=namespace_tmp,
                peak_process_count=peak_processes,
                peak_rss_bytes=peak_rss,
                aggregate_cpu_seconds=aggregate_cpu,
                aggregate_write_bytes=aggregate_write,
            )
            raise
        final_usage_scan_completed = (
            cleanup_succeeded is True and all_final_scans_returned
        )

        host_interruption: BaseException | None = None
        reader_integrity = True
        readers_terminal, reader_join_error = _join_output_readers(
            readers,
            reader_states,
            monotonic() + policy.caps.termination_grace_seconds,
        )
        if reader_join_error is not None:
            if not isinstance(reader_join_error, Exception):
                host_interruption = reader_join_error
            reader_integrity = False

        capture_values: list[tuple[str, int, bool]] = []
        for capture in (stdout_capture, stderr_capture):
            try:
                capture_values.append(capture.snapshot())
            except BaseException as exc:
                capture_values.append(("", 0, True))
                reader_integrity = False
                if host_interruption is None and not isinstance(exc, Exception):
                    host_interruption = exc
        (stdout, stdout_seen, stdout_truncated) = capture_values[0]
        (stderr, stderr_seen, stderr_truncated) = capture_values[1]

        stream_close_results: list[bool] = []
        for stream in (process.stdout, process.stderr):
            if stream is None:
                continue
            try:
                stream_close_results.append(
                    _close_owned_stream_best_effort(stream)
                )
            except BaseException as exc:  # pragma: no cover - helper is total
                stream_close_results.append(False)
                if host_interruption is None and not isinstance(exc, Exception):
                    host_interruption = exc
        second_terminal, second_join_error = _join_output_readers(
            readers,
            reader_states,
            monotonic() + policy.caps.termination_grace_seconds,
        )
        if second_join_error is not None:
            if host_interruption is None and not isinstance(
                second_join_error, Exception
            ):
                host_interruption = second_join_error
            reader_integrity = False
        readers_terminal = readers_terminal or second_terminal
        streams_closed = all(stream_close_results)
        reader_integrity = reader_integrity and readers_terminal and streams_closed
        if not reader_integrity:
            violation.set("process-output-capture-failed")
            cleanup_succeeded = False
            final_usage_scan_completed = False

        descriptor_cleanup_completed = _close_owned_descriptors_strict((
            root_pidfd,
            *(item.file_descriptor for item in root_handles),
            *(
                ()
                if namespace_tmp is None
                else (namespace_tmp.file_descriptor,)
            ),
        ))
        if not descriptor_cleanup_completed:
            violation.set("resource-descriptor-cleanup-failed")
            cleanup_succeeded = False
            final_usage_scan_completed = False

        if host_interruption is not None:
            interrupted = host_interruption
            preserve_interruption_after_spawn(
                interrupted,
                owned_processes=owned,
                pinned_root_pidfd=root_pidfd,
                pinned_namespace_tmp=namespace_tmp,
                peak_process_count=peak_processes,
                peak_rss_bytes=peak_rss,
                aggregate_cpu_seconds=aggregate_cpu,
                aggregate_write_bytes=aggregate_write,
            )
            raise interrupted
        reason = violation.reason
        if reason is not None:
            if stderr and not stderr.endswith("\n"):
                stderr += "\n"
            stderr += f"{_FIXED_FAILURE_PREFIX}{reason}."
        if timed_out:
            status_value = ExecutionStatus.TIMED_OUT
        elif reason is not None:
            status_value = ExecutionStatus.FAILED
        else:
            assert return_code is not None
            status_value = (
                ExecutionStatus.COMPLETED if return_code == 0 else ExecutionStatus.FAILED
            )
        observation_reason = reason
        if observation_reason is None and timed_out:
            observation_reason = "wall-timeout"
        elif observation_reason is None and return_code not in (None, 0):
            observation_reason = "process-exit-nonzero"
        self._set_observation(
            policy,
            outcome_status=status_value,
            reason=observation_reason,
            cleanup_succeeded=cleanup_succeeded,
            final_usage_scan_completed=final_usage_scan_completed,
            namespace_tmp_pinned_before_exec=(namespace_tmp is not None),
            peak_processes=peak_processes,
            peak_aggregate_rss_bytes=peak_rss,
            observed_aggregate_cpu_seconds=aggregate_cpu,
            observed_aggregate_write_bytes=aggregate_write,
            stdout_bytes_seen=stdout_seen,
            stderr_bytes_seen=stderr_seen,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
        )
        terminal_finalized = True
        return ProcessResult(
            original,
            status_value,
            stdout,
            stderr,
            return_code,
            (monotonic() - started) * 1000,
        )

    @staticmethod
    def _kill_owned(
        process: subprocess.Popen[bytes],
        owned: set[_ProcessIdentity],
        grace_seconds: float,
        *,
        root_pidfd: int | None,
    ) -> bool:
        deadline = monotonic() + grace_seconds
        cleaned = False
        while True:
            if root_pidfd is not None:
                try:
                    signal.pidfd_send_signal(root_pidfd, signal.SIGKILL, None, 0)
                except (ProcessLookupError, PermissionError):
                    pass
            # Holding root_pidfd prevents reuse of the numeric PID/PGID while
            # this group signal is issued. Since the root created a new
            # session, an unrelated session cannot join this process group.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            table = _scan_process_table()
            live = _owned_processes(
                _ProcessIdentity(process.pid, -1),
                owned,
                table,
            )
            live = {
                identity
                for identity in live
                if table.get(identity.pid) is not None
                and table[identity.pid].state != "Z"
            }
            for identity in live:
                current = table.get(identity.pid)
                if current is None or current.identity != identity:
                    continue
                pidfd: int | None = None
                try:
                    pidfd = os.pidfd_open(identity.pid, 0)
                    # Close the stat->pidfd race: the descriptor is used only
                    # after a second identity check while it pins the target.
                    if _read_proc_stat(identity.pid).identity != identity:
                        continue
                    signal.pidfd_send_signal(pidfd, signal.SIGKILL, None, 0)
                except (OSError, ProcessLookupError, PermissionError, ValueError):
                    pass
                finally:
                    if pidfd is not None:
                        _close_after_fork(pidfd)
            if process.poll() is not None and not live:
                cleaned = True
                break
            if monotonic() >= deadline:
                break
            threading.Event().wait(0.02)
        try:
            process.wait(timeout=max(0.01, grace_seconds))
        except (subprocess.TimeoutExpired, ChildProcessError):
            if root_pidfd is not None:
                try:
                    signal.pidfd_send_signal(root_pidfd, signal.SIGKILL, None, 0)
                except (ProcessLookupError, PermissionError):
                    pass
            try:
                process.wait(timeout=max(0.01, grace_seconds))
            except (subprocess.TimeoutExpired, ChildProcessError):
                pass
        return cleaned and process.poll() is not None
