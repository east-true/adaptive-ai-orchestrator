import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

if os.name == "posix":
    import fcntl

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.execution import _windows_gate as gate_protocol
from adaptive_orchestrator.execution import _windows_process as windows_process


class _FakeProcess:
    def __init__(self, events: list[str], pid: int = 43210) -> None:
        self.events = events
        self.pid = pid
        self._handle = 98765
        self.stdout = StringIO("")
        self.stderr = StringIO("")
        self.returncode: int | None = None

    def poll(self):
        return self.returncode

    def kill(self):
        self.events.append("process.kill")
        self.returncode = -9

    def wait(self, timeout=None):
        self.events.append("process.wait")
        return self.returncode


class _FakeJob:
    def __init__(self, events: list[str], assign_error: OSError | None = None) -> None:
        self.events = events
        self.assign_error = assign_error
        self.closed = False
        self.armed = True

    def assign_process_handle(self, process_handle: object) -> None:
        self.events.append(f"job.assign_handle:{process_handle}")
        if self.assign_error is not None:
            raise self.assign_error

    def terminate(self, exit_code: int = 1) -> None:
        self.events.append("job.terminate")

    def disarm(self) -> None:
        self.events.append("job.disarm")
        self.armed = False

    def close(self) -> None:
        self.events.append("job.close")
        self.closed = True


class _FakeGuard:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.released = False

    def release(self) -> None:
        self.events.append("guard.release")
        self.released = True


class WindowsProcessLaunchTests(unittest.TestCase):
    def _prepare(
        self,
        *,
        job: _FakeJob | None = None,
    ) -> tuple[
        windows_process.WindowsProcessLaunch,
        _FakeProcess,
        _FakeJob,
        _FakeGuard,
        list[str],
        Path,
    ]:
        events: list[str] = []
        process = _FakeProcess(events)
        resolved_job = job or _FakeJob(events)
        guard = _FakeGuard(events)
        captured_control_dir: Path | None = None

        def popen(argv, **kwargs):
            nonlocal captured_control_dir
            events.append("gate.spawn")
            captured_control_dir = Path(argv[-1])
            request = gate_protocol._read_json(captured_control_dir / gate_protocol.CONFIG_FILE)
            gate_protocol._atomic_write_json(
                captured_control_dir / gate_protocol.READY_FILE,
                {
                    "protocol": gate_protocol.PROTOCOL_VERSION,
                    "token": request["token"],
                    "kind": "ready",
                    "gate_pid": process.pid,
                },
            )
            self.assertEqual(argv[1:3], ("-I", "-S"))
            self.assertEqual(Path(argv[3]), Path(gate_protocol.__file__).resolve())
            self.assertEqual(kwargs["cwd"], Path("C:/workspace"))
            self.assertTrue(kwargs["close_fds"])
            self.assertEqual(kwargs["creationflags"], windows_process._CREATE_NEW_PROCESS_GROUP)
            return process

        with (
            patch.object(windows_process.WindowsJob, "create", return_value=resolved_job),
            patch.object(windows_process._ParentGuard, "acquire", return_value=guard),
            patch.object(windows_process.subprocess, "Popen", side_effect=popen),
        ):
            launch = windows_process.WindowsProcessLaunch.prepare(
                ("agent.exe", "space arg", "", "한글"),
                Path("C:/workspace"),
            )

        assert captured_control_dir is not None
        return launch, process, resolved_job, guard, events, captured_control_dir

    def test_prepare_assigns_gate_before_release_and_preserves_original_argv(self) -> None:
        launch, process, _job, _guard, events, control_dir = self._prepare()
        try:
            request = gate_protocol._read_json(control_dir / gate_protocol.CONFIG_FILE)
            self.assertEqual(request["argv"], ["agent.exe", "space arg", "", "한글"])
            self.assertEqual(events[:2], ["gate.spawn", f"job.assign_handle:{process._handle}"])
            self.assertFalse((control_dir / gate_protocol.RELEASE_FILE).exists())

            launch.release()

            release = gate_protocol._read_json(control_dir / gate_protocol.RELEASE_FILE)
            self.assertEqual(release["kind"], "release")
            self.assertEqual(release["token"], request["token"])
        finally:
            launch.terminate_and_reap()

    def test_completed_outcome_is_authoritative_and_disarms_before_close(self) -> None:
        launch, process, job, guard, events, control_dir = self._prepare()
        launch.release()
        request = gate_protocol._read_json(control_dir / gate_protocol.CONFIG_FILE)
        gate_protocol._atomic_write_json(
            control_dir / gate_protocol.OUTCOME_FILE,
            {
                "protocol": gate_protocol.PROTOCOL_VERSION,
                "token": request["token"],
                "kind": "completed",
                "return_code": 37,
            },
        )
        process.returncode = 0

        outcome = launch.outcome()
        launch.finish_normal()

        self.assertEqual(outcome.kind, "completed")
        self.assertEqual(outcome.return_code, 37)
        self.assertLess(events.index("job.disarm"), events.index("job.close"))
        self.assertNotIn("job.terminate", events)
        self.assertTrue(job.closed)
        self.assertTrue(guard.released)
        self.assertFalse(control_dir.exists())

    def test_spawn_error_outcome_is_validated_separately_from_gate_exit(self) -> None:
        launch, process, _job, _guard, _events, control_dir = self._prepare()
        try:
            launch.release()
            request = gate_protocol._read_json(control_dir / gate_protocol.CONFIG_FILE)
            gate_protocol._atomic_write_json(
                control_dir / gate_protocol.OUTCOME_FILE,
                {
                    "protocol": gate_protocol.PROTOCOL_VERSION,
                    "token": request["token"],
                    "kind": "spawn_error",
                    "error": "FileNotFoundError: missing-agent",
                },
            )
            process.returncode = gate_protocol.SPAWN_ERROR_EXIT_CODE

            outcome = launch.outcome()

            self.assertEqual(outcome.kind, "spawn_error")
            self.assertIn("missing-agent", outcome.error or "")
        finally:
            launch.terminate_and_reap()

    def test_missing_or_mismatched_outcome_fails_closed(self) -> None:
        launch, process, _job, _guard, _events, control_dir = self._prepare()
        try:
            launch.release()
            process.returncode = 0
            self.assertEqual(launch.outcome().kind, "protocol_error")

            gate_protocol._atomic_write_json(
                control_dir / gate_protocol.OUTCOME_FILE,
                {
                    "protocol": gate_protocol.PROTOCOL_VERSION,
                    "token": "0" * 64,
                    "kind": "completed",
                    "return_code": 0,
                },
            )
            self.assertEqual(launch.outcome().kind, "protocol_error")
        finally:
            launch.terminate_and_reap()

    def test_terminate_kills_job_and_reaps_gate_without_disarming(self) -> None:
        launch, process, job, guard, events, control_dir = self._prepare()
        launch.release()

        launch.terminate_and_reap()

        self.assertIn("job.terminate", events)
        self.assertIn("job.close", events)
        self.assertNotIn("job.disarm", events)
        self.assertIn("process.kill", events)
        self.assertIn("process.wait", events)
        self.assertTrue(job.closed)
        self.assertTrue(guard.released)
        self.assertFalse(control_dir.exists())

    def test_assignment_failure_never_publishes_release_and_cleans_up(self) -> None:
        events: list[str] = []
        process = _FakeProcess(events)
        job = _FakeJob(events, assign_error=OSError("assign failed"))
        guard = _FakeGuard(events)
        published_names: list[str] = []
        real_write = gate_protocol._atomic_write_json

        def record_write(path, value):
            published_names.append(Path(path).name)
            return real_write(path, value)

        def popen(argv, **_kwargs):
            control_dir = Path(argv[-1])
            request = gate_protocol._read_json(control_dir / gate_protocol.CONFIG_FILE)
            real_write(
                control_dir / gate_protocol.READY_FILE,
                {
                    "protocol": gate_protocol.PROTOCOL_VERSION,
                    "token": request["token"],
                    "kind": "ready",
                    "gate_pid": process.pid,
                },
            )
            return process

        with (
            patch.object(windows_process.WindowsJob, "create", return_value=job),
            patch.object(windows_process._ParentGuard, "acquire", return_value=guard),
            patch.object(windows_process.subprocess, "Popen", side_effect=popen),
            patch.object(gate_protocol, "_atomic_write_json", side_effect=record_write),
            self.assertRaisesRegex(OSError, "assign failed"),
        ):
            windows_process.WindowsProcessLaunch.prepare(("agent.exe",), Path("C:/workspace"))

        self.assertNotIn(gate_protocol.RELEASE_FILE, published_names)
        self.assertIn("job.terminate", events)
        self.assertIn("process.kill", events)
        self.assertTrue(guard.released)


@unittest.skipUnless(os.name == "posix", "portable gate protocol exercise")
class WindowsGateProtocolTests(unittest.TestCase):
    def _start_gate(
        self,
        control_dir: Path,
        command: list[str],
        *,
        cwd: Path,
    ):
        token = "a" * 64
        gate_protocol._atomic_write_json(
            control_dir / gate_protocol.CONFIG_FILE,
            {"protocol": gate_protocol.PROTOCOL_VERSION, "token": token, "argv": command},
        )
        guard_path = control_dir / gate_protocol.GUARD_FILE
        guard_path.write_bytes(b"\0")
        guard = guard_path.open("r+b", buffering=0)
        fcntl.flock(guard.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
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
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        ready_path = control_dir / gate_protocol.READY_FILE
        deadline = time.monotonic() + 5
        while not ready_path.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(ready_path.exists())
        return process, guard, token

    def _release(self, control_dir: Path, token: str) -> None:
        gate_protocol._atomic_write_json(
            control_dir / gate_protocol.RELEASE_FILE,
            {"protocol": gate_protocol.PROTOCOL_VERSION, "token": token, "kind": "release"},
        )

    def test_gate_waits_for_release_then_preserves_argv_cwd_stdin_and_streams(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            control_dir = root / "control"
            workspace = root / "workspace"
            control_dir.mkdir()
            workspace.mkdir()
            capture_path = root / "capture.json"
            target_code = (
                "import json, os, sys\n"
                "from pathlib import Path\n"
                f"Path({str(capture_path)!r}).write_text(json.dumps({{'argv': sys.argv[1:], 'cwd': os.getcwd(), 'stdin': sys.stdin.read()}}, ensure_ascii=False), encoding='utf-8')\n"
                "print('target-out', flush=True)\n"
                "print('target-err', file=sys.stderr, flush=True)\n"
                "raise SystemExit(7)\n"
            )
            process, guard, token = self._start_gate(
                control_dir,
                [sys.executable, "-c", target_code, "space arg", "", "한글"],
                cwd=workspace,
            )
            try:
                self.assertFalse(capture_path.exists())
                self._release(control_dir, token)
                stdout, stderr = process.communicate("input text", timeout=5)
            finally:
                fcntl.flock(guard.fileno(), fcntl.LOCK_UN)
                guard.close()
                if process.poll() is None:
                    process.kill()
                    process.wait()

            capture = json.loads(capture_path.read_text(encoding="utf-8"))
            outcome = gate_protocol._read_json(control_dir / gate_protocol.OUTCOME_FILE)
            self.assertEqual(process.returncode, 0)
            self.assertEqual(capture["argv"], ["space arg", "", "한글"])
            self.assertEqual(capture["cwd"], str(workspace))
            self.assertEqual(capture["stdin"], "input text")
            self.assertEqual(stdout, "target-out\n")
            self.assertEqual(stderr, "target-err\n")
            self.assertEqual(outcome["kind"], "completed")
            self.assertEqual(outcome["return_code"], 7)

    def test_gate_reports_target_spawn_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            control_dir = root / "control"
            control_dir.mkdir()
            process, guard, token = self._start_gate(
                control_dir,
                [str(root / "missing-agent")],
                cwd=root,
            )
            try:
                self._release(control_dir, token)
                process.communicate(timeout=5)
            finally:
                fcntl.flock(guard.fileno(), fcntl.LOCK_UN)
                guard.close()
                if process.poll() is None:
                    process.kill()
                    process.wait()

            outcome = gate_protocol._read_json(control_dir / gate_protocol.OUTCOME_FILE)
            self.assertEqual(process.returncode, gate_protocol.SPAWN_ERROR_EXIT_CODE)
            self.assertEqual(outcome["kind"], "spawn_error")
            self.assertIn("missing-agent", outcome["error"])

    def test_gate_exits_without_launch_when_parent_guard_is_released(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            control_dir = root / "control"
            control_dir.mkdir()
            side_effect = root / "must-not-exist"
            target_code = f"from pathlib import Path; Path({str(side_effect)!r}).touch()"
            process, guard, _token = self._start_gate(
                control_dir,
                [sys.executable, "-c", target_code],
                cwd=root,
            )
            fcntl.flock(guard.fileno(), fcntl.LOCK_UN)
            guard.close()
            process.communicate(timeout=5)

            outcome = gate_protocol._read_json(control_dir / gate_protocol.OUTCOME_FILE)
            self.assertEqual(process.returncode, gate_protocol.PROTOCOL_ERROR_EXIT_CODE)
            self.assertEqual(outcome["kind"], "protocol_error")
            self.assertFalse(side_effect.exists())


@unittest.skipUnless(os.name == "nt", "real Windows Job Object behavior")
class WindowsJobIntegrationTests(unittest.TestCase):
    def test_timeout_stops_owned_descendants_but_not_unrelated_process(self) -> None:
        from adaptive_orchestrator.core.domain import ExecutionStatus
        from adaptive_orchestrator.execution.process_runner import SubprocessRunner

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            descendant_heartbeat = workspace / "owned.heartbeat"
            sibling_heartbeat = workspace / "sibling.heartbeat"
            heartbeat_code = (
                "import time\n"
                "from pathlib import Path\n"
                "path = Path(__import__('sys').argv[1])\n"
                "deadline = time.monotonic() + 10\n"
                "while time.monotonic() < deadline:\n"
                "    with path.open('a', encoding='utf-8') as stream:\n"
                "        stream.write('x')\n"
                "    time.sleep(0.02)\n"
            )
            sibling = subprocess.Popen(
                (sys.executable, "-c", heartbeat_code, str(sibling_heartbeat)),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            descendant_code = (
                "import os, subprocess, sys, time\n"
                "from pathlib import Path\n"
                f"child = subprocess.Popen([sys.executable, '-c', {heartbeat_code!r}, {str(descendant_heartbeat)!r}], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
                f"heartbeat = Path({str(descendant_heartbeat)!r})\n"
                "deadline = time.monotonic() + 5\n"
                "while (not heartbeat.exists() or heartbeat.stat().st_size == 0) and time.monotonic() < deadline:\n"
                "    if child.poll() is not None:\n"
                "        raise SystemExit('descendant exited before readiness')\n"
                "    time.sleep(0.02)\n"
                "if not heartbeat.exists() or heartbeat.stat().st_size == 0:\n"
                "    raise SystemExit('descendant heartbeat was not ready')\n"
                "print('ready', flush=True)\n"
                "time.sleep(60)\n"
            )
            try:
                result = SubprocessRunner().run(
                    (sys.executable, "-c", descendant_code),
                    workspace,
                    1.5,
                )
                self.assertEqual(result.status, ExecutionStatus.TIMED_OUT)
                self.assertIn("ready", result.stdout)
                deadline = time.monotonic() + 5
                while (
                    (
                        not descendant_heartbeat.exists()
                        or descendant_heartbeat.stat().st_size == 0
                        or not sibling_heartbeat.exists()
                        or sibling_heartbeat.stat().st_size == 0
                    )
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.02)
                self.assertTrue(descendant_heartbeat.exists())
                self.assertTrue(sibling_heartbeat.exists())
                sibling_size = sibling_heartbeat.stat().st_size
                previous_size: int | None = None
                stable_samples = 0
                deadline = time.monotonic() + 3
                while stable_samples < 3 and time.monotonic() < deadline:
                    current_size = descendant_heartbeat.stat().st_size
                    stable_samples = stable_samples + 1 if current_size == previous_size else 0
                    previous_size = current_size
                    time.sleep(0.1)
                self.assertEqual(stable_samples, 3)
                self.assertGreater(sibling_heartbeat.stat().st_size, sibling_size)
                self.assertIsNone(sibling.poll())
            finally:
                if sibling.poll() is None:
                    sibling.kill()
                sibling.wait()


if __name__ == "__main__":
    unittest.main()
