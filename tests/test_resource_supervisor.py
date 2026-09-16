import hashlib
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.core.domain import ExecutionStatus
from adaptive_orchestrator.execution.resource_supervisor import (
    RESOURCE_SUPERVISOR_SCHEMA,
    ResourceCapabilityError,
    ResourceCaps,
    ResourceInvocationPolicy,
    SupervisedProcessRunner,
    WatchedRoot,
    WatchedRootPolicy,
    probe_resource_capabilities,
    resource_policy_descriptor,
)
from adaptive_orchestrator.execution import resource_supervisor


def _caps(**overrides) -> ResourceCaps:
    values = {
        "rlimit_nproc": 256,
        "rlimit_address_space_bytes": 512 * 1024 * 1024,
        "rlimit_file_size_bytes": 8 * 1024 * 1024,
        "rlimit_open_files": 128,
        "rlimit_core_bytes": 0,
        "rlimit_cpu_seconds": 30,
        "rlimit_message_queue_bytes": 0,
        "rlimit_realtime_priority": 0,
        "rlimit_memlock_bytes": 0,
        "max_processes": 32,
        "max_aggregate_rss_bytes": 256 * 1024 * 1024,
        "max_aggregate_cpu_seconds": 20.0,
        "max_aggregate_write_bytes": 32 * 1024 * 1024,
        "max_stdout_bytes": 1024 * 1024,
        "max_stderr_bytes": 1024 * 1024,
        "nice_increment": 10,
        "poll_interval_seconds": 0.02,
        "disk_poll_interval_seconds": 0.03,
        "termination_grace_seconds": 1.0,
        "namespace_tmp_discovery_grace_seconds": 1.0,
    }
    values.update(overrides)
    return ResourceCaps(**values)


def _root_policy(
    *,
    allocated_bytes: int = 16 * 1024 * 1024,
    files: int = 1_000,
) -> WatchedRootPolicy:
    return WatchedRootPolicy(
        label="workspace",
        max_allocated_byte_growth=allocated_bytes,
        max_file_count_growth=files,
    )


def _runner(
    workspace: Path,
    *,
    caps: ResourceCaps | None = None,
    root_policy: WatchedRootPolicy | None = None,
    namespace_tmp_policy: WatchedRootPolicy | None = None,
    require_bubblewrap_pid_namespace: bool = False,
) -> SupervisedProcessRunner:
    selected_root = root_policy or _root_policy()
    policy = ResourceInvocationPolicy(
        name="test",
        caps=caps or _caps(),
        watched_root_policies=(selected_root,),
        namespace_tmp_policy=namespace_tmp_policy,
        require_bubblewrap_pid_namespace=require_bubblewrap_pid_namespace,
    )
    return SupervisedProcessRunner((policy,), {selected_root.label: workspace})


class _CloseFailingStream:
    def __init__(self, stream, *, failures: int) -> None:
        self._stream = stream
        self._remaining_failures = failures
        self.close_calls = 0

    def read(self, size: int = -1):
        return self._stream.read(size)

    def close(self) -> None:
        self.close_calls += 1
        if self._remaining_failures:
            self._remaining_failures -= 1
            raise KeyboardInterrupt()
        self._stream.close()

    @property
    def closed(self) -> bool:
        return self._stream.closed

    def fileno(self) -> int:
        return self._stream.fileno()


class _ReadFailingStream:
    def __init__(self, stream) -> None:
        self._stream = stream
        self._failed = False

    def read(self, size: int = -1):
        if not self._failed:
            self._failed = True
            raise RuntimeError("synthetic output read failure")
        return self._stream.read(size)

    def close(self) -> None:
        self._stream.close()

    @property
    def closed(self) -> bool:
        return self._stream.closed

    def fileno(self) -> int:
        return self._stream.fileno()


class ResourceSupervisorTests(unittest.TestCase):
    def _assert_observation(
        self,
        runner: SupervisedProcessRunner,
        *,
        outcome_status: ExecutionStatus,
        reason: str | None,
        cleanup_succeeded: bool | None,
        final_usage_scan_completed: bool,
    ) -> None:
        observation = runner.last_observation
        self.assertIsNotNone(observation)
        assert observation is not None
        policy = runner._policies[0]
        expected_policy_sha256 = hashlib.sha256(
            json.dumps(
                policy.as_dict(),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(observation.outcome_status, outcome_status.value)
        self.assertEqual(observation.reason, reason)
        self.assertEqual(observation.cleanup_succeeded, cleanup_succeeded)
        self.assertEqual(
            observation.final_usage_scan_completed,
            final_usage_scan_completed,
        )
        self.assertEqual(
            observation.invocation_policy_sha256,
            expected_policy_sha256,
        )
        rendered = observation.as_dict()
        self.assertEqual(
            rendered["cleanup_status"],
            (
                "not-required-or-unobserved"
                if cleanup_succeeded is None
                else "succeeded" if cleanup_succeeded else "failed"
            ),
        )
        self.assertEqual(
            rendered["final_usage_scan_status"],
            "completed" if final_usage_scan_completed else "not-completed",
        )

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs supervisor")
    def test_capability_probe_and_descriptor_are_explicit_about_fallback_limits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = WatchedRoot(Path(directory), _root_policy())
            caps = _caps()
            attestation = probe_resource_capabilities(caps, (root,))
            policy = ResourceInvocationPolicy(
                name="agent",
                caps=caps,
                watched_root_policies=(root.policy,),
                namespace_tmp_policy=None,
            )
            descriptor = resource_policy_descriptor((policy,), attestation)

        self.assertEqual(attestation.schema_version, RESOURCE_SUPERVISOR_SCHEMA)
        self.assertEqual(
            attestation.enforcement_backend,
            "inherited-rlimits-plus-host-procfs-watchdog",
        )
        self.assertFalse(attestation.cgroup_enforced)
        self.assertFalse(attestation.hard_aggregate_kernel_enforcement)
        self.assertIn("RLIMIT_NPROC", attestation.inherited_rlimits)
        self.assertEqual(attestation.child_environment, "empty")
        self.assertEqual(attestation.child_stdin, "devnull")
        self.assertIn(
            "root/tmp-directory-fd",
            attestation.procfs_observations,
        )
        self.assertEqual(
            attestation.namespace_tmp_accounting,
            "bubblewrap-pre-exec-block-fd-barrier-plus-pinned-directory-fd",
        )
        self.assertEqual(
            attestation.final_usage_scan,
            "required-after-process-tree-cleanup-before-result",
        )
        self.assertEqual(len(descriptor["policy_sha256"]), 64)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs supervisor")
    def test_capability_probe_fails_if_child_root_tmp_cannot_be_pinned(self) -> None:
        real_open = os.open

        def reject_child_tmp(path, flags, *args, **kwargs):
            if str(path).endswith("/root/tmp"):
                raise PermissionError("synthetic procfs root/tmp denial")
            return real_open(path, flags, *args, **kwargs)

        with tempfile.TemporaryDirectory() as directory, patch.object(
            resource_supervisor.os,
            "open",
            side_effect=reject_child_tmp,
        ):
            with self.assertRaisesRegex(
                ResourceCapabilityError,
                "required child procfs observations are unavailable",
            ):
                probe_resource_capabilities(
                    _caps(),
                    (WatchedRoot(Path(directory), _root_policy()),),
                )

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs supervisor")
    def test_procfs_probe_post_fork_cleanup_preserves_error_and_reaps_child(
        self,
    ) -> None:
        parent_pid = os.getpid()
        real_pipe = os.pipe
        real_fork = os.fork
        real_close = os.close

        for scenario in (
            "parent-write-interrupt",
            "cleanup-read-error",
            "child-read-interrupt",
        ):
            with self.subTest(scenario=scenario):
                pipe_descriptors: tuple[int, int] | None = None
                child_pid: int | None = None
                injected = False

                def remember_pipe() -> tuple[int, int]:
                    nonlocal pipe_descriptors
                    pipe_descriptors = real_pipe()
                    return pipe_descriptors

                def remember_fork() -> int:
                    nonlocal child_pid
                    result = real_fork()
                    if result > 0:
                        child_pid = result
                    return result

                def inject_parent_close(descriptor: int) -> None:
                    nonlocal injected
                    assert pipe_descriptors is not None
                    target = (
                        pipe_descriptors[1]
                        if scenario == "parent-write-interrupt"
                        else pipe_descriptors[0]
                    )
                    selected_process = (
                        os.getpid() != parent_pid
                        if scenario == "child-read-interrupt"
                        else os.getpid() == parent_pid
                    )
                    if (
                        selected_process
                        and descriptor == target
                        and not injected
                    ):
                        injected = True
                        if scenario in {
                            "parent-write-interrupt",
                            "child-read-interrupt",
                        }:
                            raise KeyboardInterrupt()
                        raise RuntimeError("synthetic cleanup close failure")
                    real_close(descriptor)

                descriptors_before = len(
                    tuple(Path("/proc/self/fd").iterdir())
                )
                expected = (
                    KeyboardInterrupt
                    if scenario == "parent-write-interrupt"
                    else ResourceCapabilityError
                )
                with (
                    patch.object(os, "pipe", side_effect=remember_pipe),
                    patch.object(os, "fork", side_effect=remember_fork),
                    patch.object(os, "close", side_effect=inject_parent_close),
                    self.assertRaises(expected),
                ):
                    resource_supervisor._probe_child_procfs()
                descriptors_after = len(
                    tuple(Path("/proc/self/fd").iterdir())
                )

                if scenario != "child-read-interrupt":
                    self.assertTrue(injected)
                self.assertEqual(descriptors_after, descriptors_before)
                assert child_pid is not None
                self.assertFalse(Path(f"/proc/{child_pid}").exists())
                with self.assertRaises(ChildProcessError):
                    os.waitpid(child_pid, os.WNOHANG)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs supervisor")
    def test_rlimit_probe_wait_interruption_reaps_real_child(self) -> None:
        parent_pid = os.getpid()
        real_fork = os.fork
        real_waitpid = os.waitpid
        child_pid: int | None = None
        injected = False

        def remember_fork() -> int:
            nonlocal child_pid
            result = real_fork()
            if result > 0:
                child_pid = result
            return result

        def interrupt_first_target_wait(pid: int, options: int):
            nonlocal injected
            if (
                os.getpid() == parent_pid
                and child_pid is not None
                and pid == child_pid
                and not injected
            ):
                injected = True
                raise KeyboardInterrupt()
            return real_waitpid(pid, options)

        with (
            patch.object(os, "fork", side_effect=remember_fork),
            patch.object(os, "waitpid", side_effect=interrupt_first_target_wait),
            self.assertRaises(KeyboardInterrupt),
        ):
            resource_supervisor._probe_rlimits(_caps())

        self.assertTrue(injected)
        assert child_pid is not None
        self.assertFalse(Path(f"/proc/{child_pid}").exists())
        with self.assertRaises(ChildProcessError):
            os.waitpid(child_pid, os.WNOHANG)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs supervisor")
    def test_real_uid_nproc_inventory_counts_threads_and_reserves_full_subtree(self) -> None:
        release = threading.Event()
        ready = threading.Barrier(9)

        def hold_thread() -> None:
            ready.wait()
            release.wait(5)

        baseline = resource_supervisor._real_uid_task_count()
        threads = tuple(threading.Thread(target=hold_thread) for _ in range(8))
        try:
            for thread in threads:
                thread.start()
            ready.wait()
            observed = resource_supervisor._real_uid_task_count()
            self.assertGreaterEqual(observed, baseline + len(threads))
        finally:
            release.set()
            for thread in threads:
                thread.join(5)
        self.assertTrue(all(not thread.is_alive() for thread in threads))

        caps = _caps(rlimit_nproc=256, max_processes=32)
        minimum_required = (
            caps.rlimit_nproc
            - caps.max_processes
            - resource_supervisor._RLIMIT_NPROC_HOST_RACE_RESERVE
            + 1
        )
        with (
            patch.object(
                resource_supervisor,
                "_real_uid_task_count",
                return_value=minimum_required,
            ),
            self.assertRaisesRegex(
                ResourceCapabilityError,
                "real-UID task count",
            ),
        ):
            resource_supervisor._probe_rlimits(caps)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs supervisor")
    def test_capability_probe_rejects_a_symlinked_watched_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            actual = base / "actual"
            actual.mkdir()
            alias = base / "alias"
            alias.symlink_to(actual, target_is_directory=True)
            with self.assertRaisesRegex(ResourceCapabilityError, "symlink"):
                probe_resource_capabilities(
                    _caps(),
                    (WatchedRoot(alias, _root_policy()),),
                )

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs supervisor")
    def test_partial_watched_root_open_failure_closes_earlier_descriptors(self) -> None:
        second_policy = WatchedRootPolicy(
            label="agent-home",
            max_allocated_byte_growth=1024 * 1024,
            max_file_count_growth=100,
        )
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            workspace = base / "workspace"
            agent_home = base / "agent-home"
            workspace.mkdir()
            agent_home.mkdir()
            policy = ResourceInvocationPolicy(
                name="test",
                caps=_caps(),
                watched_root_policies=(_root_policy(), second_policy),
                namespace_tmp_policy=None,
                require_bubblewrap_pid_namespace=False,
            )
            runner = SupervisedProcessRunner(
                (policy,),
                {"workspace": workspace, "agent-home": agent_home},
            )
            real_open = resource_supervisor._open_watched_root
            real_close = os.close
            opened_descriptors: list[int] = []
            close_error_injected = False

            def fail_second_open(root: WatchedRoot):
                if root.policy.label == "agent-home":
                    raise ResourceCapabilityError("synthetic second-root failure")
                handle = real_open(root)
                opened_descriptors.append(handle.file_descriptor)
                return handle

            def close_then_raise(descriptor: int) -> None:
                nonlocal close_error_injected
                if (
                    opened_descriptors
                    and descriptor == opened_descriptors[0]
                    and not close_error_injected
                ):
                    close_error_injected = True
                    raise RuntimeError("synthetic watched-root close failure")
                real_close(descriptor)

            with (
                patch.object(
                    resource_supervisor,
                    "_open_watched_root",
                    side_effect=fail_second_open,
                ),
                patch.object(os, "close", side_effect=close_then_raise),
            ):
                result = runner.run((sys.executable, "-c", "pass"), workspace, 5)

            self.assertEqual(len(opened_descriptors), 1)
            self.assertTrue(close_error_injected)
            with self.assertRaises(OSError):
                os.fstat(opened_descriptors[0])

        self.assertEqual(result.status, ExecutionStatus.SPAWN_ERROR, result.stderr)
        self._assert_observation(
            runner,
            outcome_status=ExecutionStatus.SPAWN_ERROR,
            reason="resource-capability-probe-failed",
            cleanup_succeeded=None,
            final_usage_scan_completed=False,
        )

    def test_watched_root_validation_two_close_interruptions_keep_identity_and_close(
        self,
    ) -> None:
        real_open = os.open
        real_fstat = os.fstat
        real_close = os.close
        opened_descriptor: int | None = None
        validation_injected = False
        close_interruptions = 0

        def remember_open(*args, **kwargs):
            nonlocal opened_descriptor
            opened_descriptor = real_open(*args, **kwargs)
            return opened_descriptor

        def reject_first_validation(descriptor: int):
            nonlocal validation_injected
            observed = real_fstat(descriptor)
            if descriptor == opened_descriptor and not validation_injected:
                validation_injected = True
                values = list(observed)
                values[4] = os.geteuid() + 1
                return os.stat_result(values)
            return observed

        def interrupt_two_closes(descriptor: int) -> None:
            nonlocal close_interruptions
            if descriptor == opened_descriptor and close_interruptions < 2:
                close_interruptions += 1
                raise KeyboardInterrupt()
            real_close(descriptor)

        with tempfile.TemporaryDirectory() as directory:
            root = WatchedRoot(Path(directory), _root_policy())
            descriptors_before = len(tuple(Path("/proc/self/fd").iterdir()))
            with (
                patch.object(os, "open", side_effect=remember_open),
                patch.object(os, "fstat", side_effect=reject_first_validation),
                patch.object(os, "close", side_effect=interrupt_two_closes),
                self.assertRaisesRegex(
                    ResourceCapabilityError,
                    "descriptor is not an owned directory",
                ),
            ):
                resource_supervisor._open_watched_root(root)
            descriptors_after = len(tuple(Path("/proc/self/fd").iterdir()))

        self.assertTrue(validation_injected)
        self.assertEqual(close_interruptions, 2)
        self.assertEqual(descriptors_after, descriptors_before)
        assert opened_descriptor is not None
        with self.assertRaises(OSError):
            real_fstat(opened_descriptor)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs supervisor")
    def test_spawn_error_root_close_failure_preserves_terminal_observation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            runner = _runner(workspace)
            real_open = resource_supervisor._open_watched_root
            real_close = os.close
            opened_descriptor: int | None = None
            close_error_injected = False

            def remember_open(root: WatchedRoot):
                nonlocal opened_descriptor
                handle = real_open(root)
                opened_descriptor = handle.file_descriptor
                return handle

            def close_then_raise(descriptor: int) -> None:
                nonlocal close_error_injected
                if descriptor == opened_descriptor and not close_error_injected:
                    close_error_injected = True
                    raise RuntimeError("synthetic watched-root close failure")
                real_close(descriptor)

            with (
                patch.object(
                    resource_supervisor,
                    "_open_watched_root",
                    side_effect=remember_open,
                ),
                patch.object(
                    subprocess,
                    "Popen",
                    side_effect=OSError("synthetic spawn failure"),
                ),
                patch.object(os, "close", side_effect=close_then_raise),
            ):
                result = runner.run(
                    (sys.executable, "-c", "pass"), workspace, 5
                )

            self.assertTrue(close_error_injected)
            assert opened_descriptor is not None
            with self.assertRaises(OSError):
                os.fstat(opened_descriptor)

        self.assertEqual(result.status, ExecutionStatus.SPAWN_ERROR, result.stderr)
        self._assert_observation(
            runner,
            outcome_status=ExecutionStatus.SPAWN_ERROR,
            reason="resource-contained-spawn-failed",
            cleanup_succeeded=None,
            final_usage_scan_completed=False,
        )

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs supervisor")
    def test_spawn_error_reports_unclosable_owned_descriptor_cleanup_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            runner = _runner(workspace)
            real_open = resource_supervisor._open_watched_root
            real_close = os.close
            opened_descriptor: int | None = None

            def remember_open(root: WatchedRoot):
                nonlocal opened_descriptor
                handle = real_open(root)
                opened_descriptor = handle.file_descriptor
                return handle

            def reject_target_close(descriptor: int) -> None:
                if descriptor == opened_descriptor:
                    raise KeyboardInterrupt()
                real_close(descriptor)

            with (
                patch.object(
                    resource_supervisor,
                    "_open_watched_root",
                    side_effect=remember_open,
                ),
                patch.object(
                    subprocess,
                    "Popen",
                    side_effect=OSError("synthetic spawn failure"),
                ),
                patch.object(os, "close", side_effect=reject_target_close),
            ):
                result = runner.run(
                    (sys.executable, "-c", "pass"), workspace, 5
                )

            assert opened_descriptor is not None
            os.fstat(opened_descriptor)
            self.assertIn(
                opened_descriptor,
                resource_supervisor._QUARANTINED_OWNED_DESCRIPTORS,
            )
            real_close(opened_descriptor)
            resource_supervisor._QUARANTINED_OWNED_DESCRIPTORS.pop(
                opened_descriptor,
                None,
            )

        self.assertEqual(result.status, ExecutionStatus.SPAWN_ERROR, result.stderr)
        self._assert_observation(
            runner,
            outcome_status=ExecutionStatus.SPAWN_ERROR,
            reason="resource-contained-spawn-failed",
            cleanup_succeeded=False,
            final_usage_scan_completed=False,
        )

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs supervisor")
    def test_exact_policy_rejects_a_command_without_private_pid_namespace_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            runner = _runner(
                workspace,
                require_bubblewrap_pid_namespace=True,
            )
            result = runner.run((sys.executable, "-c", "pass"), workspace, 5)

        self.assertEqual(result.status, ExecutionStatus.SPAWN_ERROR)
        self.assertIn("not the pinned bubblewrap launcher", result.stderr)
        self._assert_observation(
            runner,
            outcome_status=ExecutionStatus.SPAWN_ERROR,
            reason="resource-capability-probe-failed",
            cleanup_succeeded=None,
            final_usage_scan_completed=False,
        )

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs supervisor")
    def test_preflight_spawn_and_reader_interruptions_leave_terminal_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            runner = _runner(workspace)
            with patch.object(
                resource_supervisor,
                "_scan_usage",
                side_effect=KeyboardInterrupt(),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    runner.run((sys.executable, "-c", "pass"), workspace, 1)
            self._assert_observation(
                runner,
                outcome_status=ExecutionStatus.FAILED,
                reason="supervisor-interrupted:KeyboardInterrupt",
                cleanup_succeeded=None,
                final_usage_scan_completed=False,
            )

        namespace_policy = WatchedRootPolicy(
            label="namespace-tmp",
            max_allocated_byte_growth=1024 * 1024,
            max_file_count_growth=100,
            subtract_baseline=False,
        )
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            runner = _runner(workspace, namespace_tmp_policy=namespace_policy)
            command = (
                "/usr/bin/bwrap",
                "--tmpfs",
                "/tmp",
                "--",
                "/bin/true",
            )
            descriptors_before = len(tuple(Path("/proc/self/fd").iterdir()))
            with patch.object(
                subprocess,
                "Popen",
                side_effect=KeyboardInterrupt(),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    runner.run(command, workspace, 1)
            descriptors_after = len(tuple(Path("/proc/self/fd").iterdir()))
            self.assertEqual(descriptors_after, descriptors_before)
            self._assert_observation(
                runner,
                outcome_status=ExecutionStatus.FAILED,
                reason="supervisor-interrupted:KeyboardInterrupt",
                cleanup_succeeded=None,
                final_usage_scan_completed=False,
            )

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            runner = _runner(workspace)
            with patch.object(
                threading.Thread,
                "start",
                side_effect=KeyboardInterrupt(),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    runner.run(
                        (sys.executable, "-c", "import time; time.sleep(30)"),
                        workspace,
                        5,
                    )
            self._assert_observation(
                runner,
                outcome_status=ExecutionStatus.FAILED,
                reason="supervisor-interrupted:KeyboardInterrupt",
                cleanup_succeeded=False,
                final_usage_scan_completed=False,
            )

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux/bubblewrap supervisor")
    def test_pin_and_post_release_interruptions_kill_before_reraise(self) -> None:
        bubblewrap = Path("/usr/bin/bwrap")
        if not bubblewrap.is_file():
            self.skipTest("bubblewrap is unavailable")
        namespace_policy = WatchedRootPolicy(
            label="namespace-tmp",
            max_allocated_byte_growth=1024 * 1024,
            max_file_count_growth=100,
            subtract_baseline=False,
        )
        for phase in ("pin", "post-release"):
            with self.subTest(phase=phase):
                with tempfile.TemporaryDirectory() as directory:
                    workspace = Path(directory)
                    marker = workspace / "payload-ran"
                    command = (
                        str(bubblewrap),
                        "--die-with-parent",
                        "--new-session",
                        "--unshare-all",
                        "--clearenv",
                        "--ro-bind",
                        "/",
                        "/",
                        "--bind",
                        str(workspace),
                        str(workspace),
                        "--tmpfs",
                        "/tmp",
                        "--proc",
                        "/proc",
                        "--remount-ro",
                        "/",
                        "--remount-ro",
                        "/dev",
                        "--",
                        sys.executable,
                        "-c",
                        (
                            "import time; from pathlib import Path; "
                            "time.sleep(0.2); "
                            f"Path({str(marker)!r}).touch()"
                        ),
                    )
                    runner = _runner(
                        workspace,
                        namespace_tmp_policy=namespace_policy,
                        require_bubblewrap_pid_namespace=True,
                    )
                    if phase == "pin":
                        interruption = patch.object(
                            resource_supervisor,
                            "_pin_namespace_tmp_before_exec",
                            side_effect=KeyboardInterrupt(),
                        )
                    else:
                        interruption = patch.object(
                            resource_supervisor.os,
                            "sysconf",
                            side_effect=KeyboardInterrupt(),
                        )
                    with interruption:
                        with self.assertRaises(KeyboardInterrupt):
                            runner.run(command, workspace, 5)

                    self.assertFalse(marker.exists())
                    self._assert_observation(
                        runner,
                        outcome_status=ExecutionStatus.FAILED,
                        reason="supervisor-interrupted:KeyboardInterrupt",
                        cleanup_succeeded=True,
                        final_usage_scan_completed=True,
                    )

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux/bubblewrap supervisor")
    def test_barrier_writer_close_interruption_kills_before_retry_close(self) -> None:
        bubblewrap = Path("/usr/bin/bwrap")
        if not bubblewrap.is_file():
            self.skipTest("bubblewrap is unavailable")
        namespace_policy = WatchedRootPolicy(
            label="namespace-tmp",
            max_allocated_byte_growth=1024 * 1024,
            max_file_count_growth=100,
            subtract_baseline=False,
        )
        real_pin = resource_supervisor._pin_namespace_tmp_before_exec
        real_close = os.close
        pin_completed = False
        close_interrupted = False

        def remember_pin(*args, **kwargs):
            nonlocal pin_completed
            result = real_pin(*args, **kwargs)
            pin_completed = True
            return result

        def interrupt_first_close_after_pin(descriptor: int) -> None:
            nonlocal close_interrupted
            if pin_completed and not close_interrupted:
                close_interrupted = True
                raise KeyboardInterrupt()
            real_close(descriptor)

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            marker = workspace / "payload-ran"
            runner = _runner(
                workspace,
                namespace_tmp_policy=namespace_policy,
                require_bubblewrap_pid_namespace=True,
            )
            command = (
                str(bubblewrap),
                "--die-with-parent",
                "--new-session",
                "--unshare-all",
                "--clearenv",
                "--ro-bind",
                "/",
                "/",
                "--bind",
                str(workspace),
                str(workspace),
                "--tmpfs",
                "/tmp",
                "--proc",
                "/proc",
                "--remount-ro",
                "/",
                "--remount-ro",
                "/dev",
                "--",
                sys.executable,
                "-c",
                f"from pathlib import Path; Path({str(marker)!r}).touch()",
            )
            with (
                patch.object(
                    resource_supervisor,
                    "_pin_namespace_tmp_before_exec",
                    side_effect=remember_pin,
                ),
                patch.object(os, "close", side_effect=interrupt_first_close_after_pin),
                self.assertRaises(KeyboardInterrupt),
            ):
                runner.run(command, workspace, 5)

            self.assertTrue(close_interrupted)
            self.assertFalse(marker.exists())
            self._assert_observation(
                runner,
                outcome_status=ExecutionStatus.FAILED,
                reason="supervisor-interrupted:KeyboardInterrupt",
                cleanup_succeeded=True,
                final_usage_scan_completed=True,
            )

    def test_namespace_tmp_pin_local_descriptor_closes_on_interruption(
        self,
    ) -> None:
        namespace_policy = WatchedRootPolicy(
            label="namespace-tmp",
            max_allocated_byte_growth=1024 * 1024,
            max_file_count_growth=100,
            subtract_baseline=False,
        )
        identity = resource_supervisor._ProcessIdentity(424242, 17)
        sample = resource_supervisor._ProcStat(
            identity=identity,
            state="S",
            parent_pid=os.getpid(),
            process_group=424242,
            session=424242,
            cpu_ticks=0,
        )
        process = mock_process = unittest.mock.Mock()
        mock_process.poll.return_value = None
        real_fstat = os.fstat

        with tempfile.TemporaryDirectory() as directory:
            descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            opened = real_fstat(descriptor)
            candidate_stat = os.stat_result(
                (
                    stat.S_IFDIR | 0o700,
                    opened.st_ino,
                    opened.st_dev,
                    1,
                    os.geteuid(),
                    os.getegid(),
                    0,
                    0,
                    0,
                    0,
                )
            )
            interrupted = False

            def interrupt_descriptor_fstat(target: int):
                nonlocal interrupted
                if target == descriptor and not interrupted:
                    interrupted = True
                    raise KeyboardInterrupt()
                return real_fstat(target)

            with (
                patch.object(
                    resource_supervisor,
                    "_host_tmp_identity",
                    return_value=(opened.st_dev + 1, opened.st_ino + 1),
                ),
                patch.object(
                    resource_supervisor,
                    "_scan_process_table",
                    return_value={identity.pid: sample},
                ),
                patch.object(
                    resource_supervisor,
                    "_owned_processes",
                    return_value={identity},
                ),
                patch.object(Path, "stat", return_value=candidate_stat),
                patch.object(os, "open", return_value=descriptor),
                patch.object(os, "fstat", side_effect=interrupt_descriptor_fstat),
                self.assertRaises(KeyboardInterrupt),
            ):
                resource_supervisor._pin_namespace_tmp_before_exec(
                    identity,
                    namespace_policy,
                    process,
                    1,
                )

            self.assertTrue(interrupted)
            with self.assertRaises(OSError):
                real_fstat(descriptor)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux/bubblewrap supervisor")
    def test_post_spawn_barrier_close_interruption_uses_outer_finalizer(self) -> None:
        bubblewrap = Path("/usr/bin/bwrap")
        if not bubblewrap.is_file():
            self.skipTest("bubblewrap is unavailable")
        namespace_policy = WatchedRootPolicy(
            label="namespace-tmp",
            max_allocated_byte_growth=1024 * 1024,
            max_file_count_growth=100,
            subtract_baseline=False,
        )
        real_close = os.close
        real_popen = subprocess.Popen
        real_with_barrier = resource_supervisor._with_pre_exec_block_fd
        barrier_read_fd: int | None = None
        popen_returned = False
        interrupted = False

        def remember_barrier_descriptor(command, descriptor):
            nonlocal barrier_read_fd
            barrier_read_fd = descriptor
            return real_with_barrier(command, descriptor)

        def interrupt_first_parent_barrier_close(descriptor: int) -> None:
            nonlocal interrupted
            if popen_returned and descriptor == barrier_read_fd and not interrupted:
                interrupted = True
                raise KeyboardInterrupt()
            real_close(descriptor)

        def remember_popen_return(*args, **kwargs):
            nonlocal popen_returned
            process = real_popen(*args, **kwargs)
            popen_returned = True
            return process

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            marker = workspace / "payload-ran"
            runner = _runner(
                workspace,
                namespace_tmp_policy=namespace_policy,
                require_bubblewrap_pid_namespace=True,
            )
            command = (
                str(bubblewrap),
                "--die-with-parent",
                "--new-session",
                "--unshare-all",
                "--clearenv",
                "--ro-bind",
                "/",
                "/",
                "--bind",
                str(workspace),
                str(workspace),
                "--tmpfs",
                "/tmp",
                "--proc",
                "/proc",
                "--remount-ro",
                "/",
                "--remount-ro",
                "/dev",
                "--",
                sys.executable,
                "-c",
                f"from pathlib import Path; Path({str(marker)!r}).touch()",
            )
            descriptors_before = len(tuple(Path("/proc/self/fd").iterdir()))
            with (
                patch.object(
                    resource_supervisor,
                    "_with_pre_exec_block_fd",
                    side_effect=remember_barrier_descriptor,
                ),
                patch.object(
                    os,
                    "close",
                    side_effect=interrupt_first_parent_barrier_close,
                ),
                patch.object(subprocess, "Popen", side_effect=remember_popen_return),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    runner.run(command, workspace, 5)
            descriptors_after = len(tuple(Path("/proc/self/fd").iterdir()))

            self.assertTrue(interrupted)
            self.assertFalse(marker.exists())
            self.assertEqual(descriptors_after, descriptors_before)
            self._assert_observation(
                runner,
                outcome_status=ExecutionStatus.FAILED,
                reason="supervisor-interrupted:KeyboardInterrupt",
                cleanup_succeeded=True,
                final_usage_scan_completed=True,
            )

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs supervisor")
    def test_outer_finalizer_retries_stream_close_without_masking_original(
        self,
    ) -> None:
        real_popen = subprocess.Popen
        wrapped: _CloseFailingStream | None = None

        def wrap_stdout(*args, **kwargs):
            nonlocal wrapped
            process = real_popen(*args, **kwargs)
            assert process.stdout is not None
            wrapped = _CloseFailingStream(process.stdout, failures=1)
            process.stdout = wrapped
            return process

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            runner = _runner(workspace)
            descriptors_before = len(tuple(Path("/proc/self/fd").iterdir()))
            with (
                patch.object(subprocess, "Popen", side_effect=wrap_stdout),
                patch.object(
                    resource_supervisor,
                    "_OutputCapture",
                    side_effect=SystemExit(29),
                ),
                self.assertRaisesRegex(SystemExit, "29"),
            ):
                runner.run(
                    (sys.executable, "-c", "import time; time.sleep(30)"),
                    workspace,
                    5,
                )
            descriptors_after = len(tuple(Path("/proc/self/fd").iterdir()))

            assert wrapped is not None
            self.assertGreaterEqual(wrapped.close_calls, 2)
            self.assertTrue(wrapped.closed)
            self.assertEqual(descriptors_after, descriptors_before)
            self._assert_observation(
                runner,
                outcome_status=ExecutionStatus.FAILED,
                reason="supervisor-interrupted:SystemExit",
                cleanup_succeeded=True,
                final_usage_scan_completed=True,
            )

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs supervisor")
    def test_normal_main_thread_verifies_stream_cleanup(self) -> None:
        real_popen = subprocess.Popen
        for failures in (2, 100):
            with self.subTest(failures=failures):
                wrapped: _CloseFailingStream | None = None

                def wrap_stdout(*args, **kwargs):
                    nonlocal wrapped
                    process = real_popen(*args, **kwargs)
                    assert process.stdout is not None
                    wrapped = _CloseFailingStream(
                        process.stdout, failures=failures
                    )
                    process.stdout = wrapped
                    return process

                with tempfile.TemporaryDirectory() as directory:
                    workspace = Path(directory)
                    runner = _runner(workspace)
                    with patch.object(
                        subprocess, "Popen", side_effect=wrap_stdout
                    ):
                        result = runner.run(
                            (sys.executable, "-c", "pass"), workspace, 5
                        )

                    assert wrapped is not None
                    self.assertEqual(result.status, ExecutionStatus.FAILED)
                    if failures == 2:
                        self.assertGreaterEqual(wrapped.close_calls, 3)
                        self.assertTrue(wrapped.closed)
                    else:
                        self.assertFalse(wrapped.closed)
                        wrapped._remaining_failures = 0
                        wrapped.close()
                    self.assertIn(
                        "process-output-capture-failed", result.stderr
                    )
                    self._assert_observation(
                        runner,
                        outcome_status=ExecutionStatus.FAILED,
                        reason="process-output-capture-failed",
                        cleanup_succeeded=False,
                        final_usage_scan_completed=False,
                    )

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs supervisor")
    def test_reader_stage_failures_are_shared_joined_and_fail_closed(self) -> None:
        real_popen = subprocess.Popen
        real_consume = resource_supervisor._OutputCapture.consume
        real_finish = resource_supervisor._OutputCapture.finish_callback

        for stage in ("read", "consume", "finish", "close"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                runner = _runner(workspace)
                wrapped = None
                injected = False

                def wrap_stdout(*args, **kwargs):
                    nonlocal wrapped
                    process = real_popen(*args, **kwargs)
                    assert process.stdout is not None
                    if stage == "read":
                        wrapped = _ReadFailingStream(process.stdout)
                    elif stage == "close":
                        wrapped = _CloseFailingStream(process.stdout, failures=1)
                    else:
                        wrapped = process.stdout
                    process.stdout = wrapped
                    return process

                def fail_consume_once(capture, chunk):
                    nonlocal injected
                    if stage == "consume" and not injected:
                        injected = True
                        raise RuntimeError("synthetic output consume failure")
                    return real_consume(capture, chunk)

                def fail_finish_once(capture):
                    nonlocal injected
                    if stage == "finish" and not injected:
                        injected = True
                        raise RuntimeError("synthetic output finish failure")
                    return real_finish(capture)

                descriptors_before = len(tuple(Path("/proc/self/fd").iterdir()))
                with (
                    patch.object(subprocess, "Popen", side_effect=wrap_stdout),
                    patch.object(
                        resource_supervisor._OutputCapture,
                        "consume",
                        side_effect=fail_consume_once,
                        autospec=True,
                    ),
                    patch.object(
                        resource_supervisor._OutputCapture,
                        "finish_callback",
                        side_effect=fail_finish_once,
                        autospec=True,
                    ),
                ):
                    result = runner.run(
                        (
                            sys.executable,
                            "-c",
                            "import time; print('output', flush=True); time.sleep(0.1)",
                        ),
                        workspace,
                        5,
                    )
                descriptors_after = len(tuple(Path("/proc/self/fd").iterdir()))

                self.assertEqual(result.status, ExecutionStatus.FAILED)
                self.assertIn("process-output-capture-failed", result.stderr)
                self.assertEqual(descriptors_after, descriptors_before)
                self._assert_observation(
                    runner,
                    outcome_status=ExecutionStatus.FAILED,
                    reason="process-output-capture-failed",
                    cleanup_succeeded=False,
                    final_usage_scan_completed=False,
                )
                if stage in {"consume", "finish"}:
                    self.assertTrue(injected)
                assert wrapped is not None
                self.assertTrue(wrapped.closed)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux/bubblewrap supervisor")
    def test_ancestry_anchor_requires_root_and_dev_as_final_mount_operations(self) -> None:
        bubblewrap = Path("/usr/bin/bwrap")
        if not bubblewrap.is_file():
            self.skipTest("bubblewrap is unavailable")
        valid = (
            str(bubblewrap),
            "--die-with-parent",
            "--new-session",
            "--unshare-all",
            "--tmpfs",
            "/tmp",
            "--remount-ro",
            "/",
            "--remount-ro",
            "/dev",
            "--",
            "/bin/true",
        )
        resource_supervisor._validate_kernel_ancestry_anchor(valid)
        with self.assertRaisesRegex(ResourceCapabilityError, "read-only root/dev"):
            resource_supervisor._validate_kernel_ancestry_anchor(
                tuple(token for index, token in enumerate(valid) if index not in {6, 7})
            )
        late_mount = (*valid[:-2], "--dir", "/late", *valid[-2:])
        with self.assertRaisesRegex(ResourceCapabilityError, "final mount operations"):
            resource_supervisor._validate_kernel_ancestry_anchor(late_mount)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux/bubblewrap supervisor")
    def test_child_identification_failure_kills_before_releasing_pre_exec_barrier(
        self,
    ) -> None:
        bubblewrap = Path("/usr/bin/bwrap")
        if not bubblewrap.is_file():
            self.skipTest("bubblewrap is unavailable")
        namespace_policy = WatchedRootPolicy(
            label="namespace-tmp",
            max_allocated_byte_growth=1024 * 1024,
            max_file_count_growth=100,
            subtract_baseline=False,
        )
        real_pidfd_open = os.pidfd_open
        pidfd_calls = 0

        def fail_target_identification(pid: int, flags: int = 0) -> int:
            nonlocal pidfd_calls
            pidfd_calls += 1
            if pidfd_calls == 2:
                raise OSError("synthetic child-identification failure")
            return real_pidfd_open(pid, flags)

        real_kill_owned = SupervisedProcessRunner._kill_owned

        def delayed_kill(*args, **kwargs) -> bool:
            time.sleep(0.2)
            return real_kill_owned(*args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            marker = workspace / "payload-ran"
            command = (
                str(bubblewrap),
                "--die-with-parent",
                "--new-session",
                "--unshare-all",
                "--clearenv",
                "--ro-bind",
                "/",
                "/",
                "--bind",
                str(workspace),
                str(workspace),
                "--tmpfs",
                "/tmp",
                "--proc",
                "/proc",
                "--remount-ro",
                "/",
                "--remount-ro",
                "/dev",
                "--",
                sys.executable,
                "-c",
                f"from pathlib import Path; Path({str(marker)!r}).touch()",
            )
            runner = _runner(
                workspace,
                namespace_tmp_policy=namespace_policy,
                require_bubblewrap_pid_namespace=True,
            )
            with (
                patch.object(os, "pidfd_open", side_effect=fail_target_identification),
                patch.object(
                    SupervisedProcessRunner,
                    "_kill_owned",
                    side_effect=delayed_kill,
                ),
            ):
                result = runner.run(command, workspace, 5)

            self.assertFalse(marker.exists())

        self.assertEqual(result.status, ExecutionStatus.SPAWN_ERROR, result.stderr)
        self.assertIn("could not identify child", result.stderr)
        self._assert_observation(
            runner,
            outcome_status=ExecutionStatus.SPAWN_ERROR,
            reason="resource-watchdog-child-identification-failed",
            cleanup_succeeded=True,
            final_usage_scan_completed=True,
        )

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux/bubblewrap supervisor")
    def test_tmp_pin_failure_kills_before_releasing_pre_exec_barrier(self) -> None:
        bubblewrap = Path("/usr/bin/bwrap")
        if not bubblewrap.is_file():
            self.skipTest("bubblewrap is unavailable")
        namespace_policy = WatchedRootPolicy(
            label="namespace-tmp",
            max_allocated_byte_growth=1024 * 1024,
            max_file_count_growth=100,
            subtract_baseline=False,
        )
        real_kill_owned = SupervisedProcessRunner._kill_owned

        def delayed_pin_failure(*_args, **_kwargs):
            time.sleep(0.1)
            raise ResourceCapabilityError("synthetic namespace tmp pin failure")

        def delayed_kill(*args, **kwargs) -> bool:
            time.sleep(0.2)
            return real_kill_owned(*args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            marker = workspace / "payload-ran"
            command = (
                str(bubblewrap),
                "--die-with-parent",
                "--new-session",
                "--unshare-all",
                "--clearenv",
                "--ro-bind",
                "/",
                "/",
                "--bind",
                str(workspace),
                str(workspace),
                "--tmpfs",
                "/tmp",
                "--proc",
                "/proc",
                "--remount-ro",
                "/",
                "--remount-ro",
                "/dev",
                "--",
                sys.executable,
                "-c",
                f"from pathlib import Path; Path({str(marker)!r}).touch()",
            )
            runner = _runner(
                workspace,
                namespace_tmp_policy=namespace_policy,
                require_bubblewrap_pid_namespace=True,
            )
            with (
                patch.object(
                    resource_supervisor,
                    "_pin_namespace_tmp_before_exec",
                    side_effect=delayed_pin_failure,
                ),
                patch.object(
                    SupervisedProcessRunner,
                    "_kill_owned",
                    side_effect=delayed_kill,
                ),
            ):
                result = runner.run(command, workspace, 5)

            self.assertFalse(marker.exists())

        self.assertEqual(result.status, ExecutionStatus.SPAWN_ERROR, result.stderr)
        self.assertIn("could not pin namespace tmp", result.stderr)
        self._assert_observation(
            runner,
            outcome_status=ExecutionStatus.SPAWN_ERROR,
            reason="namespace-tmp-pre-exec-pin-failed",
            cleanup_succeeded=True,
            final_usage_scan_completed=True,
        )

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux/bubblewrap supervisor")
    def test_pre_exec_failure_cleanup_errors_never_release_blocked_payload(
        self,
    ) -> None:
        bubblewrap = Path("/usr/bin/bwrap")
        if not bubblewrap.is_file():
            self.skipTest("bubblewrap is unavailable")
        namespace_policy = WatchedRootPolicy(
            label="namespace-tmp",
            max_allocated_byte_growth=1024 * 1024,
            max_file_count_growth=100,
            subtract_baseline=False,
        )
        real_kill_owned = SupervisedProcessRunner._kill_owned
        real_pidfd_open = os.pidfd_open

        for site in ("child-identification", "tmp-pin"):
            for cleanup_mode in ("false", "raise"):
                with self.subTest(site=site, cleanup_mode=cleanup_mode):
                    pidfd_calls = 0

                    def fail_target_identification(
                        pid: int, flags: int = 0
                    ) -> int:
                        nonlocal pidfd_calls
                        pidfd_calls += 1
                        if pidfd_calls == 2:
                            raise OSError("synthetic child-identification failure")
                        return real_pidfd_open(pid, flags)

                    def kill_then_report_failure(*args, **kwargs) -> bool:
                        real_kill_owned(*args, **kwargs)
                        if cleanup_mode == "raise":
                            raise RuntimeError("synthetic cleanup failure")
                        return False

                    if site == "child-identification":
                        injected_failure = patch.object(
                            os,
                            "pidfd_open",
                            side_effect=fail_target_identification,
                        )
                        expected_reason = (
                            "resource-watchdog-child-identification-failed"
                        )
                    else:
                        injected_failure = patch.object(
                            resource_supervisor,
                            "_pin_namespace_tmp_before_exec",
                            side_effect=ResourceCapabilityError(
                                "synthetic namespace tmp pin failure"
                            ),
                        )
                        expected_reason = "namespace-tmp-pre-exec-pin-failed"

                    with tempfile.TemporaryDirectory() as directory:
                        workspace = Path(directory)
                        marker = workspace / "payload-ran"
                        runner = _runner(
                            workspace,
                            namespace_tmp_policy=namespace_policy,
                            require_bubblewrap_pid_namespace=True,
                        )
                        command = (
                            str(bubblewrap),
                            "--die-with-parent",
                            "--new-session",
                            "--unshare-all",
                            "--clearenv",
                            "--ro-bind",
                            "/",
                            "/",
                            "--bind",
                            str(workspace),
                            str(workspace),
                            "--tmpfs",
                            "/tmp",
                            "--proc",
                            "/proc",
                            "--remount-ro",
                            "/",
                            "--remount-ro",
                            "/dev",
                            "--",
                            sys.executable,
                            "-c",
                            (
                                "from pathlib import Path; "
                                f"Path({str(marker)!r}).touch()"
                            ),
                        )
                        with (
                            injected_failure,
                            patch.object(
                                SupervisedProcessRunner,
                                "_kill_owned",
                                side_effect=kill_then_report_failure,
                            ),
                        ):
                            result = runner.run(command, workspace, 5)

                        self.assertEqual(
                            result.status,
                            ExecutionStatus.SPAWN_ERROR,
                            result.stderr,
                        )
                        self.assertFalse(marker.exists())
                        self._assert_observation(
                            runner,
                            outcome_status=ExecutionStatus.SPAWN_ERROR,
                            reason=expected_reason,
                            cleanup_succeeded=False,
                            final_usage_scan_completed=False,
                        )

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs supervisor")
    def test_child_has_devnull_stdin_empty_environment_nice_and_exact_rlimits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            caps = _caps()
            environment_result = _runner(workspace, caps=caps).run(
                ("/usr/bin/env",), workspace, 5
            )

            script = (
                "import json, os, resource, sys\n"
                "print(json.dumps({\n"
                " 'stdin': sys.stdin.buffer.read().decode(),\n"
                " 'nice': os.nice(0),\n"
                " 'nproc': resource.getrlimit(resource.RLIMIT_NPROC),\n"
                " 'as': resource.getrlimit(resource.RLIMIT_AS),\n"
                " 'fsize': resource.getrlimit(resource.RLIMIT_FSIZE),\n"
                " 'nofile': resource.getrlimit(resource.RLIMIT_NOFILE),\n"
                " 'core': resource.getrlimit(resource.RLIMIT_CORE),\n"
                " 'cpu': resource.getrlimit(resource.RLIMIT_CPU),\n"
                " 'msgqueue': resource.getrlimit(resource.RLIMIT_MSGQUEUE),\n"
                " 'rtprio': resource.getrlimit(resource.RLIMIT_RTPRIO),\n"
                " 'memlock': resource.getrlimit(resource.RLIMIT_MEMLOCK),\n"
                "}))\n"
            )
            limits_result = _runner(workspace, caps=caps).run(
                (sys.executable, "-c", script), workspace, 5
            )

        self.assertEqual(environment_result.status, ExecutionStatus.COMPLETED)
        self.assertEqual(environment_result.stdout, "")
        self.assertEqual(limits_result.status, ExecutionStatus.COMPLETED)
        observed = json.loads(limits_result.stdout)
        self.assertEqual(observed["stdin"], "")
        self.assertGreaterEqual(observed["nice"], caps.nice_increment)
        self.assertEqual(observed["nproc"], [caps.rlimit_nproc] * 2)
        self.assertEqual(observed["as"], [caps.rlimit_address_space_bytes] * 2)
        self.assertEqual(observed["fsize"], [caps.rlimit_file_size_bytes] * 2)
        self.assertEqual(observed["nofile"], [caps.rlimit_open_files] * 2)
        self.assertEqual(observed["core"], [0, 0])
        self.assertEqual(observed["cpu"], [caps.rlimit_cpu_seconds] * 2)
        self.assertEqual(observed["msgqueue"], [0, 0])
        self.assertEqual(observed["rtprio"], [0, 0])
        self.assertEqual(observed["memlock"], [0, 0])

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs supervisor")
    def test_stdout_flood_is_bounded_drained_and_killed_with_fixed_reason(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            result = _runner(
                workspace,
                caps=_caps(max_stdout_bytes=4096),
            ).run(
                (
                    sys.executable,
                    "-c",
                    "import os, time; os.write(1, b'x' * 1048576); time.sleep(30)",
                ),
                workspace,
                10,
            )

        self.assertEqual(result.status, ExecutionStatus.FAILED)
        self.assertIsNone(result.exit_code)
        self.assertLessEqual(len(result.stdout.encode()), 4096)
        self.assertIn("killed invocation: stdout-byte-limit-exceeded.", result.stderr)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs supervisor")
    def test_normal_exit_between_poll_and_proc_scan_is_not_a_watchdog_failure(self) -> None:
        def delayed_empty_process_table():
            time.sleep(0.05)
            return {}

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            runner = _runner(workspace)
            with patch.object(
                resource_supervisor,
                "_scan_process_table",
                side_effect=delayed_empty_process_table,
            ):
                result = runner.run(
                    (sys.executable, "-c", "import time; time.sleep(0.02)"),
                    workspace,
                    5,
                )

        self.assertEqual(result.status, ExecutionStatus.COMPLETED, result.stderr)
        self.assertEqual(result.exit_code, 0)
        self._assert_observation(
            runner,
            outcome_status=ExecutionStatus.COMPLETED,
            reason=None,
            cleanup_succeeded=True,
            final_usage_scan_completed=True,
        )

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs supervisor")
    def test_nonzero_exit_has_terminal_observation_and_final_scan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            runner = _runner(workspace)
            result = runner.run(
                (sys.executable, "-c", "raise SystemExit(7)"),
                workspace,
                5,
            )

        self.assertEqual(result.status, ExecutionStatus.FAILED, result.stderr)
        self.assertEqual(result.exit_code, 7)
        self._assert_observation(
            runner,
            outcome_status=ExecutionStatus.FAILED,
            reason="process-exit-nonzero",
            cleanup_succeeded=True,
            final_usage_scan_completed=True,
        )

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs supervisor")
    def test_aggregate_rss_limit_kills_the_owned_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            result = _runner(
                workspace,
                caps=_caps(max_aggregate_rss_bytes=20 * 1024 * 1024),
            ).run(
                (
                    sys.executable,
                    "-c",
                    "import time; value = bytearray(64 * 1024 * 1024); time.sleep(30)",
                ),
                workspace,
                10,
            )

        self.assertEqual(result.status, ExecutionStatus.FAILED)
        self.assertIn("aggregate-rss-byte-limit-exceeded", result.stderr)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs supervisor")
    def test_aggregate_process_limit_kills_a_forking_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            script = (
                "import subprocess, sys, time\n"
                "children = [subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']) for _ in range(8)]\n"
                "time.sleep(30)\n"
            )
            result = _runner(
                workspace,
                caps=_caps(max_processes=3),
            ).run((sys.executable, "-c", script), workspace, 10)

        self.assertEqual(result.status, ExecutionStatus.FAILED)
        self.assertIn("process-count-limit-exceeded", result.stderr)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs supervisor")
    def test_workspace_allocated_block_growth_is_limited_above_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "baseline.bin").write_bytes(b"a" * 128 * 1024)
            result = _runner(
                workspace,
                root_policy=_root_policy(allocated_bytes=64 * 1024),
            ).run(
                (
                    sys.executable,
                    "-c",
                    "from pathlib import Path; import time; Path('growth.bin').write_bytes(b'x' * 524288); time.sleep(30)",
                ),
                workspace,
                10,
            )

        self.assertEqual(result.status, ExecutionStatus.FAILED)
        self.assertIn(
            "watched-root-allocated-byte-limit-exceeded:workspace",
            result.stderr,
        )

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs supervisor")
    def test_final_scan_catches_quick_workspace_flood_after_normal_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            runner = _runner(
                workspace,
                caps=_caps(disk_poll_interval_seconds=60.0),
                root_policy=_root_policy(allocated_bytes=64 * 1024),
            )
            result = runner.run(
                (
                    sys.executable,
                    "-c",
                    "from pathlib import Path; import time; time.sleep(0.1); Path('quick.bin').write_bytes(b'x' * 2097152)",
                ),
                workspace,
                10,
            )

        self.assertEqual(result.status, ExecutionStatus.FAILED)
        self.assertIn(
            "watched-root-allocated-byte-limit-exceeded:workspace",
            result.stderr,
        )
        self._assert_observation(
            runner,
            outcome_status=ExecutionStatus.FAILED,
            reason="watched-root-allocated-byte-limit-exceeded:workspace",
            cleanup_succeeded=True,
            final_usage_scan_completed=True,
        )

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs supervisor")
    def test_final_scan_visits_later_root_after_first_root_violation(self) -> None:
        workspace_policy = _root_policy(allocated_bytes=64 * 1024)
        home_policy = WatchedRootPolicy(
            label="agent-home",
            max_allocated_byte_growth=8 * 1024 * 1024,
            max_file_count_growth=1_000,
        )
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            workspace = base / "workspace"
            agent_home = base / "agent-home"
            workspace.mkdir()
            agent_home.mkdir()
            policy = ResourceInvocationPolicy(
                name="test",
                caps=_caps(disk_poll_interval_seconds=60.0),
                watched_root_policies=(workspace_policy, home_policy),
                namespace_tmp_policy=None,
                require_bubblewrap_pid_namespace=False,
            )
            runner = SupervisedProcessRunner(
                (policy,),
                {"workspace": workspace, "agent-home": agent_home},
            )
            real_scan = resource_supervisor._scan_watched_root_limit
            observations: list[tuple[str, str | None]] = []

            def observe_scan(root, baseline):
                reason = real_scan(root, baseline)
                observations.append((root.policy.label, reason))
                return reason

            with patch.object(
                resource_supervisor,
                "_scan_watched_root_limit",
                side_effect=observe_scan,
            ):
                result = runner.run(
                    (
                        sys.executable,
                        "-c",
                        "open('quick.bin','wb').write(b'x' * (2 * 1024 * 1024))",
                    ),
                    workspace,
                    5,
                )

        violation_index = next(
            index
            for index, (label, reason) in enumerate(observations)
            if label == "workspace" and reason is not None
        )
        self.assertIn(
            "agent-home",
            [label for label, _reason in observations[violation_index + 1 :]],
        )
        self.assertEqual(result.status, ExecutionStatus.FAILED)
        self._assert_observation(
            runner,
            outcome_status=ExecutionStatus.FAILED,
            reason="watched-root-allocated-byte-limit-exceeded:workspace",
            cleanup_succeeded=True,
            final_usage_scan_completed=True,
        )

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs supervisor")
    def test_final_scan_counts_hardlink_names_as_distinct_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            runner = _runner(
                workspace,
                root_policy=_root_policy(
                    allocated_bytes=8 * 1024 * 1024,
                    files=5,
                ),
                caps=_caps(disk_poll_interval_seconds=60.0),
            )
            result = runner.run(
                (
                    sys.executable,
                    "-c",
                    (
                        "import os; open('seed','wb').write(b'x'); "
                        "[os.link('seed', f'link-{i}') for i in range(20)]"
                    ),
                ),
                workspace,
                5,
            )

        self.assertEqual(result.status, ExecutionStatus.FAILED)
        self._assert_observation(
            runner,
            outcome_status=ExecutionStatus.FAILED,
            reason="watched-root-file-count-limit-exceeded:workspace",
            cleanup_succeeded=True,
            final_usage_scan_completed=True,
        )

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs supervisor")
    def test_watched_root_identity_swap_fails_closed_while_open_fd_stays_pinned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            workspace = base / "workspace"
            moved = base / "moved"
            workspace.mkdir()
            marker = workspace / "ready"

            def replace_root() -> None:
                deadline = time.monotonic() + 5
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                workspace.rename(moved)
                workspace.mkdir()

            replacer = threading.Thread(target=replace_root)
            replacer.start()
            runner = _runner(workspace)
            result = runner.run(
                (
                    sys.executable,
                    "-c",
                    "from pathlib import Path; import time; Path('ready').touch(); time.sleep(30)",
                ),
                workspace,
                10,
            )
            replacer.join(timeout=5)

        self.assertFalse(replacer.is_alive())
        self.assertEqual(result.status, ExecutionStatus.FAILED)
        self.assertIn("watched-root-identity-changed:workspace", result.stderr)
        self._assert_observation(
            runner,
            outcome_status=ExecutionStatus.FAILED,
            reason="watched-root-identity-changed:workspace",
            cleanup_succeeded=True,
            final_usage_scan_completed=False,
        )

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs supervisor")
    def test_aggregate_write_bytes_limit_catches_rewrite_io_without_disk_growth(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            script = (
                "import os, time\n"
                "fd = os.open('rewrite.bin', os.O_CREAT | os.O_RDWR, 0o600)\n"
                "data = b'x' * 1048576\n"
                "while True:\n"
                " os.pwrite(fd, data, 0); os.fsync(fd)\n"
            )
            result = _runner(
                workspace,
                caps=_caps(max_aggregate_write_bytes=512 * 1024),
            ).run((sys.executable, "-c", script), workspace, 10)

        self.assertEqual(result.status, ExecutionStatus.FAILED)
        self.assertIn("aggregate-write-byte-limit-exceeded", result.stderr)

    @staticmethod
    def _pid_is_running(pid: int) -> bool:
        try:
            state = (Path("/proc") / str(pid) / "stat").read_text().split()[2]
            return state != "Z"
        except FileNotFoundError:
            return False

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs supervisor")
    def test_timeout_kills_a_seen_descendant_that_detached_its_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            pid_path = workspace / "detached.pid"
            child = (
                "import os, time\n"
                "from pathlib import Path\n"
                f"Path({str(pid_path)!r}).write_text(str(os.getpid()))\n"
                "time.sleep(30)\n"
            )
            parent = (
                "import subprocess, sys, time\n"
                "from pathlib import Path\n"
                f"subprocess.Popen([sys.executable, '-c', {child!r}], start_new_session=True)\n"
                f"path = Path({str(pid_path)!r})\n"
                "while not path.exists(): time.sleep(0.01)\n"
                "print('ready', flush=True)\n"
                "time.sleep(30)\n"
            )
            runner = _runner(workspace)
            result = runner.run(
                (sys.executable, "-c", parent), workspace, 0.8
            )
            detached_pid = int(pid_path.read_text())
            deadline = time.monotonic() + 2
            while self._pid_is_running(detached_pid) and time.monotonic() < deadline:
                time.sleep(0.02)

        self.assertEqual(result.status, ExecutionStatus.TIMED_OUT)
        self.assertIn("ready", result.stdout)
        self.assertFalse(self._pid_is_running(detached_pid))
        self._assert_observation(
            runner,
            outcome_status=ExecutionStatus.TIMED_OUT,
            reason="wall-timeout",
            cleanup_succeeded=True,
            final_usage_scan_completed=True,
        )

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs supervisor")
    def test_cleanup_failure_cannot_claim_a_completed_final_scan(self) -> None:
        real_kill = SupervisedProcessRunner._kill_owned

        def kill_but_report_failure(*args, **kwargs):
            real_kill(*args, **kwargs)
            return False

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            runner = _runner(workspace)
            with patch.object(
                SupervisedProcessRunner,
                "_kill_owned",
                side_effect=kill_but_report_failure,
            ):
                result = runner.run(
                    (sys.executable, "-c", "import time; time.sleep(30)"),
                    workspace,
                    0.1,
                )

        self.assertEqual(result.status, ExecutionStatus.TIMED_OUT)
        self._assert_observation(
            runner,
            outcome_status=ExecutionStatus.TIMED_OUT,
            reason="process-tree-cleanup-failed",
            cleanup_succeeded=False,
            final_usage_scan_completed=False,
        )

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs supervisor")
    def test_supervisor_interruption_records_cleanup_and_final_scan_before_reraise(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            runner = _runner(workspace)
            with patch.object(
                resource_supervisor._Violation,
                "wait",
                side_effect=KeyboardInterrupt(),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    runner.run(
                        (sys.executable, "-c", "import time; time.sleep(30)"),
                        workspace,
                        10,
                    )

        self._assert_observation(
            runner,
            outcome_status=ExecutionStatus.FAILED,
            reason="supervisor-interrupted:KeyboardInterrupt",
            cleanup_succeeded=True,
            final_usage_scan_completed=True,
        )

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs supervisor")
    def test_final_scan_failure_does_not_mask_original_supervisor_interruption(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            runner = _runner(workspace)
            with (
                patch.object(
                    resource_supervisor._Violation,
                    "wait",
                    side_effect=KeyboardInterrupt(),
                ),
                patch.object(
                    resource_supervisor,
                    "_scan_all_final_usage",
                    side_effect=SystemExit(23),
                ),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    runner.run(
                        (sys.executable, "-c", "import time; time.sleep(30)"),
                        workspace,
                        10,
                    )

        self._assert_observation(
            runner,
            outcome_status=ExecutionStatus.FAILED,
            reason="resource-final-usage-scan-failed",
            cleanup_succeeded=True,
            final_usage_scan_completed=False,
        )

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs supervisor")
    def test_interruption_observation_preserves_concrete_final_scan_violation(
        self,
    ) -> None:
        scans = 0

        def violation_only_on_final_scan(_root, _baseline):
            nonlocal scans
            scans += 1
            if scans >= 2:
                return "watched-root-file-count-limit-exceeded:workspace"
            return None

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            runner = _runner(workspace)
            with (
                patch.object(
                    resource_supervisor._Violation,
                    "wait",
                    side_effect=KeyboardInterrupt(),
                ),
                patch.object(
                    resource_supervisor,
                    "_scan_watched_root_limit",
                    side_effect=violation_only_on_final_scan,
                ),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    runner.run(
                        (sys.executable, "-c", "import time; time.sleep(30)"),
                        workspace,
                        10,
                    )

        self._assert_observation(
            runner,
            outcome_status=ExecutionStatus.FAILED,
            reason="watched-root-file-count-limit-exceeded:workspace",
            cleanup_succeeded=True,
            final_usage_scan_completed=True,
        )

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux/bubblewrap supervisor")
    def test_namespace_tmpfs_allocated_blocks_are_observed_through_proc_root(self) -> None:
        bubblewrap = Path("/usr/bin/bwrap")
        if not bubblewrap.is_file():
            self.skipTest("bubblewrap is unavailable")
        smoke = subprocess.run(
            (
                str(bubblewrap),
                "--unshare-all",
                "--ro-bind",
                "/",
                "/",
                "--tmpfs",
                "/tmp",
                "--",
                "/bin/true",
            ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={},
            timeout=5,
            check=False,
        )
        if smoke.returncode != 0:
            self.skipTest("bubblewrap namespaces are unavailable")
        namespace_policy = WatchedRootPolicy(
            label="namespace-tmp",
            max_allocated_byte_growth=64 * 1024,
            max_file_count_growth=100,
            subtract_baseline=False,
        )
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            command = (
                str(bubblewrap),
                "--die-with-parent",
                "--new-session",
                "--unshare-all",
                "--clearenv",
                "--ro-bind",
                "/",
                "/",
                "--tmpfs",
                "/tmp",
                "--proc",
                "/proc",
                "--remount-ro",
                "/",
                "--remount-ro",
                "/dev",
                "--",
                sys.executable,
                "-c",
                "from pathlib import Path; import time; Path('/tmp/growth').write_bytes(b'x' * 524288); time.sleep(30)",
            )
            result = _runner(
                workspace,
                namespace_tmp_policy=namespace_policy,
                require_bubblewrap_pid_namespace=True,
            ).run(command, workspace, 10)

        self.assertEqual(result.status, ExecutionStatus.FAILED)
        self.assertIn(
            "watched-root-allocated-byte-limit-exceeded:namespace-tmp",
            result.stderr,
        )

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux/bubblewrap supervisor")
    def test_final_scan_catches_quick_namespace_tmpfs_flood_after_exit(self) -> None:
        bubblewrap = Path("/usr/bin/bwrap")
        if not bubblewrap.is_file():
            self.skipTest("bubblewrap is unavailable")
        namespace_policy = WatchedRootPolicy(
            label="namespace-tmp",
            max_allocated_byte_growth=64 * 1024,
            max_file_count_growth=100,
            subtract_baseline=False,
        )
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            command = (
                str(bubblewrap),
                "--die-with-parent",
                "--new-session",
                "--unshare-all",
                "--clearenv",
                "--ro-bind",
                "/",
                "/",
                "--tmpfs",
                "/tmp",
                "--proc",
                "/proc",
                "--remount-ro",
                "/",
                "--remount-ro",
                "/dev",
                "--",
                sys.executable,
                "-c",
                "from pathlib import Path; import time; time.sleep(0.1); Path('/tmp/quick').write_bytes(b'x' * 2097152)",
            )
            runner = _runner(
                workspace,
                caps=_caps(disk_poll_interval_seconds=60.0),
                namespace_tmp_policy=namespace_policy,
                require_bubblewrap_pid_namespace=True,
            )
            result = runner.run(command, workspace, 10)

        self.assertEqual(result.status, ExecutionStatus.FAILED, result.stderr)
        self.assertIn(
            "watched-root-allocated-byte-limit-exceeded:namespace-tmp",
            result.stderr,
        )
        assert runner.last_observation is not None
        self.assertTrue(runner.last_observation.namespace_tmp_pinned_before_exec)
        self._assert_observation(
            runner,
            outcome_status=ExecutionStatus.FAILED,
            reason="watched-root-allocated-byte-limit-exceeded:namespace-tmp",
            cleanup_succeeded=True,
            final_usage_scan_completed=True,
        )

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux/bubblewrap supervisor")
    def test_private_pid_namespace_stops_unseen_double_fork_setsid_escape(self) -> None:
        bubblewrap = Path("/usr/bin/bwrap")
        if not bubblewrap.is_file():
            self.skipTest("bubblewrap is unavailable")
        smoke = subprocess.run(
            (
                str(bubblewrap),
                "--unshare-all",
                "--ro-bind",
                "/",
                "/",
                "--",
                "/bin/true",
            ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={},
            timeout=5,
            check=False,
        )
        if smoke.returncode != 0:
            self.skipTest("bubblewrap namespaces are unavailable")
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            heartbeat = workspace / "escaped.heartbeat"
            payload = (
                "import os, time\n"
                "from pathlib import Path\n"
                "read_fd, write_fd = os.pipe()\n"
                "first = os.fork()\n"
                "if first == 0:\n"
                " os.close(read_fd); os.setsid(); second = os.fork()\n"
                " if second != 0: os.close(write_fd); os._exit(0)\n"
                f" path = Path({str(heartbeat)!r})\n"
                " path.write_text('ready')\n"
                " os.write(write_fd, b'1'); os.close(write_fd)\n"
                " while True:\n"
                "  path.write_text(str(time.monotonic_ns())); time.sleep(0.02)\n"
                "os.close(write_fd)\n"
                "assert os.read(read_fd, 1) == b'1'\n"
                "os.close(read_fd)\n"
            )
            command = (
                str(bubblewrap),
                "--die-with-parent",
                "--new-session",
                "--unshare-all",
                "--clearenv",
                "--ro-bind",
                "/",
                "/",
                "--bind",
                str(workspace),
                str(workspace),
                "--proc",
                "/proc",
                "--remount-ro",
                "/",
                "--remount-ro",
                "/dev",
                "--",
                sys.executable,
                "-c",
                payload,
            )
            result = _runner(
                workspace,
                require_bubblewrap_pid_namespace=True,
            ).run(command, workspace, 5)
            self.assertTrue(heartbeat.exists())
            after = heartbeat.read_text()
            time.sleep(0.15)
            stable = heartbeat.read_text()

        self.assertEqual(result.status, ExecutionStatus.COMPLETED, result.stderr)
        self.assertEqual(after, stable)


if __name__ == "__main__":
    unittest.main()
