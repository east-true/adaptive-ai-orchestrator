import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.core.domain import EvaluatorRole, EvaluatorSpec, EvaluatorStatus, ExecutionStatus, Task, VerificationStatus
from adaptive_orchestrator.execution.process_runner import ProcessResult
from adaptive_orchestrator.execution.verification import CommandVerifier


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

        _, evaluations = CommandVerifier(("pytest",)).verify_with_evaluations(
            Task("t", "o"), ExecutionStatus.COMPLETED, Path("/tmp"), ScriptedRunner(runner.results)
        )
        self.assertEqual([item.role for item in evaluations], [EvaluatorRole.RELIABILITY, EvaluatorRole.CONSTRAINT])
        self.assertTrue(all(item.observed for item in evaluations))
        self.assertNotIn(EvaluatorRole.QUALITY, [item.role for item in evaluations])

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

        _, evaluations = verifier.verify_with_evaluations(Task("t", "o"), ExecutionStatus.FAILED, Path("/tmp"), runner)
        self.assertTrue(evaluations[0].observed)
        self.assertEqual(evaluations[0].role, EvaluatorRole.RELIABILITY)
        self.assertTrue(all(not item.observed for item in evaluations[1:]))

    def test_quality_evaluator_records_role_score_version_and_protected_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            artifact = root / "hidden-evaluator.py"
            artifact.write_text("# held-out evaluator\n")
            artifact.chmod(0o444)
            spec = EvaluatorSpec(
                "quality-hidden-test",
                "v1",
                EvaluatorRole.QUALITY,
                "task objective",
                ("python3", str(artifact)),
                evidence_scope="held-out acceptance test",
                artifact_paths=(str(artifact),),
            )
            runner = ScriptedRunner({"python3": ProcessResult(("python3", str(artifact)), ExecutionStatus.COMPLETED, "pass", "", 0, 7)})
            verifier = CommandVerifier(evaluator_specs=(spec,))

            verification, evaluations = verifier.verify_with_evaluations(Task("t", "o"), ExecutionStatus.COMPLETED, workspace, runner)

            quality = evaluations[1]
            self.assertEqual(verification.status, VerificationStatus.PASSED)
            self.assertEqual(quality.role, EvaluatorRole.QUALITY)
            self.assertEqual(quality.status, EvaluatorStatus.PASSED)
            self.assertTrue(quality.observed)
            self.assertEqual(quality.score, 1.0)
            self.assertEqual(quality.artifact_hash_expected, quality.artifact_hash_before)
            self.assertEqual(quality.artifact_hash_before, quality.artifact_hash_after)
            self.assertTrue(quality.artifact_integrity_verified)

    def test_quality_evaluator_rejects_agent_writeable_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            artifact = workspace / "agent-test.py"
            artifact.write_text("# agent controlled\n")
            artifact.chmod(0o444)
            spec = EvaluatorSpec(
                "quality-agent-test",
                "v1",
                EvaluatorRole.QUALITY,
                "task objective",
                ("python3", str(artifact)),
                artifact_paths=(str(artifact),),
            )
            runner = ScriptedRunner({})

            verification, evaluations = CommandVerifier(evaluator_specs=(spec,)).verify_with_evaluations(
                Task("t", "o"), ExecutionStatus.COMPLETED, workspace, runner
            )

            self.assertEqual(verification.status, VerificationStatus.FAILED)
            self.assertEqual(evaluations[1].status, EvaluatorStatus.ERROR)
            self.assertFalse(evaluations[1].observed)
            self.assertIn("outside", evaluations[1].stderr or "")
            self.assertEqual(runner.calls, [])

    def test_quality_evaluator_detects_artifact_mutation_during_evaluation(self) -> None:
        class MutatingRunner:
            def __init__(self, artifact: Path) -> None:
                self.artifact = artifact

            def run(self, command, cwd, timeout_seconds):
                self.artifact.chmod(0o644)
                self.artifact.write_text("changed\n")
                self.artifact.chmod(0o444)
                return ProcessResult(command, ExecutionStatus.COMPLETED, "pass", "", 0, 2)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            artifact = root / "hidden-evaluator.py"
            artifact.write_text("original\n")
            artifact.chmod(0o444)
            spec = EvaluatorSpec(
                "quality-hidden-test",
                "v1",
                EvaluatorRole.QUALITY,
                "task objective",
                ("python3", str(artifact)),
                artifact_paths=(str(artifact),),
            )

            verification, evaluations = CommandVerifier(evaluator_specs=(spec,)).verify_with_evaluations(
                Task("t", "o"), ExecutionStatus.COMPLETED, workspace, MutatingRunner(artifact)
            )

            self.assertEqual(verification.status, VerificationStatus.FAILED)
            self.assertEqual(evaluations[1].status, EvaluatorStatus.ERROR)
            self.assertTrue(evaluations[1].observed)
            self.assertFalse(evaluations[1].artifact_integrity_verified)
            self.assertIsNone(evaluations[1].score)


if __name__ == "__main__":
    unittest.main()
