import sys
import tempfile
import time
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.core.domain import ExecutionStatus
from adaptive_orchestrator.execution.process_runner import SubprocessRunner


class SubprocessRunnerTests(unittest.TestCase):
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
        timestamps: list[float] = []

        def on_output_line(line: str) -> None:
            timestamps.append(time.monotonic())
            lines.append(line)

        with tempfile.TemporaryDirectory() as directory:
            runner = SubprocessRunner(on_output_line=on_output_line)
            result = runner.run(
                [
                    sys.executable,
                    "-c",
                    "import time\nfor i in range(3):\n print(i, flush=True)\n time.sleep(0.2)",
                ],
                Path(directory),
                None,
            )

        self.assertEqual(result.status, ExecutionStatus.COMPLETED)
        self.assertEqual(lines, ["0\n", "1\n", "2\n"])
        self.assertEqual(result.stdout, "0\n1\n2\n")
        self.assertGreater(timestamps[1] - timestamps[0], 0.1)
        self.assertGreater(timestamps[2] - timestamps[1], 0.1)

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

    def test_interrupt_kills_and_reaps_child_before_reraising(self) -> None:
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
        with tempfile.TemporaryDirectory() as directory, patch("adaptive_orchestrator.execution.process_runner.subprocess.Popen", return_value=process):
            with self.assertRaises(KeyboardInterrupt):
                SubprocessRunner().run(("agent",), Path(directory), None)

        self.assertTrue(process.killed)
        self.assertEqual(process.wait_calls, 2)


if __name__ == "__main__":
    unittest.main()
