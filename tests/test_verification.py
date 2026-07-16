import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.domain import ExecutionStatus, Task, VerificationStatus
from adaptive_orchestrator.process_runner import ProcessResult
from adaptive_orchestrator.verification import CommandVerifier


class ScriptedRunner:
    def __init__(self, results: dict[str, ProcessResult]) -> None:
        self.results = results
        self.calls: list[tuple[str, ...]] = []

    def run(self, command, cwd, timeout_seconds):
        self.calls.append(tuple(command))
        return self.results[command[0]]


class CommandVerifierTests(unittest.TestCase):
    def test_single_command_behaves_as_before(self) -> None:
        runner = ScriptedRunner({"pytest": ProcessResult(("pytest",), ExecutionStatus.COMPLETED, "3 passed", "", 0, 10)})
        result = CommandVerifier(("pytest",)).verify(Task("t", "o"), ExecutionStatus.COMPLETED, Path("/tmp"), runner)
        self.assertEqual(result.status, VerificationStatus.PASSED)
        self.assertEqual(len(runner.calls), 1)

    def test_all_commands_run_and_worst_status_wins(self) -> None:
        runner = ScriptedRunner({
            "pytest": ProcessResult(("pytest",), ExecutionStatus.COMPLETED, "3 passed", "", 0, 10),
            "ruff": ProcessResult(("ruff",), ExecutionStatus.FAILED, "", "2 lint errors", 1, 3),
            "mypy": ProcessResult(("mypy",), ExecutionStatus.COMPLETED, "no issues", "", 0, 4),
        })
        verifier = CommandVerifier(("pytest",), additional_commands=(("ruff",), ("mypy",)))
        result = verifier.verify(Task("t", "o"), ExecutionStatus.COMPLETED, Path("/tmp"), runner)

        self.assertEqual(result.status, VerificationStatus.FAILED)
        self.assertEqual(len(runner.calls), 3)
        self.assertIn("3 passed", result.stdout)
        self.assertIn("no issues", result.stdout)
        self.assertIn("2 lint errors", result.stderr)

    def test_skipped_when_execution_failed_even_with_commands_configured(self) -> None:
        runner = ScriptedRunner({})
        verifier = CommandVerifier(("pytest",), additional_commands=(("ruff",),))
        result = verifier.verify(Task("t", "o"), ExecutionStatus.FAILED, Path("/tmp"), runner)
        self.assertEqual(result.status, VerificationStatus.SKIPPED)
        self.assertEqual(runner.calls, [])


if __name__ == "__main__":
    unittest.main()
