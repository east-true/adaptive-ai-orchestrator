import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.core.domain import ExecutionStatus
from adaptive_orchestrator.execution import process_runner as process_runner_module
from adaptive_orchestrator.execution.process_runner import SubprocessRunner


class SubprocessRunnerTests(unittest.TestCase):
    def test_windows_completed_outcome_uses_target_code_and_disarms_job(self) -> None:
        events: list[str] = []

        class GateProcess:
            def __init__(self) -> None:
                self.stdout = StringIO("out\n")
                self.stderr = StringIO("err\n")

            def wait(self, timeout=None):
                events.append("wait")
                return 0

        class Launch:
            process = GateProcess()

            def release(self):
                events.append("release")

            def outcome(self):
                events.append("outcome")
                return SimpleNamespace(kind="completed", return_code=7, error=None)

            def finish_normal(self):
                events.append("finish_normal")

            def terminate_and_reap(self):
                raise AssertionError("a completed launch must not be terminated")

            def close(self):
                events.append("close")

        launch = Launch()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(process_runner_module, "os", SimpleNamespace(name="nt")),
            patch(
                "adaptive_orchestrator.execution._windows_process.WindowsProcessLaunch.prepare",
                return_value=launch,
            ) as prepare,
            patch.object(
                process_runner_module.subprocess,
                "Popen",
                side_effect=AssertionError("the target must be launched through the gate"),
            ),
        ):
            result = SubprocessRunner().run(("agent.exe", "arg"), Path(directory), 3)

        prepare.assert_called_once()
        self.assertEqual(result.status, ExecutionStatus.FAILED)
        self.assertEqual(result.exit_code, 7)
        self.assertEqual(result.stdout, "out\n")
        self.assertEqual(result.stderr, "err\n")
        self.assertEqual(events, ["release", "wait", "outcome", "finish_normal", "close"])

    def test_windows_completed_target_cleans_descendant_that_keeps_output_pipe_open(self) -> None:
        events: list[str] = []
        release_pipe = threading.Event()

        class BlockingStream:
            def readline(self):
                release_pipe.wait()
                return ""

            def close(self):
                events.append("stdout.close")

        class GateProcess:
            def __init__(self) -> None:
                self.stdout = BlockingStream()
                self.stderr = StringIO("")

            def wait(self, timeout=None):
                events.append("wait")
                return 0

        class Launch:
            process = GateProcess()

            def release(self):
                events.append("release")

            def outcome(self):
                events.append("outcome")
                return SimpleNamespace(kind="completed", return_code=0, error=None)

            def finish_normal(self):
                raise AssertionError("an open inherited pipe must keep the Job armed")

            def terminate_and_reap(self):
                events.append("terminate_job")
                release_pipe.set()

            def close(self):
                events.append("close")

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(process_runner_module, "os", SimpleNamespace(name="nt")),
            patch.object(process_runner_module, "_WINDOWS_OUTPUT_DRAIN_GRACE_SECONDS", 0.01),
            patch(
                "adaptive_orchestrator.execution._windows_process.WindowsProcessLaunch.prepare",
                return_value=Launch(),
            ),
        ):
            result = SubprocessRunner().run(("agent.exe",), Path(directory), None)

        self.assertEqual(result.status, ExecutionStatus.COMPLETED)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("terminate_job", events)
        self.assertIn("stdout.close", events)
        self.assertEqual(events[-1], "close")

    def test_windows_spawn_protocol_failure_terminates_only_owned_job(self) -> None:
        events: list[str] = []

        class GateProcess:
            def __init__(self) -> None:
                self.stdout = StringIO("")
                self.stderr = StringIO("")

            def wait(self, timeout=None):
                events.append("wait")
                return gate_protocol_code

        gate_protocol_code = 120

        class Launch:
            process = GateProcess()

            def release(self):
                events.append("release")

            def outcome(self):
                events.append("outcome")
                return SimpleNamespace(kind="spawn_error", return_code=None, error="missing agent")

            def finish_normal(self):
                raise AssertionError("a failed launch must not be disarmed")

            def terminate_and_reap(self):
                events.append("terminate_job")

            def close(self):
                events.append("close")

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(process_runner_module, "os", SimpleNamespace(name="nt")),
            patch(
                "adaptive_orchestrator.execution._windows_process.WindowsProcessLaunch.prepare",
                return_value=Launch(),
            ),
        ):
            result = SubprocessRunner().run(("missing-agent.exe",), Path(directory), None)

        self.assertEqual(result.status, ExecutionStatus.SPAWN_ERROR)
        self.assertIsNone(result.exit_code)
        self.assertEqual(result.stderr, "missing agent")
        self.assertEqual(events, ["release", "wait", "outcome", "terminate_job", "close"])

    def test_windows_timeout_terminates_job_and_returns_timed_out(self) -> None:
        events: list[str] = []

        class GateProcess:
            def __init__(self) -> None:
                self.stdout = StringIO("")
                self.stderr = StringIO("")

            def wait(self, timeout=None):
                events.append("wait")
                raise subprocess.TimeoutExpired(("gate",), timeout)

        class Launch:
            process = GateProcess()

            def release(self):
                events.append("release")

            def outcome(self):
                raise AssertionError("a timed-out launch has no normal outcome")

            def finish_normal(self):
                raise AssertionError("a timed-out launch must not be disarmed")

            def terminate_and_reap(self):
                events.append("terminate_job")

            def close(self):
                events.append("close")

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(process_runner_module, "os", SimpleNamespace(name="nt")),
            patch(
                "adaptive_orchestrator.execution._windows_process.WindowsProcessLaunch.prepare",
                return_value=Launch(),
            ),
        ):
            result = SubprocessRunner().run(("agent.exe",), Path(directory), 0.1)

        self.assertEqual(result.status, ExecutionStatus.TIMED_OUT)
        self.assertIsNone(result.exit_code)
        self.assertEqual(events, ["release", "wait", "terminate_job", "close"])

    def test_windows_base_exception_terminates_job_and_preserves_exception(self) -> None:
        events: list[str] = []

        class StopRun(BaseException):
            pass

        class GateProcess:
            def __init__(self) -> None:
                self.stdout = StringIO("")
                self.stderr = StringIO("")

            def wait(self, timeout=None):
                events.append("wait")
                raise StopRun()

        class Launch:
            process = GateProcess()

            def release(self):
                events.append("release")

            def outcome(self):
                raise AssertionError("an interrupted launch has no normal outcome")

            def finish_normal(self):
                raise AssertionError("an interrupted launch must not be disarmed")

            def terminate_and_reap(self):
                events.append("terminate_job")

            def close(self):
                events.append("close")

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(process_runner_module, "os", SimpleNamespace(name="nt")),
            patch(
                "adaptive_orchestrator.execution._windows_process.WindowsProcessLaunch.prepare",
                return_value=Launch(),
            ),
            self.assertRaises(StopRun),
        ):
            SubprocessRunner().run(("agent.exe",), Path(directory), None)

        self.assertEqual(events, ["release", "wait", "terminate_job", "close"])

    def test_without_output_callback_captures_stdout_and_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runner = SubprocessRunner()
            result = runner.run(
                [
                    sys.executable,
                    "-c",
                    "import sys; print('out'); print('err', file=sys.stderr); sys.exit(7)",
                ],
                Path(directory),
                None,
            )

        self.assertEqual(result.status, ExecutionStatus.FAILED)
        self.assertEqual(result.stdout, "out\n")
        self.assertEqual(result.stderr, "err\n")
        self.assertEqual(result.exit_code, 7)

    def test_streams_stdout_lines_incrementally(self) -> None:
        lines: list[str] = []

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)

            def on_output_line(line: str) -> None:
                lines.append(line)
                (workspace / f"ack-{line.strip()}").touch()

            runner = SubprocessRunner(on_output_line=on_output_line)
            result = runner.run(
                [
                    sys.executable,
                    "-c",
                    "import time\n"
                    "from pathlib import Path\n"
                    f"workspace = Path({str(workspace)!r})\n"
                    "for i in range(3):\n"
                    " print(i, flush=True)\n"
                    " deadline = time.monotonic() + 2\n"
                    " while not (workspace / f'ack-{i}').exists() and time.monotonic() < deadline:\n"
                    "  time.sleep(0.01)\n"
                    " if not (workspace / f'ack-{i}').exists():\n"
                    "  raise SystemExit('output callback did not run incrementally')\n",
                ],
                workspace,
                None,
            )

        self.assertEqual(result.status, ExecutionStatus.COMPLETED)
        self.assertEqual(lines, ["0\n", "1\n", "2\n"])
        self.assertEqual(result.stdout, "0\n1\n2\n")

    def test_timeout_still_returns_timed_out_with_output_callback(self) -> None:
        lines: list[str] = []

        runner = SubprocessRunner(on_output_line=lines.append)
        with tempfile.TemporaryDirectory() as directory:
            result = runner.run(
                [
                    sys.executable,
                    "-c",
                    "import time; print('start', flush=True); time.sleep(1)",
                ],
                Path(directory),
                0.2,
            )

        self.assertEqual(result.status, ExecutionStatus.TIMED_OUT)
        self.assertIsNone(result.exit_code)
        self.assertEqual(lines, ["start\n"])
        self.assertEqual(result.stdout, "start\n")

    def test_other_non_posix_interrupt_kills_and_reaps_child_before_reraising(self) -> None:
        class InterruptingProcess:
            def __init__(self) -> None:
                self.stdout = StringIO("")
                self.stderr = StringIO("")
                self.killed = False
                self.wait_calls = 0

            def wait(self, timeout=None):
                self.wait_calls += 1
                if self.wait_calls == 1:
                    raise KeyboardInterrupt()
                return -9

            def kill(self):
                self.killed = True

        process = InterruptingProcess()
        non_posix_os = SimpleNamespace(name="java")
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(process_runner_module, "os", non_posix_os),
            patch("adaptive_orchestrator.execution.process_runner.subprocess.Popen", return_value=process) as popen,
        ):
            with self.assertRaises(KeyboardInterrupt):
                SubprocessRunner().run(("agent",), Path(directory), None)

        self.assertTrue(process.killed)
        self.assertEqual(process.wait_calls, 2)
        self.assertFalse(popen.call_args.kwargs["start_new_session"])

    @unittest.skipUnless(os.name == "posix", "POSIX process-group behavior")
    def test_timeout_kills_posix_process_group_and_reaps_direct_child(self) -> None:
        class TimingOutProcess:
            def __init__(self) -> None:
                self.pid = 43210
                self.stdout = StringIO("")
                self.stderr = StringIO("")
                self.killed = False
                self.wait_calls = 0

            def wait(self, timeout=None):
                self.wait_calls += 1
                if self.wait_calls == 1:
                    raise subprocess.TimeoutExpired(("agent",), timeout)
                return -signal.SIGKILL

            def kill(self):
                self.killed = True

        process = TimingOutProcess()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(process_runner_module.subprocess, "Popen", return_value=process) as popen,
            patch.object(process_runner_module.os, "killpg") as killpg,
        ):
            result = SubprocessRunner().run(("agent",), Path(directory), 0.1)

        self.assertEqual(result.status, ExecutionStatus.TIMED_OUT)
        self.assertIsNone(result.exit_code)
        self.assertEqual(process.wait_calls, 2)
        self.assertFalse(process.killed)
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        killpg.assert_called_once_with(process.pid, signal.SIGKILL)

    @unittest.skipUnless(os.name == "posix", "POSIX process-group behavior")
    def test_base_exception_kills_posix_process_group_before_reraising(self) -> None:
        class StopRun(BaseException):
            pass

        class InterruptingProcess:
            def __init__(self) -> None:
                self.pid = 43211
                self.stdout = StringIO("")
                self.stderr = StringIO("")
                self.wait_calls = 0

            def wait(self, timeout=None):
                self.wait_calls += 1
                if self.wait_calls == 1:
                    raise StopRun()
                return -signal.SIGKILL

            def kill(self):
                raise AssertionError("direct kill should not be needed after killpg")

        process = InterruptingProcess()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(process_runner_module.subprocess, "Popen", return_value=process),
            patch.object(process_runner_module.os, "killpg") as killpg,
        ):
            with self.assertRaises(StopRun):
                SubprocessRunner().run(("agent",), Path(directory), None)

        self.assertEqual(process.wait_calls, 2)
        killpg.assert_called_once_with(process.pid, signal.SIGKILL)

    @unittest.skipUnless(os.name == "posix", "POSIX process-group behavior")
    def test_normal_completion_does_not_kill_process_group(self) -> None:
        class CompletedProcess:
            def __init__(self) -> None:
                self.pid = 43212
                self.stdout = StringIO("")
                self.stderr = StringIO("")

            def wait(self, timeout=None):
                return 0

            def kill(self):
                raise AssertionError("normal completion must not kill the child")

        process = CompletedProcess()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(process_runner_module.subprocess, "Popen", return_value=process) as popen,
            patch.object(process_runner_module.os, "killpg") as killpg,
        ):
            result = SubprocessRunner().run(("agent",), Path(directory), None)

        self.assertEqual(result.status, ExecutionStatus.COMPLETED)
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        killpg.assert_not_called()

    @staticmethod
    def _pid_is_running(pid: int) -> bool:
        stat_path = Path("/proc") / str(pid) / "stat"
        if stat_path.exists():
            try:
                if stat_path.read_text(encoding="utf-8").split()[2] == "Z":
                    return False
            except (FileNotFoundError, IndexError, OSError):
                pass
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    @unittest.skipUnless(os.name == "posix", "POSIX process-group behavior")
    def test_timeout_stops_real_descendant_in_owned_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            pid_path = workspace / "descendant.pid"
            heartbeat_path = workspace / "descendant.heartbeat"
            descendant_code = (
                "import os, time\n"
                "from pathlib import Path\n"
                f"Path({str(pid_path)!r}).write_text(str(os.getpid()), encoding='utf-8')\n"
                f"heartbeat = Path({str(heartbeat_path)!r})\n"
                "while True:\n"
                "    heartbeat.write_text(str(time.monotonic_ns()), encoding='utf-8')\n"
                "    time.sleep(0.02)\n"
            )
            parent_code = (
                "import subprocess, sys, time\n"
                "from pathlib import Path\n"
                f"subprocess.Popen([sys.executable, '-c', {descendant_code!r}], "
                "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
                f"ready = Path({str(pid_path)!r})\n"
                "while not ready.exists():\n"
                "    time.sleep(0.01)\n"
                "print('descendant-ready', flush=True)\n"
                "time.sleep(60)\n"
            )

            descendant_pid: int | None = None
            try:
                result = SubprocessRunner().run(
                    (sys.executable, "-c", parent_code),
                    workspace,
                    1.0,
                )
                self.assertEqual(result.status, ExecutionStatus.TIMED_OUT)
                self.assertIn("descendant-ready", result.stdout)
                descendant_pid = int(pid_path.read_text(encoding="utf-8"))

                deadline = time.monotonic() + 2
                while self._pid_is_running(descendant_pid) and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertFalse(self._pid_is_running(descendant_pid))

                heartbeat = heartbeat_path.read_text(encoding="utf-8")
                time.sleep(0.1)
                self.assertEqual(heartbeat_path.read_text(encoding="utf-8"), heartbeat)
            finally:
                if descendant_pid is not None and self._pid_is_running(descendant_pid):
                    os.kill(descendant_pid, signal.SIGKILL)

    @unittest.skipUnless(os.name == "posix", "POSIX process-group behavior")
    def test_timeout_does_not_touch_an_unrelated_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            heartbeat_path = workspace / "sibling.heartbeat"
            sibling_code = (
                "import time\n"
                "from pathlib import Path\n"
                f"heartbeat = Path({str(heartbeat_path)!r})\n"
                "with heartbeat.open('a', encoding='utf-8') as stream:\n"
                "    while True:\n"
                "        stream.write('x')\n"
                "        stream.flush()\n"
                "        time.sleep(0.02)\n"
            )
            sibling = subprocess.Popen(
                (sys.executable, "-c", sibling_code),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            try:
                deadline = time.monotonic() + 2
                while (
                    (not heartbeat_path.exists() or heartbeat_path.stat().st_size == 0)
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.02)
                self.assertTrue(heartbeat_path.exists())
                before = heartbeat_path.stat().st_size

                result = SubprocessRunner().run(
                    (sys.executable, "-c", "import time; time.sleep(60)"),
                    workspace,
                    0.2,
                )

                self.assertEqual(result.status, ExecutionStatus.TIMED_OUT)
                self.assertIsNone(sibling.poll())
                deadline = time.monotonic() + 2
                while heartbeat_path.stat().st_size <= before and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertGreater(heartbeat_path.stat().st_size, before)
            finally:
                if sibling.poll() is None:
                    os.killpg(sibling.pid, signal.SIGKILL)
                sibling.wait()

    @unittest.skipUnless(os.name == "posix", "POSIX session-detachment behavior")
    def test_timeout_is_bounded_when_a_detached_descendant_holds_the_pipes(self) -> None:
        # A descendant in its own session keeps the inherited stdout/stderr open
        # and is outside the group we kill, so waiting for EOF would extend the
        # run for as long as that process lives, defeating the timeout.
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            detached_pid_path = workspace / "detached.pid"
            detached_code = (
                "import os, time\n"
                "from pathlib import Path\n"
                f"Path({str(detached_pid_path)!r}).write_text(str(os.getpid()), encoding='utf-8')\n"
                "time.sleep(60)\n"
            )
            parent_code = (
                "import os, subprocess, sys, time\n"
                "from pathlib import Path\n"
                # start_new_session detaches the grandchild from the group the
                # runner owns, while it keeps the inherited pipes.
                f"subprocess.Popen([sys.executable, '-c', {detached_code!r}], start_new_session=True)\n"
                f"ready = Path({str(detached_pid_path)!r})\n"
                "while not ready.exists():\n"
                "    time.sleep(0.01)\n"
                "print('parent-ready', flush=True)\n"
                "time.sleep(60)\n"
            )

            detached_pid: int | None = None
            try:
                started = time.monotonic()
                result = SubprocessRunner().run(
                    (sys.executable, "-c", parent_code),
                    workspace,
                    1.0,
                )
                elapsed = time.monotonic() - started
                detached_pid = int(detached_pid_path.read_text(encoding="utf-8"))

                self.assertEqual(result.status, ExecutionStatus.TIMED_OUT)
                # Bounded by the timeout plus the drain grace, not by the
                # detached descendant's own 60s lifetime.
                self.assertLess(
                    elapsed,
                    1.0 + process_runner_module._DETACHED_OUTPUT_DRAIN_GRACE_SECONDS + 8.0,
                )
                # Output collected before the cut-off is kept, and the result
                # says the capture was stopped early rather than hiding it.
                self.assertIn("parent-ready", result.stdout)
                self.assertIn("may be incomplete", result.stderr)
            finally:
                if detached_pid is not None:
                    try:
                        os.kill(detached_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_normal_completion_keeps_full_output_and_adds_no_truncation_note(self) -> None:
        result = SubprocessRunner().run(
            (sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)"),
            Path(tempfile.gettempdir()),
            30.0,
        )

        self.assertEqual(result.status, ExecutionStatus.COMPLETED)
        self.assertIn("out", result.stdout)
        self.assertIn("err", result.stderr)
        self.assertNotIn("may be incomplete", result.stderr)


if __name__ == "__main__":
    unittest.main()
