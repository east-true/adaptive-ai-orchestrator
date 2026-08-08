import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.interfaces import cli
from adaptive_orchestrator.infrastructure.configuration import ProjectConfig, config_path
from adaptive_orchestrator.core.domain import (
    Capability,
    EvaluatorRole,
    ExecutionRecord,
    ExecutionStatus,
    MemoryEntryType,
    Priority,
    Task,
    VerificationResult,
    VerificationStatus,
)
from adaptive_orchestrator.infrastructure.events import JsonlEventStore, LifecycleEventType
from adaptive_orchestrator.routing.state import LifecycleRecorder, RoutingStateStore
from adaptive_orchestrator.orchestration.planning import ExecutionPlan



def _stub_plan() -> ExecutionPlan:
    return ExecutionPlan(Task("Do the thing", "Thing is done"), "codex", "stub")


def _completed_record(execution_id: str) -> ExecutionRecord:
    """A minimal successful record for exercising CLI output formatting."""
    return ExecutionRecord(
        task=Task("Do the thing", "Thing is done"),
        agent_id="codex",
        prompt="prompt",
        command=(),
        status=ExecutionStatus.COMPLETED,
        result="done",
        error=None,
        exit_code=0,
        duration_ms=1.0,
        verification=VerificationResult(VerificationStatus.SKIPPED, (), ""),
        execution_id=execution_id,
    )


class BuildWorkflowTests(unittest.TestCase):
    def test_configured_agents_apply_model_options_and_derive_registry_ids(self) -> None:
        args = argparse.Namespace(
            claude_model="opus",
            codex_model="gpt-5.5",
            codex_reasoning_effort="high",
        )

        claude, codex = cli._configured_agents(args)

        self.assertEqual(claude.agent_id, "claude-code:opus")
        self.assertEqual(codex.agent_id, "codex:gpt-5.5:high")
        self.assertIn(("--model", "opus"), tuple(zip(claude.build_command("task", Path(".")), claude.build_command("task", Path("."))[1:])))
        self.assertIn(("-m", "gpt-5.5"), tuple(zip(codex.build_command("task", Path(".")), codex.build_command("task", Path("."))[1:])))
        self.assertIn(("-c", "model_reasoning_effort=high"), tuple(zip(codex.build_command("task", Path(".")), codex.build_command("task", Path("."))[1:])))

    def test_model_options_are_available_on_routed_commands(self) -> None:
        parser = cli.build_parser()
        cases = (
            ["run", "--description", "Do it", "--objective", "Done"],
            ["run-plan", "plan.json"],
            ["plan", "generate", "Make a plan"],
            ["retry", "exec-1", "--agent", "auto"],
        )
        for argv in cases:
            with self.subTest(command=argv):
                args = parser.parse_args([*argv, "--claude-model", "opus", "--codex-model", "gpt-5.5", "--codex-reasoning-effort", "high"])
                self.assertEqual(args.claude_model, "opus")
                self.assertEqual(args.codex_model, "gpt-5.5")
                self.assertEqual(args.codex_reasoning_effort, "high")

    def test_typed_evaluator_flags_are_available_on_routed_commands(self) -> None:
        parser = cli.build_parser()
        for argv in (["run", "--description", "Do it", "--objective", "Done"], ["run-plan", "plan.json"]):
            with self.subTest(command=argv):
                args = parser.parse_args([
                    *argv,
                    "--verify-command", "ruff check .",
                    "--quality-evaluator-command", "python3 /protected/acceptance.py",
                    "--quality-evaluator-artifact", "/protected/acceptance.py",
                ])
                self.assertEqual(args.verify_command, ["ruff check ."])
                self.assertEqual(args.quality_evaluator_command, ["python3 /protected/acceptance.py"])
                self.assertEqual(args.quality_evaluator_artifact, [Path("/protected/acceptance.py")])

    def test_phase_one_routing_flags_are_available_on_routed_commands(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args([
            "run", "--description", "Do it", "--objective", "Done",
            "--routing-policy", "static",
            "--routing-baseline-agent", "codex",
            "--routing-shadow",
            "--routing-seed", "17",
            "--environment-epoch", "codex-0.145",
        ])
        self.assertEqual(args.routing_policy, "static")
        self.assertEqual(args.routing_baseline_agent, "codex")
        self.assertTrue(args.routing_shadow)
        self.assertEqual(args.routing_seed, 17)
        self.assertEqual(args.environment_epoch, "codex-0.145")

    def test_verbose_flag_installs_streaming_runner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            args = type(
                "Args",
                (),
                {
                    "command": "run",
                    "agent": "codex",
                    "include_git_diff": False,
                    "verify_command": [],
                    "verify_time_limit": None,
                    "no_escalation": True,
                    "escalation_risk_threshold": 3,
                    "escalation_uncertainty_threshold": 3,
                    "escalation_difficulty_threshold": 4,
                    "verbose": True,
                    "control_state_dir": root / "control",
                },
            )()

            with patch.object(cli, "SubprocessRunner") as runner_ctor:
                runner_instance = runner_ctor.return_value
                workflow = cli._build_workflow(args, workspace)

        runner_ctor.assert_called_once()
        self.assertIs(workflow._kernel.runner, runner_instance)
        self.assertTrue(callable(runner_ctor.call_args.args[0]))

    def test_verbose_stream_is_labelled_with_the_agent_actually_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            args = type(
                "Args",
                (),
                {
                    "command": "retry",
                    # `retry` keeps the sentinel here until the record names one.
                    "agent": "same",
                    "include_git_diff": False,
                    "verify_command": [],
                    "verify_time_limit": None,
                    "no_escalation": True,
                    "escalation_risk_threshold": 3,
                    "escalation_uncertainty_threshold": 3,
                    "escalation_difficulty_threshold": 4,
                    "verbose": True,
                    "control_state_dir": root / "control",
                },
            )()

            with patch.object(cli, "SubprocessRunner") as runner_ctor:
                cli._build_workflow(args, workspace, "codex")

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                runner_ctor.call_args.args[0]("line\n")

        self.assertIn("[retry:codex]", stderr.getvalue())
        self.assertNotIn("same", stderr.getvalue())


class ProjectConfigCliTests(unittest.TestCase):
    def test_project_config_supplies_defaults_and_cli_can_override_them(self) -> None:
        config = ProjectConfig(
            agent="claude-code:opus",
            claude_model="opus",
            time_limit_seconds=90,
            verbose=True,
            verify_commands=("python3 -m unittest",),
            escalation_enabled=False,
        )
        parser = cli.build_parser(config)

        defaults = parser.parse_args(["run", "--description", "Do it", "--objective", "Done"])
        self.assertEqual(defaults.agent, "claude-code:opus")
        self.assertEqual(defaults.time_limit, 90)
        self.assertTrue(defaults.verbose)
        self.assertEqual(defaults.verify_command, ["python3 -m unittest"])
        self.assertTrue(defaults.no_escalation)

        overridden = parser.parse_args([
            "run", "--description", "Do it", "--objective", "Done",
            "--agent", "codex", "--time-limit", "30", "--no-verbose", "--escalation",
        ])
        self.assertEqual(overridden.agent, "codex")
        self.assertEqual(overridden.time_limit, 30)
        self.assertFalse(overridden.verbose)
        self.assertFalse(overridden.no_escalation)

    def test_cli_can_clear_configured_time_limit_and_verification_commands(self) -> None:
        config = ProjectConfig(
            time_limit_seconds=90,
            verify_commands=("configured-check",),
        )
        parser = cli.build_parser(config)

        cleared = parser.parse_args([
            "run",
            "--description",
            "Do it",
            "--objective",
            "Done",
            "--no-time-limit",
            "--clear-verify-commands",
        ])
        self.assertIsNone(cleared.time_limit)
        self.assertEqual(cleared.verify_command, [])

        overridden_later = parser.parse_args([
            "run",
            "--description",
            "Do it",
            "--objective",
            "Done",
            "--no-time-limit",
            "--time-limit",
            "30",
            "--clear-verify-commands",
            "--verify-command",
            "explicit-check",
        ])
        self.assertEqual(overridden_later.time_limit, 30)
        self.assertEqual(overridden_later.verify_command, ["explicit-check"])

    def test_configured_commands_reject_abbreviated_workspace_options(self) -> None:
        parser = cli.build_parser()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
            parser.parse_args([
                "run",
                "--work",
                "/override",
                "--description",
                "Do it",
                "--objective",
                "Done",
            ])
        self.assertIn("unrecognized arguments", stderr.getvalue())

    def test_config_for_argv_uses_explicit_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            path = config_path(workspace)
            path.parent.mkdir()
            path.write_text(json.dumps({"version": 1, "agent": "codex"}), encoding="utf-8")
            config = cli._config_for_argv(["run", "--workspace", str(workspace)])
        self.assertEqual(config.agent, "codex")

    def test_config_for_argv_uses_last_repeated_workspace_like_argparse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first"
            second = root / "second"
            for workspace, agent in ((first, "claude-code"), (second, "codex")):
                path = config_path(workspace)
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps({"version": 1, "agent": agent}), encoding="utf-8")

            argv = [
                "run",
                "--workspace",
                str(first),
                f"--workspace={second}",
                "--description",
                "Do it",
                "--objective",
                "Done",
            ]
            config = cli._config_for_argv(argv)
            args = cli.build_parser(config).parse_args(argv)

        self.assertEqual(config.agent, "codex")
        self.assertEqual(args.workspace, second)

    def test_config_for_argv_ignores_workspace_text_after_option_terminator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first"
            second = root / "second"
            ignored = root / "ignored"
            for workspace, agent in (
                (first, "claude-code"),
                (second, "codex"),
                (ignored, "claude-code:ignored"),
            ):
                path = config_path(workspace)
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps({"version": 1, "agent": agent}), encoding="utf-8")

            argv = [
                "plan",
                "generate",
                "--workspace",
                str(first),
                f"--workspace={second}",
                "--",
                f"--workspace={ignored}",
            ]
            config = cli._config_for_argv(argv)
            args = cli.build_parser(config).parse_args(argv)

        self.assertEqual(config.agent, "codex")
        self.assertEqual(args.workspace, second)
        self.assertEqual(args.request, f"--workspace={ignored}")

    def test_init_dispatch_writes_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = cli.main(["init", "--workspace", directory])
            self.assertEqual(exit_code, 0)
            self.assertTrue(config_path(Path(directory)).is_file())
            self.assertIn("Project config written", stdout.getvalue())

    def test_show_and_report_dispatch_render_recorded_execution(self) -> None:
        record = {
            "execution_id": "exec-1",
            "attempt_id": "attempt-1",
            "task": {"description": "Fix it", "objective": "It works"},
            "agent_id": "codex",
            "status": "completed",
            "duration_ms": 10,
            "verification": {"status": "passed"},
        }
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            log = workspace / ".orchestrator" / "executions.jsonl"
            log.parent.mkdir()
            log.write_text(json.dumps(record), encoding="utf-8")

            show_output = io.StringIO()
            with contextlib.redirect_stdout(show_output):
                show_exit = cli.main(["show", "exec-1", "--workspace", directory])
            report_path = workspace / "report.md"
            report_output = io.StringIO()
            with contextlib.redirect_stdout(report_output):
                report_exit = cli.main(["report", "exec-1", "--workspace", directory, "--output", str(report_path)])

            self.assertEqual(show_exit, 0)
            self.assertIn("Status: completed", show_output.getvalue())
            self.assertEqual(report_exit, 0)
            self.assertIn("# Execution exec-1", report_path.read_text(encoding="utf-8"))

    def test_report_refuses_to_replace_existing_file_without_force(self) -> None:
        record = {
            "execution_id": "exec-1",
            "attempt_id": "attempt-1",
            "task": {"description": "Fix it", "objective": "It works"},
            "agent_id": "codex",
            "status": "completed",
        }
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            log = workspace / ".orchestrator" / "executions.jsonl"
            log.parent.mkdir()
            log.write_text(json.dumps(record), encoding="utf-8")
            output = workspace / "report.md"
            output.write_text("keep", encoding="utf-8")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = cli.main(["report", "exec-1", "--workspace", directory, "--output", str(output)])
            self.assertEqual(exit_code, 1)
            self.assertEqual(output.read_text(encoding="utf-8"), "keep")
            self.assertIn("already exists", stderr.getvalue())

    def test_report_resolves_relative_output_from_final_workspace(self) -> None:
        record = {
            "execution_id": "exec-1",
            "attempt_id": "attempt-1",
            "task": {"description": "Fix it", "objective": "It works"},
            "agent_id": "codex",
            "status": "completed",
            "verification": {"status": "passed"},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first"
            workspace = root / "final"
            first.mkdir()
            log = workspace / ".orchestrator" / "executions.jsonl"
            log.parent.mkdir(parents=True)
            log.write_text(json.dumps(record), encoding="utf-8")
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = cli.main([
                    "report",
                    "exec-1",
                    "--workspace",
                    str(first),
                    "--workspace",
                    str(workspace),
                    "--output",
                    "reports/result.md",
                ])

            output = workspace / "reports" / "result.md"
            self.assertEqual(exit_code, 0)
            self.assertTrue(output.is_file())
            self.assertIn("# Execution exec-1", output.read_text(encoding="utf-8"))
            self.assertIn(str(output.resolve()), stdout.getvalue())

    def test_quality_evaluator_specs_are_versioned_and_protected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            artifact = root / "acceptance.py"
            artifact.write_text("# hidden acceptance evaluator\n")
            artifact.chmod(0o444)
            args = type("Args", (), {
                "quality_evaluator_command": [f"python3 {artifact}"],
                "quality_evaluator_artifact": [artifact],
                "quality_evaluator_time_limit": 12,
            })()

            specs = cli._quality_evaluator_specs(args, workspace)

            self.assertEqual(len(specs), 1)
            self.assertEqual(specs[0].role, EvaluatorRole.QUALITY)
            self.assertTrue(specs[0].version.startswith("sha256:"))
            self.assertEqual(specs[0].timeout_seconds, 12)
            self.assertEqual(specs[0].artifact_paths, (str(artifact),))

    def test_quality_evaluator_requires_external_read_only_referenced_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            artifact = root / "acceptance.py"
            artifact.write_text("# evaluator\n")
            base = {
                "quality_evaluator_command": ["python3 -V"],
                "quality_evaluator_artifact": [artifact],
                "quality_evaluator_time_limit": None,
            }
            with self.assertRaisesRegex(ValueError, "read-only"):
                cli._quality_evaluator_specs(type("Args", (), base)(), workspace)

            artifact.chmod(0o444)
            with self.assertRaisesRegex(ValueError, "directly reference"):
                cli._quality_evaluator_specs(type("Args", (), base)(), workspace)


class TaskFromSpecTests(unittest.TestCase):
    def test_required_fields_only(self) -> None:
        task = cli._task_from_spec({"description": "Do the thing", "objective": "Get it done"})
        self.assertEqual(task.description, "Do the thing")
        self.assertEqual(task.objective, "Get it done")
        self.assertEqual(task.required_capabilities, ())
        self.assertEqual(task.priority, Priority.NORMAL)
        self.assertIsNone(task.cost_limit_usd)

    def test_optional_fields_are_applied(self) -> None:
        task = cli._task_from_spec({
            "description": "Fix it",
            "objective": "No regressions",
            "constraints": ["Read-only"],
            "capabilities": ["debugging"],
            "priority": "high",
            "time_limit_seconds": 120,
            "cost_limit_usd": 2.5,
            "task_id": "task-login-fix",
        })
        self.assertEqual(task.constraints, ("Read-only",))
        self.assertEqual(task.required_capabilities, (Capability.DEBUGGING,))
        self.assertEqual(task.priority, Priority.HIGH)
        self.assertEqual(task.time_limit_seconds, 120)
        self.assertEqual(task.cost_limit_usd, 2.5)
        self.assertEqual(task.task_id, "task-login-fix")

    def test_cost_limit_preserves_zero_and_rejects_negative_values(self) -> None:
        zero = cli._task_from_spec({"description": "Fix it", "objective": "Done", "cost_limit_usd": 0})
        self.assertEqual(zero.cost_limit_usd, 0)
        with self.assertRaisesRegex(ValueError, "cost_limit_usd cannot be negative"):
            cli._task_from_spec({"description": "Fix it", "objective": "Done", "cost_limit_usd": -0.01})


class LoadPlanTests(unittest.TestCase):
    def test_loads_ordered_tasks_from_json_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(json.dumps([
                {"description": "Step one", "objective": "First"},
                {"description": "Step two", "objective": "Second", "cost_limit_usd": 1.25},
            ]))
            tasks = cli._load_plan(path)
            self.assertEqual([t.description for t in tasks], ["Step one", "Step two"])
            self.assertEqual([task.cost_limit_usd for task in tasks], [None, 1.25])

    def test_negative_cost_limit_fails_plan_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(json.dumps([
                {"description": "Step one", "objective": "First", "cost_limit_usd": -0.5},
            ]))
            valid, error = cli._validate_plan_file(path)
            self.assertFalse(valid)
            self.assertIn("cost_limit_usd cannot be negative", error or "")

    def test_rejects_empty_or_non_list_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(json.dumps({"description": "not a list"}))
            with self.assertRaises(ValueError):
                cli._load_plan(path)

            path.write_text(json.dumps([]))
            with self.assertRaises(ValueError):
                cli._load_plan(path)


class MainPlanValidateDispatchTests(unittest.TestCase):
    # Regression test: `plan validate`'s subparser has no --workspace, but main() used to
    # unconditionally resolve args.workspace before dispatching on args.command, so every real
    # `plan validate` invocation crashed with AttributeError - invisible to tests that only
    # called the pure _validate_plan_file helper directly instead of going through main().
    def test_plan_validate_runs_through_main_without_a_workspace_argument(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(json.dumps([{"description": "Step one", "objective": "First"}]))
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = cli.main(["plan", "validate", str(path)])
            self.assertEqual(exit_code, 0)
            self.assertIn("1 task(s)", stdout.getvalue())

    def test_plan_validate_reports_failure_through_main(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text("{not-json")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = cli.main(["plan", "validate", str(path)])
            self.assertEqual(exit_code, 1)
            self.assertIn("Invalid plan file", stderr.getvalue())


class ReplayDispatchTests(unittest.TestCase):
    def test_replay_validates_and_rebuilds_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            control = root / "control"
            store = JsonlEventStore(control / "events.jsonl")
            state_path = control / "routing-state.json"
            seed = LifecycleRecorder(store, RoutingStateStore(state_path))
            common = {"execution_id": "execution", "task_id": "task", "attempt_id": "attempt"}
            seed.record(
                LifecycleEventType.SELECTION_MADE,
                payload={
                    "selected_agent": "codex",
                    "eligible_candidates": ["codex"],
                    "ineligible_reasons": {},
                    "candidate_probabilities": {"codex": 1.0},
                    "selected_probability": 1.0,
                },
                **common,
            )
            seed.record(LifecycleEventType.EXECUTION_STARTED, **common)
            seed.record(LifecycleEventType.EXECUTION_TERMINAL, payload={"status": "completed"}, **common)
            seed.record(LifecycleEventType.OUTCOME_FINALIZED, payload={"status": "completed"}, **common)
            state_path.unlink()
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = cli.main([
                    "replay", "--workspace", str(workspace),
                    "--control-state-dir", str(control), "--rebuild-state",
                ])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["event_count"], 4)
            self.assertEqual(payload["attempt_count"], 1)
            self.assertEqual(payload["finalized_attempt_count"], 1)
            self.assertEqual(payload["incomplete_attempt_count"], 0)
            self.assertEqual(payload["attempt_status_counts"], {"finalized": 1})
            self.assertTrue(payload["state_rebuilt"])
            self.assertFalse(payload["legacy_execution_log"]["counterfactual_supported"])
            self.assertTrue((control / "routing-state.json").exists())

    def test_rebuild_state_does_not_reconcile_incomplete_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            control = root / "control"
            store = JsonlEventStore(control / "events.jsonl")
            state_path = control / "routing-state.json"
            seed = LifecycleRecorder(store, RoutingStateStore(state_path))
            common = {"execution_id": "execution", "task_id": "task", "attempt_id": "attempt"}
            seed.record(
                LifecycleEventType.SELECTION_MADE,
                payload={
                    "selected_agent": "codex",
                    "eligible_candidates": ["codex"],
                    "ineligible_reasons": {},
                    "candidate_probabilities": {"codex": 1.0},
                    "selected_probability": 1.0,
                },
                **common,
            )
            seed.record(LifecycleEventType.EXECUTION_STARTED, **common)
            state_path.unlink()
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = cli.main([
                    "replay", "--workspace", str(workspace),
                    "--control-state-dir", str(control), "--rebuild-state",
                ])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["reconciled_count"], 0)
            self.assertEqual(payload["attempt_status_counts"], {"started": 1})
            self.assertEqual(len(store.read()), 2)
            materialized = RoutingStateStore(control / "routing-state.json").read()
            self.assertIsNotNone(materialized)
            self.assertEqual(
                materialized["executions"]["execution"]["attempts"]["attempt"]["status"],
                "started",
            )

    def test_rebuild_state_cannot_overwrite_a_concurrent_recorder_projection(self) -> None:
        class SignalingAppendStore(JsonlEventStore):
            def __init__(self, path: Path, append_entered: threading.Event) -> None:
                super().__init__(path)
                self.append_entered = append_entered

            def _append_validated(self, *args, **kwargs):
                self.append_entered.set()
                return super()._append_validated(*args, **kwargs)

        class BlockingReadStore(JsonlEventStore):
            def __init__(self, path: Path, entered: threading.Event, release: threading.Event) -> None:
                super().__init__(path)
                self.entered = entered
                self.release = release

            def read(self):
                events = super().read()
                self.entered.set()
                if not self.release.wait(5):
                    raise RuntimeError("timed out waiting to release CLI event snapshot")
                return events

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            control = root / "control"
            event_path = control / "events.jsonl"
            state_path = control / "routing-state.json"
            append_entered = threading.Event()
            recorder = LifecycleRecorder(
                SignalingAppendStore(event_path, append_entered),
                RoutingStateStore(state_path),
            )
            selection = {
                "selected_agent": "codex",
                "eligible_candidates": ["codex"],
                "ineligible_reasons": {},
                "candidate_probabilities": {"codex": 1.0},
                "selected_probability": 1.0,
            }
            recorder.record(
                LifecycleEventType.SELECTION_MADE,
                execution_id="execution-a",
                task_id="task-a",
                attempt_id="attempt-a",
                payload=selection,
            )
            append_entered.clear()

            entered = threading.Event()
            release = threading.Event()
            writer_started = threading.Event()
            writer_finished = threading.Event()
            errors: list[BaseException] = []
            exit_codes: list[int] = []
            stdout = io.StringIO()
            blocking_events = BlockingReadStore(event_path, entered, release)

            def rebuild_from_cli() -> None:
                try:
                    with contextlib.redirect_stdout(stdout):
                        exit_codes.append(cli.main([
                            "replay", "--workspace", str(workspace),
                            "--control-state-dir", str(control), "--rebuild-state",
                        ]))
                except BaseException as exc:
                    errors.append(exc)

            def record_new_execution() -> None:
                try:
                    writer_started.set()
                    recorder.record(
                        LifecycleEventType.SELECTION_MADE,
                        execution_id="execution-b",
                        task_id="task-b",
                        attempt_id="attempt-b",
                        payload=selection,
                    )
                except BaseException as exc:
                    errors.append(exc)
                finally:
                    writer_finished.set()

            with patch.object(cli, "JsonlEventStore", return_value=blocking_events):
                rebuild_thread = threading.Thread(target=rebuild_from_cli)
                writer_thread = threading.Thread(target=record_new_execution)
                rebuild_thread.start()
                rebuild_entered = entered.wait(5)
                if rebuild_entered:
                    writer_thread.start()
                    writer_did_start = writer_started.wait(5)
                    append_was_blocked = not append_entered.wait(0.5)
                else:
                    writer_did_start = False
                    append_was_blocked = False
                release.set()
                rebuild_thread.join(5)
                if writer_thread.ident is not None:
                    writer_thread.join(5)

            self.assertTrue(rebuild_entered)
            self.assertTrue(writer_did_start)
            self.assertTrue(append_was_blocked)
            self.assertFalse(rebuild_thread.is_alive())
            self.assertFalse(writer_thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(exit_codes, [0])
            self.assertTrue(append_entered.is_set())
            self.assertTrue(writer_finished.is_set())
            event_execution_ids = {
                event.execution_id for event in JsonlEventStore(event_path).read()
            }
            materialized = RoutingStateStore(state_path).read()
            self.assertIsNotNone(materialized)
            self.assertEqual(set(materialized["executions"]), event_execution_ids)

    def test_replay_reports_invalid_event_log_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            control = root / "control"
            event_path = control / "events.jsonl"
            event_path.parent.mkdir()
            event_path.write_text("not-json\n")
            stderr = io.StringIO()

            with contextlib.redirect_stderr(stderr):
                exit_code = cli.main(["replay", "--workspace", str(workspace), "--control-state-dir", str(control)])

            self.assertEqual(exit_code, 1)
            self.assertIn("Replay failed", stderr.getvalue())

    def test_replay_rejects_control_directory_inside_workspace_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            stderr = io.StringIO()

            with contextlib.redirect_stderr(stderr):
                exit_code = cli.main([
                    "replay",
                    "--workspace", str(workspace),
                    "--control-state-dir", str(workspace / ".orchestrator"),
                ])

            self.assertEqual(exit_code, 1)
            self.assertIn("Replay failed", stderr.getvalue())


class PairedDispatchTests(unittest.TestCase):
    def test_paired_plan_arguments_are_explicit(self) -> None:
        args = cli.build_parser().parse_args([
            "paired", "plan", "manifest.json", "--workspace-root", "/isolated/workspaces",
        ])
        self.assertEqual(args.paired_command, "plan")
        self.assertEqual(args.workspace_root, Path("/isolated/workspaces"))

    def test_paired_dry_run_arguments_are_explicit(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args([
            "paired", "dry-run", "manifest.json",
            "--source-repository", "/repo",
            "--workspace-root", "/isolated/workspaces",
        ])

        self.assertEqual(args.paired_command, "dry-run")
        self.assertEqual(args.manifest, Path("manifest.json"))
        self.assertEqual(args.source_repository, Path("/repo"))
        self.assertEqual(args.workspace_root, Path("/isolated/workspaces"))

    def test_paired_run_requires_an_explicit_execution_gate(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args([
            "paired", "run", "manifest.json",
            "--source-repository", "/repo",
            "--workspace-root", "/isolated/workspaces",
            "--control-state-dir", "/protected/control",
            "--confirm-agent-execution",
        ])

        self.assertEqual(args.paired_command, "run")
        self.assertEqual(args.control_state_dir, Path("/protected/control"))
        self.assertTrue(args.confirm_agent_execution)

    def test_paired_resume_reuses_explicit_run_directories(self) -> None:
        args = cli.build_parser().parse_args([
            "paired", "resume", "manifest.json",
            "--source-repository", "/repo",
            "--workspace-root", "/isolated/workspaces",
            "--control-state-dir", "/protected/control",
            "--confirm-agent-execution",
        ])

        self.assertEqual(args.paired_command, "resume")
        self.assertEqual(args.workspace_root, Path("/isolated/workspaces"))
        self.assertEqual(args.control_state_dir, Path("/protected/control"))
        self.assertTrue(args.confirm_agent_execution)

    def test_paired_missing_manifest_fails_without_traceback(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = cli.main(["paired", "validate", "/missing/paired-manifest.json"])

        self.assertEqual(exit_code, 1)
        self.assertIn("Paired experiment failed", stderr.getvalue())


class WorkflowConfigurationDispatchTests(unittest.TestCase):
    def test_unknown_model_variant_fails_cleanly_before_agent_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            control = root / "control"
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = cli.main([
                    "run",
                    "--workspace", str(workspace),
                    "--control-state-dir", str(control),
                    "--agent", "codex:old",
                    "--codex-model", "new",
                    "--description", "Do work",
                    "--objective", "Done",
                ])

            self.assertEqual(exit_code, 2)
            self.assertIn("Unknown agent: codex:old", stderr.getvalue())
            self.assertFalse(control.exists())

    def test_static_policy_without_baseline_fails_cleanly_before_agent_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = cli.main([
                    "run",
                    "--workspace", str(workspace),
                    "--control-state-dir", str(root / "control"),
                    "--description", "Do work",
                    "--objective", "Done",
                    "--routing-policy", "static",
                ])

            self.assertEqual(exit_code, 2)
            self.assertIn("requires --routing-baseline-agent", stderr.getvalue())

    def test_retry_unknown_original_agent_uses_clean_preflight_exit(self) -> None:
        record = {
            "execution_id": "exec-1",
            "attempt_id": "attempt-1",
            "task": {
                "description": "Do work",
                "objective": "Done",
                "cost_limit_usd": 1.5,
            },
            "agent_id": "codex:old",
            "status": "failed",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            log = workspace / ".orchestrator" / "executions.jsonl"
            log.parent.mkdir(parents=True)
            log.write_text(json.dumps(record), encoding="utf-8")
            control = root / "control"
            stderr = io.StringIO()

            with contextlib.redirect_stderr(stderr):
                exit_code = cli.main([
                    "retry",
                    "exec-1",
                    "--workspace",
                    str(workspace),
                    "--control-state-dir",
                    str(control),
                ])

            self.assertEqual(exit_code, 2)
            self.assertIn("Workflow configuration failed", stderr.getvalue())
            self.assertIn("Unknown agent: codex:old", stderr.getvalue())
            self.assertFalse(control.exists())


class WorkspaceRelativeDispatchTests(unittest.TestCase):
    def test_run_plan_resolves_relative_plan_from_final_workspace(self) -> None:
        class Workflow:
            tasks = None

            def run_plan(self, tasks, requested_agent, stop_on_failure=True):
                self.tasks = tasks
                return type("Result", (), {
                    "steps": (),
                    "stopped_early": False,
                    "succeeded": True,
                })()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first"
            workspace = root / "final"
            first.mkdir()
            plan_path = workspace / "plans" / "plan.json"
            plan_path.parent.mkdir(parents=True)
            plan_path.write_text(json.dumps([
                {"description": "From final workspace", "objective": "Done"},
            ]), encoding="utf-8")
            workflow = Workflow()

            with (
                patch.object(cli, "_build_workflow_for_cli", return_value=workflow),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                exit_code = cli.main([
                    "run-plan",
                    "--workspace",
                    str(first),
                    "--workspace",
                    str(workspace),
                    "plans/plan.json",
                ])

            self.assertEqual(exit_code, 0)
            self.assertEqual(workflow.tasks[0].description, "From final workspace")

    def test_fresh_workspace_lookup_suggests_running_a_task(self) -> None:
        for command in ("show", "report", "retry"):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    exit_code = cli.main([command, "#1", "--workspace", str(workspace)])

                self.assertEqual(exit_code, 1)
                self.assertIn("No task has run in this workspace yet", stderr.getvalue())
                self.assertIn(cli.PROGRAM_NAME, stderr.getvalue())

    def test_bad_identifier_with_existing_history_does_not_suggest_a_first_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            log = workspace / ".orchestrator" / "executions.jsonl"
            log.parent.mkdir(parents=True)
            log.write_text(
                json.dumps({"execution_id": "e1", "attempt_id": "a1", "agent_id": "codex"}) + "\n",
                encoding="utf-8",
            )
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = cli.main(["show", "nope", "--workspace", str(workspace)])

        self.assertEqual(exit_code, 1)
        self.assertIn("Show failed", stderr.getvalue())
        self.assertNotIn("No task has run in this workspace yet", stderr.getvalue())

    def test_empty_memory_search_explains_itself_without_breaking_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = cli.main(["memory", "search", "--workspace", str(workspace)])

            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(stdout.getvalue()), [])
            self.assertIn("no engineering memory has been recorded", stderr.getvalue())

            with contextlib.redirect_stdout(io.StringIO()):
                cli.main([
                    "memory", "record", "--workspace", str(workspace),
                    "--type", "trade_off", "--title", "T", "--summary", "S",
                ])
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                cli.main(["memory", "search", "--workspace", str(workspace), "--keyword", "zzz"])

            self.assertEqual(json.loads(stdout.getvalue()), [])
            self.assertIn("nothing matched --keyword", stderr.getvalue())

            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                cli.main(["memory", "search", "--workspace", str(workspace)])

            self.assertEqual(len(json.loads(stdout.getvalue())), 1)
            self.assertEqual(stderr.getvalue(), "")

    def test_memory_search_leaves_a_workspace_it_only_queried_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                exit_code = cli.main(["memory", "search", "--workspace", str(workspace)])

            self.assertEqual(exit_code, 0)
            self.assertEqual(list(workspace.iterdir()), [])

    def test_unwritable_memory_workspace_reports_one_line_instead_of_a_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            stderr = io.StringIO()
            with (
                patch.object(cli.EngineeringMemoryStore, "record", side_effect=PermissionError("denied")),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(stderr),
            ):
                exit_code = cli.main([
                    "memory", "record", "--workspace", str(workspace),
                    "--type", "trade_off", "--title", "T", "--summary", "S",
                ])

            self.assertEqual(exit_code, 1)
            self.assertIn("Memory record failed", stderr.getvalue())
            self.assertIn("denied", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())

    def test_version_reports_the_installed_console_script_name(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), self.assertRaises(SystemExit) as raised:
            cli.main(["--version"])

        self.assertEqual(raised.exception.code, 0)
        self.assertIn(cli.PROGRAM_NAME, stdout.getvalue())
        self.assertIn("kernel", stdout.getvalue())

    def test_usage_text_names_a_runnable_command_not_the_module_file(self) -> None:
        # Reached through `python3 -m adaptive_orchestrator.cli`, argparse would
        # otherwise report "cli.py", which is not a command anyone can run.
        with patch.object(sys, "argv", ["/somewhere/adaptive_orchestrator/cli.py"]):
            module_usage = cli.build_parser().format_usage()
        with patch.object(sys, "argv", [f"/usr/local/bin/{cli.PROGRAM_NAME}"]):
            script_usage = cli.build_parser().format_usage()

        self.assertIn(f"-m {cli.MODULE_ENTRY_POINT}", module_usage)
        self.assertNotIn("cli.py", module_usage)
        self.assertIn(cli.PROGRAM_NAME, script_usage)

    def test_summary_flag_renders_the_same_view_show_prints(self) -> None:
        class Workflow:
            def run(self, task, requested_agent):
                return _stub_plan(), _completed_record("exec-1")

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            log = workspace / ".orchestrator" / "executions.jsonl"
            log.parent.mkdir(parents=True)
            log.write_text(
                json.dumps({
                    "execution_id": "exec-1",
                    "attempt_id": "attempt-1",
                    "agent_id": "codex",
                    "status": "completed",
                    "task": {"description": "Do the thing"},
                }) + "\n",
                encoding="utf-8",
            )
            argv = [
                "run", "--workspace", str(workspace),
                "--description", "Do the thing", "--objective", "Thing is done",
            ]
            stdout = io.StringIO()
            with (
                patch.object(cli, "_build_workflow_for_cli", return_value=Workflow()),
                contextlib.redirect_stdout(stdout),
            ):
                cli.main([*argv, "--summary"])
            summary_output = stdout.getvalue()

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                cli.main(["show", "exec-1", "--workspace", str(workspace)])
            show_output = stdout.getvalue()

        self.assertEqual(summary_output.strip(), show_output.strip())
        self.assertIn("Execution: exec-1", summary_output)

    def test_default_output_stays_json_for_scripted_callers(self) -> None:
        class Workflow:
            def run(self, task, requested_agent):
                return _stub_plan(), _completed_record("exec-1")

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            stdout = io.StringIO()
            with (
                patch.object(cli, "_build_workflow_for_cli", return_value=Workflow()),
                contextlib.redirect_stdout(stdout),
            ):
                cli.main([
                    "run", "--workspace", str(workspace),
                    "--description", "d", "--objective", "o",
                ])

        self.assertEqual(set(json.loads(stdout.getvalue())), {"plan", "execution"})

    def test_summary_falls_back_to_json_when_the_execution_cannot_be_read(self) -> None:
        class Workflow:
            def run(self, task, requested_agent):
                return _stub_plan(), _completed_record("missing")

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            stdout = io.StringIO()
            with (
                patch.object(cli, "_build_workflow_for_cli", return_value=Workflow()),
                contextlib.redirect_stdout(stdout),
            ):
                cli.main([
                    "run", "--workspace", str(workspace),
                    "--description", "d", "--objective", "o", "--summary",
                ])

        self.assertEqual(set(json.loads(stdout.getvalue())), {"plan", "execution"})

    def test_failed_run_explains_itself_on_stderr_without_touching_stdout(self) -> None:
        failed = ExecutionRecord(
            task=Task("Do it", "Done"),
            agent_id="codex",
            prompt="p",
            command=(),
            status=ExecutionStatus.FAILED,
            result=None,
            error="boom: the agent could not do it",
            exit_code=3,
            duration_ms=1.0,
            verification=VerificationResult(VerificationStatus.SKIPPED, (), ""),
            execution_id="exec-9",
        )

        class Workflow:
            def run(self, task, requested_agent):
                return _stub_plan(), failed

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            stdout, stderr = io.StringIO(), io.StringIO()
            with (
                patch.object(cli, "_build_workflow_for_cli", return_value=Workflow()),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                exit_code = cli.main(["run", "--workspace", str(workspace), "--task", "Do it"])

        self.assertEqual(exit_code, 1)
        # stdout keeps its exact machine-readable contract.
        self.assertEqual(set(json.loads(stdout.getvalue())), {"plan", "execution"})
        reported = stderr.getvalue()
        self.assertIn("Run did not succeed", reported)
        self.assertIn("status=failed", reported)
        self.assertIn("boom: the agent could not do it", reported)
        self.assertIn("show exec-9", reported)

    def test_successful_run_says_nothing_on_stderr(self) -> None:
        class Workflow:
            def run(self, task, requested_agent):
                return _stub_plan(), _completed_record("exec-1")

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            stderr = io.StringIO()
            with (
                patch.object(cli, "_build_workflow_for_cli", return_value=Workflow()),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(stderr),
            ):
                exit_code = cli.main(["run", "--workspace", str(workspace), "--task", "Do it"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")

    def test_unreadable_text_file_is_reported_without_a_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "adir").mkdir()
            cases = (
                (["--description-file", "missing.txt", "--objective", "o"], "--description-file"),
                (["--description", "d", "--objective-file", "missing.txt"], "--objective-file"),
                (["--description-file", "adir", "--objective", "o"], "--description-file"),
            )
            for extra, expected in cases:
                with self.subTest(arguments=extra):
                    stderr = io.StringIO()
                    with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
                        cli.main(["run", "--workspace", str(workspace), *extra])

                    self.assertEqual(raised.exception.code, 2)
                    self.assertIn(f"could not read {expected}", stderr.getvalue())
                    self.assertNotIn("Traceback", stderr.getvalue())

    def test_task_shorthand_fills_both_description_and_objective(self) -> None:
        captured = {}

        class Workflow:
            def run(self, task, requested_agent):
                captured["task"] = task
                return _stub_plan(), _completed_record("exec-1")

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            with (
                patch.object(cli, "_build_workflow_for_cli", return_value=Workflow()),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                exit_code = cli.main([
                    "run", "--workspace", str(workspace), "--task", "Fix the parser",
                ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(captured["task"].description, "Fix the parser")
        self.assertEqual(captured["task"].objective, "Fix the parser")

    def test_task_shorthand_conflicts_are_rejected(self) -> None:
        parser = cli.build_parser()
        for extra in (
            ["--description", "d"],
            ["--objective", "o"],
            ["--description-file", "d.txt"],
        ):
            with self.subTest(extra=extra):
                args = parser.parse_args(["run", "--task", "t", *extra])
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    accepted = cli._apply_task_shorthand(args)

                self.assertFalse(accepted)
                self.assertIn("--task cannot be combined with", stderr.getvalue())

    def test_task_shorthand_is_optional(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args(["run", "--description", "d", "--objective", "o"])

        self.assertTrue(cli._apply_task_shorthand(args))
        self.assertEqual(args.description, "d")
        self.assertEqual(args.objective, "o")

    def test_every_option_documents_itself(self) -> None:
        # `--workspace` is the most-used option in the CLI and had no help text
        # on any of the eleven commands that accept it.
        undocumented: list[str] = []

        def scan(command: str, parser: argparse.ArgumentParser) -> None:
            for action in parser._actions:
                if isinstance(action, argparse._SubParsersAction):
                    for name, child in action.choices.items():
                        scan(f"{command} {name}", child)
                    continue
                if action.option_strings and not action.help:
                    undocumented.append(f"{command} {action.option_strings[0]}")

        root = cli.build_parser()
        subparsers = [
            action for action in root._actions
            if isinstance(action, argparse._SubParsersAction)
        ][0]
        for name, parser in subparsers.choices.items():
            scan(name, parser)

        self.assertEqual(undocumented, [])

    def test_run_help_groups_its_options_by_what_they_configure(self) -> None:
        # `run` carries more than thirty options; a single flat list is a wall.
        parser = cli.build_parser()
        run_parser = [
            action for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        ][0].choices["run"]
        help_text = run_parser.format_help()

        for heading in (
            "agent selection:",
            "task definition:",
            "verification and evaluators:",
            "routing and telemetry:",
            "escalation:",
            "output:",
        ):
            self.assertIn(heading, help_text)

    def test_grouping_did_not_drop_any_run_option(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args([
            "run", "--description", "d", "--objective", "o",
            "--agent", "codex", "--capability", "testing", "--constraint", "c",
            "--priority", "high", "--time-limit", "30",
            "--verify-command", "check", "--verify-time-limit", "5",
            "--routing-policy", "static", "--routing-seed", "3",
            "--escalation-risk-threshold", "2", "--no-escalation",
            "--verbose", "--summary",
        ])

        self.assertEqual(args.description, "d")
        self.assertEqual(args.agent, "codex")
        self.assertEqual(args.capability, ["testing"])
        self.assertEqual(args.priority, "high")
        self.assertEqual(args.time_limit, 30)
        self.assertEqual(args.verify_command, ["check"])
        self.assertEqual(args.routing_policy, "static")
        self.assertEqual(args.escalation_risk_threshold, 2)
        self.assertTrue(args.no_escalation)
        self.assertTrue(args.verbose)
        self.assertTrue(args.summary)

    def test_subcommands_are_listed_in_the_order_they_are_used(self) -> None:
        # argparse lists subcommands in registration order, and help is read top
        # down: show/report/retry used to appear before the commands that create
        # anything to show.
        subparsers = [
            action for action in cli.build_parser()._actions
            if isinstance(action, argparse._SubParsersAction)
        ]
        order = list(subparsers[0].choices)

        self.assertEqual(order[:2], ["init", "doctor"])
        self.assertLess(order.index("run"), order.index("show"))
        self.assertLess(order.index("run"), order.index("report"))
        self.assertLess(order.index("run"), order.index("retry"))
        self.assertEqual(order[-1], "paired")

    def test_unrecognized_invocation_falls_back_to_the_console_script_name(self) -> None:
        with patch.object(sys, "argv", ["/opt/some-test-runner"]):
            self.assertEqual(cli.resolve_program_name(), cli.PROGRAM_NAME)

    def test_run_plan_reports_an_unreadable_plan_file_without_a_traceback(self) -> None:
        cases = {
            "missing.json": None,
            "not-a-list.json": json.dumps({"not": "a list"}),
            "missing-field.json": json.dumps([{"description": "d"}]),
            "bad-capability.json": json.dumps(
                [{"description": "d", "objective": "o", "capabilities": ["nope"]}]
            ),
        }
        for name, content in cases.items():
            with self.subTest(plan=name), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                if content is not None:
                    (workspace / name).write_text(content, encoding="utf-8")
                stderr = io.StringIO()

                # The workflow must never be built: opening the lifecycle recorder
                # reconciles attempts and rewrites the routing projection, which an
                # invocation that cannot start should not trigger.
                with (
                    patch.object(cli, "_build_workflow_for_cli") as build_workflow,
                    contextlib.redirect_stderr(stderr),
                ):
                    exit_code = cli.main(["run-plan", "--workspace", str(workspace), name])

                self.assertEqual(exit_code, 1)
                self.assertIn("Invalid plan file", stderr.getvalue())
                build_workflow.assert_not_called()

    def test_run_resolves_relative_text_files_from_final_workspace(self) -> None:
        class Workflow:
            task = None

            def run(self, task, requested_agent):
                self.task = task
                return object(), object()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first"
            workspace = root / "final"
            first.mkdir()
            inputs = workspace / "inputs"
            inputs.mkdir(parents=True)
            (inputs / "description.txt").write_text("Workspace description\n", encoding="utf-8")
            (inputs / "objective.txt").write_text("Workspace objective\n", encoding="utf-8")
            workflow = Workflow()

            with (
                patch.object(cli, "_build_workflow_for_cli", return_value=workflow),
                patch.object(cli, "asdict", return_value={}),
                patch.object(cli, "execution_succeeded", return_value=True),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                exit_code = cli.main([
                    "run",
                    "--workspace",
                    str(first),
                    "--workspace",
                    str(workspace),
                    "--description-file",
                    "inputs/description.txt",
                    "--objective-file",
                    "inputs/objective.txt",
                ])

            self.assertEqual(exit_code, 0)
            self.assertEqual(workflow.task.description, "Workspace description")
            self.assertEqual(workflow.task.objective, "Workspace objective")


class PlanStepReportingTests(unittest.TestCase):
    @staticmethod
    def _record(succeeded: bool, name: str) -> SimpleNamespace:
        return SimpleNamespace(
            status="completed" if succeeded else "failed",
            verification=SimpleNamespace(status="passed" if succeeded else "failed"),
            execution_id=name,
        )

    def _result(self, succeeded: bool, outcomes: tuple[bool, ...], stopped_early: bool = False) -> SimpleNamespace:
        steps = [
            SimpleNamespace(record=self._record(ok, f"step{index}"), plan=object())
            for index, ok in enumerate(outcomes, start=1)
        ]
        return SimpleNamespace(steps=steps, succeeded=succeeded, stopped_early=stopped_early)

    def test_step_numbering_counts_the_plan_not_the_steps_that_ran(self) -> None:
        result = self._result(False, (True, False), stopped_early=True)
        stdout = io.StringIO()
        with (
            patch.object(cli, "_rendered_summary", side_effect=lambda record, workspace: "summary"),
            contextlib.redirect_stdout(stdout),
        ):
            cli._print_plan_result(result, Path("/workspace"), summary=True, planned_steps=3)

        self.assertIn("--- step 1 of 3 ---", stdout.getvalue())
        self.assertIn("--- step 2 of 3 ---", stdout.getvalue())
        self.assertNotIn("of 2 ---", stdout.getvalue())

    def test_notification_describes_the_first_failure_not_a_later_success(self) -> None:
        with patch.object(cli, "execution_succeeded", side_effect=lambda record: record.status == "completed"):
            failed_plan = self._result(False, (True, False, True))
            self.assertEqual(cli._notified_step_record(failed_plan).execution_id, "step2")

            succeeded_plan = self._result(True, (True, True, True))
            self.assertEqual(cli._notified_step_record(succeeded_plan).execution_id, "step3")


class InterruptTests(unittest.TestCase):
    def test_interrupt_reports_a_status_instead_of_a_traceback(self) -> None:
        stderr = io.StringIO()
        with (
            patch.object(cli, "_run_command", side_effect=KeyboardInterrupt),
            contextlib.redirect_stderr(stderr),
        ):
            exit_code = cli.main(["run", "--task", "Do it"])

        self.assertEqual(exit_code, cli.INTERRUPTED_EXIT_CODE)
        self.assertEqual(exit_code, 130)
        self.assertIn("Interrupted", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_a_signal_driven_shutdown_still_propagates(self) -> None:
        class Termination(BaseException):
            pass

        with (
            patch.object(cli, "_run_command", side_effect=Termination),
            self.assertRaises(Termination),
        ):
            cli.main(["run", "--task", "Do it"])


class BlankOptionValueTests(unittest.TestCase):
    def test_an_epoch_that_says_nothing_is_rejected(self) -> None:
        for value in ("", "   "):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                stderr = io.StringIO()
                with (
                    contextlib.redirect_stderr(stderr),
                    contextlib.redirect_stdout(io.StringIO()),
                    self.assertRaises(SystemExit) as raised,
                ):
                    cli.main([
                        "run", "--workspace", directory, "--task", "Do it",
                        "--environment-epoch", value,
                    ])

                self.assertEqual(raised.exception.code, 2)
                self.assertIn("cannot be blank", stderr.getvalue())

    def test_a_real_epoch_passes_through(self) -> None:
        self.assertEqual(cli._non_blank_text("codex-0.145"), "codex-0.145")


class MissingRecordedDiffTests(unittest.TestCase):
    def test_a_recorded_diff_produces_no_note(self) -> None:
        bundle = SimpleNamespace(attempts=({"workspace_git_diff": "diff --git a b"},))
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            cli._warn_missing_recorded_diff(bundle)
        self.assertEqual(stderr.getvalue(), "")

    def test_an_absent_diff_explains_why_the_flag_added_nothing(self) -> None:
        for attempts in (({},), ({"workspace_git_diff": None},), ({"workspace_git_diff": "  "},)):
            with self.subTest(attempts=attempts):
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    cli._warn_missing_recorded_diff(SimpleNamespace(attempts=attempts))
                self.assertIn("--include-git-diff", stderr.getvalue())


class RoutingBaselineAgentTests(unittest.TestCase):
    """The baseline is an agent id, and is checked where every other one is."""

    def _run(self, workspace: Path, *options: str) -> tuple[int, str]:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
            exit_code = cli.main(["run", "--workspace", str(workspace), "--task", "Do it", *options])
        return exit_code, stderr.getvalue()

    def test_unknown_baseline_is_rejected_before_any_state_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            exit_code, stderr = self._run(
                workspace, "--routing-policy", "static", "--routing-baseline-agent", "nope",
            )

            self.assertEqual(exit_code, 2)
            self.assertIn("Unknown --routing-baseline-agent: nope", stderr)
            self.assertNotIn("Traceback", stderr)
            # Reaching the router would mean the lifecycle recorder already ran.
            self.assertEqual(list(workspace.iterdir()), [])

    def test_unknown_baseline_is_rejected_even_beside_an_explicit_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            exit_code, stderr = self._run(
                Path(directory), "--agent", "codex", "--routing-baseline-agent", "nope",
            )

            self.assertEqual(exit_code, 2)
            self.assertIn("Unknown --routing-baseline-agent", stderr)

    def test_a_registered_baseline_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(cli, "_build_workflow", return_value=object()) as build:
                workflow = cli._build_workflow_for_cli(
                    argparse.Namespace(
                        agent="auto",
                        routing_baseline_agent="codex",
                        claude_model=None,
                        codex_model=None,
                        codex_reasoning_effort=None,
                    ),
                    Path(directory),
                )

            self.assertIsNotNone(workflow)
            build.assert_called_once()


class InertEscalationOptionTests(unittest.TestCase):
    """Escalation only applies to --agent auto; saying so beats accepting it silently."""

    def test_typed_options_are_reported_only_when_the_caller_wrote_them(self) -> None:
        self.assertEqual(cli._escalation_options_in(["run", "--escalation"]), ["--escalation"])
        self.assertEqual(
            cli._escalation_options_in(["run", "--escalation-risk-threshold=0"]),
            ["--escalation-risk-threshold"],
        )
        self.assertEqual(cli._escalation_options_in(["run", "--no-escalation"]), [])
        self.assertEqual(cli._escalation_options_in(["run", "--task", "x"]), [])

    def test_no_warning_for_auto(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            cli._warn_inert_escalation_options(["run", "--escalation"], "auto")
        self.assertEqual(stderr.getvalue(), "")

    def test_warning_names_the_options_and_the_agent(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            cli._warn_inert_escalation_options(["run", "--escalation"], "claude-code")
        self.assertIn("--escalation", stderr.getvalue())
        self.assertIn("claude-code", stderr.getvalue())
        self.assertIn("--agent auto", stderr.getvalue())

    def test_run_with_an_explicit_agent_warns_through_the_command(self) -> None:
        class Workflow:
            def run(self, task, requested_agent):
                return object(), object()

        with tempfile.TemporaryDirectory() as directory:
            stderr = io.StringIO()
            with (
                patch.object(cli, "_build_workflow_for_cli", return_value=Workflow()),
                patch.object(cli, "asdict", return_value={}),
                patch.object(cli, "execution_succeeded", return_value=True),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(stderr),
            ):
                exit_code = cli.main([
                    "run", "--workspace", directory, "--task", "Do it",
                    "--agent", "codex", "--escalation",
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("has no effect with --agent codex", stderr.getvalue())


class RetryUnknownAgentTests(unittest.TestCase):
    def test_recorded_model_variant_that_is_not_configured_says_what_to_do(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            log = workspace / ".orchestrator" / "executions.jsonl"
            log.parent.mkdir(parents=True)
            log.write_text(json.dumps({
                "execution_id": "e1",
                "attempt_id": "a1",
                "agent_id": "claude-code:some-exotic-model",
                "task": {"description": "d", "objective": "o"},
            }) + "\n", encoding="utf-8")

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
                exit_code = cli.main(["retry", "#1", "--workspace", str(workspace)])

            self.assertEqual(exit_code, 2)
            self.assertIn("Unknown agent: claude-code:some-exotic-model", stderr.getvalue())
            self.assertIn("--agent auto", stderr.getvalue())


class WorkspaceResolutionTests(unittest.TestCase):
    WORKSPACE_COMMANDS = (
        ["show", "#1"],
        ["report", "#1"],
        ["retry", "#1"],
        ["replay"],
        ["doctor"],
        ["init"],
        ["memory", "search"],
        ["run", "--task", "Do it"],
    )

    def test_unresolvable_workspace_is_reported_as_a_bad_argument(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first"
            second = Path(directory) / "second"
            first.symlink_to(second)
            second.symlink_to(first)

            for command in self.WORKSPACE_COMMANDS:
                with self.subTest(command=command[0]):
                    stderr = io.StringIO()
                    with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
                        exit_code = cli.main([*command, "--workspace", str(first)])

                    self.assertEqual(exit_code, 2)
                    self.assertIn("could not resolve --workspace", stderr.getvalue())
                    self.assertNotIn("Traceback", stderr.getvalue())

    def test_home_relative_workspace_is_expanded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            (home / "project").mkdir(parents=True)
            stderr = io.StringIO()
            with (
                patch.dict(os.environ, {"HOME": str(home)}),
                contextlib.redirect_stderr(stderr),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                exit_code = cli.main(["show", "#1", "--workspace", "~/project"])

            self.assertEqual(exit_code, 1)
            self.assertIn(str((home / "project").resolve()), stderr.getvalue())
            self.assertNotIn("~", stderr.getvalue())


class RunArgumentRejectionTests(unittest.TestCase):
    """A run rejected for its arguments reports one line and touches nothing."""

    REJECTED = (
        (["--task", "hi", "--time-limit", "-5"], "not a positive number of seconds"),
        (["--task", "   "], "description and objective are required"),
        (["--description-file", "/nope.txt", "--objective", "x"], "could not read --description-file"),
    )

    def test_domain_validation_failures_are_reported_like_parser_errors(self) -> None:
        for options, expected in self.REJECTED:
            with self.subTest(options=options), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                stderr = io.StringIO()
                with (
                    contextlib.redirect_stderr(stderr),
                    contextlib.redirect_stdout(io.StringIO()),
                    self.assertRaises(SystemExit) as raised,
                ):
                    cli.main(["run", "--workspace", str(workspace), *options])

                self.assertEqual(raised.exception.code, 2)
                self.assertIn(expected, stderr.getvalue())
                self.assertNotIn("Traceback", stderr.getvalue())

    def test_no_workflow_is_built_for_a_run_that_cannot_start(self) -> None:
        for options, _expected in self.REJECTED:
            with self.subTest(options=options), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                with (
                    patch.object(cli, "_build_workflow_for_cli") as build_workflow,
                    contextlib.redirect_stderr(io.StringIO()),
                    contextlib.redirect_stdout(io.StringIO()),
                    self.assertRaises(SystemExit),
                ):
                    cli.main(["run", "--workspace", str(workspace), *options])

                build_workflow.assert_not_called()
                self.assertEqual(list(workspace.iterdir()), [])


class PlanSpecFieldTests(unittest.TestCase):
    """A near-miss key used to vanish while `plan validate` called the file good."""

    def _validate(self, payload: object) -> tuple[bool, str]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            ok, message = cli._validate_plan_file(path)
        return ok, message or ""

    def test_every_documented_field_is_accepted(self) -> None:
        ok, message = self._validate([{
            "description": "d",
            "objective": "o",
            "constraints": ["c"],
            "capabilities": ["testing"],
            "priority": "high",
            "time_limit_seconds": 60,
            "cost_limit_usd": 1.5,
            "task_id": "t1",
        }])
        self.assertTrue(ok, message)

    def test_a_near_miss_key_is_rejected_with_the_field_it_resembles(self) -> None:
        ok, message = self._validate([
            {"description": "d", "objective": "o", "constraint": ["never delete files"]},
        ])
        self.assertFalse(ok)
        self.assertIn("'constraint'", message)
        self.assertIn("did you mean 'constraints'?", message)

    def test_the_failing_step_is_named(self) -> None:
        ok, message = self._validate([
            {"description": "d", "objective": "o"},
            {"description": "d2", "objective": "o2", "nonsense": 1},
        ])
        self.assertFalse(ok)
        self.assertIn("step 2 of 2", message)

    def test_a_missing_required_field_reads_as_missing(self) -> None:
        ok, message = self._validate([{"objective": "o"}])
        self.assertFalse(ok)
        self.assertIn("missing required field 'description'", message)

    def test_a_step_that_is_not_an_object_is_reported_once(self) -> None:
        ok, message = self._validate(["just a string"])
        self.assertFalse(ok)
        self.assertIn("expected an object, got str", message)
        # Iterating the string would have named every letter as a bad field.
        self.assertNotIn("'j'", message)

    def test_the_retry_spec_round_trips_through_the_same_builder(self) -> None:
        # `task_spec_for_retry` feeds _task_from_spec; a field it emits that the
        # schema does not list would make every retry fail.
        spec = {
            "description": "d",
            "objective": "o",
            "constraints": [],
            "capabilities": [],
            "priority": "normal",
            "time_limit_seconds": None,
            "cost_limit_usd": None,
            "task_id": "t1",
        }
        self.assertTrue(set(spec) <= set(cli.PLAN_SPEC_FIELDS))
        self.assertEqual(cli._task_from_spec(spec).task_id, "t1")


class PlanGenerateOutputPathTests(unittest.TestCase):
    def test_home_relative_output_is_expanded_like_every_other_path_option(self) -> None:
        class Workflow:
            task = None

            def run(self, task, requested_agent):
                self.task = task
                return object(), SimpleNamespace(workspace_modified_files=())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            home = root / "home"
            workspace.mkdir()
            home.mkdir()
            workflow = Workflow()

            with (
                patch.dict(os.environ, {"HOME": str(home)}),
                patch.object(cli, "_build_workflow_for_cli", return_value=workflow),
                patch.object(cli, "execution_succeeded", return_value=True),
                patch.object(cli, "_load_plan", return_value=[]),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                exit_code = cli.main([
                    "plan",
                    "generate",
                    "Add a regression test",
                    "--workspace",
                    str(workspace),
                    "--output",
                    "~/plans/plan.json",
                ])

            self.assertEqual(exit_code, 0)
            expected = str((home / "plans" / "plan.json").resolve())
            self.assertEqual(workflow.task.context["output_path"], expected)
            self.assertNotIn("~", expected)


class ValidatePlanFileTests(unittest.TestCase):
    def test_returns_success_for_valid_plan_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(json.dumps([
                {"description": "Step one", "objective": "First"},
            ]))
            self.assertEqual(cli._validate_plan_file(path), (True, None))

    def test_returns_error_for_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text("{not-json")
            ok, message = cli._validate_plan_file(path)
            self.assertFalse(ok)
            self.assertIn("Invalid plan file", message or "")

    def test_returns_error_for_wrong_shape_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(json.dumps({"description": "not a list"}))
            ok, message = cli._validate_plan_file(path)
            self.assertFalse(ok)
            self.assertIn("non-empty JSON list", message or "")

    def test_returns_error_for_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(json.dumps([]))
            ok, message = cli._validate_plan_file(path)
            self.assertFalse(ok)
            self.assertIn("non-empty JSON list", message or "")


class PlanGenerationTaskTests(unittest.TestCase):
    def test_builds_planning_task_with_schema_and_required_capabilities(self) -> None:
        workspace = Path("/workspace")
        output_path = Path("/workspace/plan.json")
        task = cli._build_plan_generation_task("Add a regression test", workspace, output_path)
        self.assertIn("Add a regression test", task.description)
        self.assertIn("description: string, required", task.description)
        self.assertIn("objective: string, required", task.description)
        self.assertIn("constraints: array of strings, optional", task.description)
        self.assertIn("cost_limit_usd: non-negative number or null, optional", task.description)
        self.assertIn("repository_understanding", task.description)
        self.assertIn("planning", task.description)
        self.assertIn("low, normal, high, critical", task.description)
        self.assertEqual(task.required_capabilities, (Capability.REPOSITORY_UNDERSTANDING, Capability.PLANNING))
        self.assertIn(str(output_path), task.objective)


class UnexpectedModifiedFilesTests(unittest.TestCase):
    def test_returns_empty_list_for_matching_path(self) -> None:
        self.assertEqual(cli._unexpected_modified_files(["plan.json"], "plan.json"), [])

    def test_returns_unexpected_paths_for_non_matching_path(self) -> None:
        self.assertEqual(cli._unexpected_modified_files(["plan.json", "README.md"], "plan.json"), ["README.md"])

    def test_returns_empty_list_when_no_files_were_modified(self) -> None:
        self.assertEqual(cli._unexpected_modified_files([], "plan.json"), [])


class MemoryEntryFromArgsTests(unittest.TestCase):
    def test_builds_entry_from_record_arguments(self) -> None:
        args = type("Args", (), {
            "type": "architecture_decision",
            "title": "Use JSONL",
            "summary": "Store explicit engineering memory entries.",
            "rationale": "Append-only and queryable.",
            "alternative": ["sqlite"],
            "tag": ["memory", "architecture"],
            "related_task": "Track architecture decisions",
        })()
        entry = cli._memory_entry_from_args(args)
        self.assertEqual(entry.entry_type, MemoryEntryType.ARCHITECTURE_DECISION)
        self.assertEqual(entry.title, "Use JSONL")
        self.assertEqual(entry.alternatives_considered, ("sqlite",))
        self.assertEqual(entry.tags, ("memory", "architecture"))
        self.assertEqual(entry.related_task_description, "Track architecture decisions")


class MemorySearchFromArgsTests(unittest.TestCase):
    def test_builds_search_filters_from_arguments(self) -> None:
        args = type("Args", (), {"type": "failure_history", "tag": "regression", "keyword": "cache"})()
        self.assertEqual(
            cli._memory_search_filters_from_args(args),
            (MemoryEntryType.FAILURE_HISTORY, "regression", "cache"),
        )

    def test_builds_empty_search_filters_when_optional_arguments_are_missing(self) -> None:
        args = type("Args", (), {})()
        self.assertEqual(cli._memory_search_filters_from_args(args), (None, None, None))


class ResolveDescriptionTests(unittest.TestCase):
    def test_uses_inline_description(self) -> None:
        args = type("Args", (), {"description": "Do the thing", "description_file": None})()
        self.assertEqual(cli._resolve_description(args), "Do the thing")

    def test_uses_description_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "description.txt"
            path.write_text("Line one\n\nLine three\n", encoding="utf-8")
            args = type("Args", (), {"description": None, "description_file": path})()
            self.assertEqual(cli._resolve_description(args), "Line one\n\nLine three")

    def test_errors_when_both_description_sources_are_provided(self) -> None:
        parser = argparse.ArgumentParser(prog="prog")
        args = type("Args", (), {"description": "inline", "description_file": Path("description.txt")})()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                cli._resolve_description(args, parser)
        self.assertIn("exactly one of --description or --description-file must be provided for description", stderr.getvalue())

    def test_errors_when_no_description_source_is_provided(self) -> None:
        parser = argparse.ArgumentParser(prog="prog")
        args = type("Args", (), {"description": None, "description_file": None})()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                cli._resolve_description(args, parser)
        self.assertIn("exactly one of --description or --description-file must be provided for description", stderr.getvalue())


class ResolveObjectiveTests(unittest.TestCase):
    def test_uses_inline_objective(self) -> None:
        args = type("Args", (), {"objective": "Get it done", "objective_file": None})()
        self.assertEqual(cli._resolve_objective(args), "Get it done")

    def test_uses_objective_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "objective.txt"
            path.write_text("Line one\n\nLine three\n", encoding="utf-8")
            args = type("Args", (), {"objective": None, "objective_file": path})()
            self.assertEqual(cli._resolve_objective(args), "Line one\n\nLine three")

    def test_errors_when_both_objective_sources_are_provided(self) -> None:
        parser = argparse.ArgumentParser(prog="prog")
        args = type("Args", (), {"objective": "inline", "objective_file": Path("objective.txt")})()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                cli._resolve_objective(args, parser)
        self.assertIn("exactly one of --objective or --objective-file must be provided for objective", stderr.getvalue())

    def test_errors_when_no_objective_source_is_provided(self) -> None:
        parser = argparse.ArgumentParser(prog="prog")
        args = type("Args", (), {"objective": None, "objective_file": None})()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                cli._resolve_objective(args, parser)
        self.assertIn("exactly one of --objective or --objective-file must be provided for objective", stderr.getvalue())


class WorkspaceMustBeADirectoryTests(unittest.TestCase):
    """A mistyped --workspace is a bad argument, not a directory to create."""

    COMMANDS = (
        ("run", "--task", "Do the thing"),
        ("run-plan", "plan.json"),
        ("retry", "#1"),
        ("memory", "record", "--type", "trade_off", "--title", "T", "--summary", "S"),
        ("show", "#1"),
        ("replay",),
    )

    def test_missing_workspace_is_rejected_and_never_created(self) -> None:
        for command in self.COMMANDS:
            with self.subTest(command=command), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory) / "typo"
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
                    exit_code = cli.main([*command, "--workspace", str(workspace)])

                self.assertEqual(exit_code, 2)
                self.assertIn("does not exist", stderr.getvalue())
                self.assertFalse(workspace.exists())

    def test_workspace_naming_a_file_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "notes.txt"
            target.write_text("x", encoding="utf-8")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
                exit_code = cli.main(["run", "--workspace", str(target), "--task", "Do the thing"])

            self.assertEqual(exit_code, 2)
            self.assertIn("not a directory", stderr.getvalue())

    def test_doctor_still_reports_a_bad_workspace_as_a_failed_check(self) -> None:
        # `doctor` exists to name what is wrong; refusing to start would say less.
        with tempfile.TemporaryDirectory() as directory:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
                exit_code = cli.main(["doctor", "--workspace", str(Path(directory) / "typo")])

            self.assertEqual(exit_code, 1)
            self.assertIn("workspace", stdout.getvalue())
            self.assertIn("not a directory", stdout.getvalue())


class PositiveTimeLimitTests(unittest.TestCase):
    """A time limit no process could satisfy is refused before the agent runs."""

    OPTIONS = ("--time-limit", "--verify-time-limit", "--quality-evaluator-time-limit")

    def test_zero_and_negative_limits_are_argument_errors(self) -> None:
        for option in self.OPTIONS:
            for value in ("0", "-5"):
                with self.subTest(option=option, value=value), tempfile.TemporaryDirectory() as directory:
                    stderr = io.StringIO()
                    with (
                        patch.object(cli, "_build_workflow_for_cli") as build_workflow,
                        contextlib.redirect_stderr(stderr),
                        contextlib.redirect_stdout(io.StringIO()),
                        self.assertRaises(SystemExit) as raised,
                    ):
                        cli.main([
                            "run", "--workspace", directory, "--task", "Do the thing", option, value,
                        ])

                    self.assertEqual(raised.exception.code, 2)
                    self.assertIn("not a positive number of seconds", stderr.getvalue())
                    build_workflow.assert_not_called()

    def test_a_non_numeric_limit_names_the_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stderr = io.StringIO()
            with (
                contextlib.redirect_stderr(stderr),
                contextlib.redirect_stdout(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                cli.main(["run", "--workspace", directory, "--task", "Do it", "--time-limit", "soon"])

            self.assertIn("'soon' is not a number of seconds", stderr.getvalue())

    def test_fractional_limits_are_still_accepted(self) -> None:
        args = cli.build_parser().parse_args(
            ["run", "--task", "Do it", "--verify-time-limit", "0.5", "--time-limit", "1.5"]
        )
        self.assertEqual(args.verify_time_limit, 0.5)
        self.assertEqual(args.time_limit, 1.5)


class PlanSpecTypeTests(unittest.TestCase):
    """Plan-file values are checked here, where the file can still be named."""

    def test_a_string_where_an_array_belongs_is_rejected(self) -> None:
        # Accepted before: a string is iterable, so one constraint became twelve
        # single-character ones and nothing said so.
        with self.assertRaisesRegex(ValueError, "'constraints' must be an array of strings, got str"):
            cli._task_from_spec({"description": "a", "objective": "b", "constraints": "do not touch"})

    def test_a_non_string_array_entry_is_located(self) -> None:
        with self.assertRaisesRegex(ValueError, "'constraints' entry 2 must be a string, got int"):
            cli._task_from_spec({"description": "a", "objective": "b", "constraints": ["ok", 7]})

    def test_non_string_description_and_objective_name_the_field(self) -> None:
        with self.assertRaisesRegex(ValueError, "'description' must be a string, got int"):
            cli._task_from_spec({"description": 42, "objective": "b"})
        with self.assertRaisesRegex(ValueError, "'objective' must be a string, got NoneType"):
            cli._task_from_spec({"description": "a", "objective": None})

    def test_a_non_numeric_limit_is_rejected_including_booleans(self) -> None:
        for value in ("60", True):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "'time_limit_seconds' must be a number or null"):
                    cli._task_from_spec({"description": "a", "objective": "b", "time_limit_seconds": value})

    def test_invalid_enum_values_list_what_is_valid(self) -> None:
        with self.assertRaisesRegex(ValueError, "did you mean 'code_generation'"):
            cli._task_from_spec({"description": "a", "objective": "b", "capabilities": ["cod_generation"]})
        with self.assertRaisesRegex(ValueError, "'priority': 'urgent' is not valid; expected one of"):
            cli._task_from_spec({"description": "a", "objective": "b", "priority": "urgent"})

    def test_a_missing_required_field_is_still_named_as_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(json.dumps([{"objective": "b"}]), encoding="utf-8")
            _, error = cli._validate_plan_file(path)
            self.assertIn("missing required field 'description'", error or "")

    def test_a_fully_populated_valid_spec_still_loads(self) -> None:
        task = cli._task_from_spec({
            "description": "a", "objective": "b", "constraints": ["x"],
            "capabilities": ["testing"], "priority": "high",
            "time_limit_seconds": 60, "cost_limit_usd": None, "task_id": "t1",
        })
        self.assertEqual(task.constraints, ("x",))
        self.assertEqual(task.required_capabilities, (Capability.TESTING,))

    def test_a_recorded_execution_still_round_trips_through_retry(self) -> None:
        # `retry` rebuilds its task through the same function; the stricter
        # checks must not reject what the logger itself wrote.
        from adaptive_orchestrator.operations.reporting import task_spec_for_retry

        bundle = SimpleNamespace(
            execution_id="exec-1",
            primary={
                "task": {
                    "description": "Fix it", "objective": "Done",
                    "constraints": ["Read-only"], "required_capabilities": ["debugging"],
                    "priority": "high", "time_limit_seconds": 30, "cost_limit_usd": 1.0,
                },
                "task_id": "task-1",
            },
        )
        task = cli._task_from_spec(task_spec_for_retry(bundle))
        self.assertEqual(task.required_capabilities, (Capability.DEBUGGING,))
        self.assertEqual(task.task_id, "task-1")


class VerifyCommandParsingTests(unittest.TestCase):
    """A constraint command that holds nothing is refused, not skipped."""

    def test_a_blank_command_is_rejected(self) -> None:
        for value in ("", "   "):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "contains no command"):
                    cli._verify_commands([value])

    def test_an_unbalanced_quote_names_the_offending_value(self) -> None:
        with self.assertRaisesRegex(ValueError, r"--verify-command \"echo 'oops\" could not be parsed"):
            cli._verify_commands(["echo 'oops"])

    def test_valid_commands_are_tokenized_in_order(self) -> None:
        self.assertEqual(
            cli._verify_commands(["pytest -q", "ruff check ."]),
            [("pytest", "-q"), ("ruff", "check", ".")],
        )

    def test_a_blank_command_stops_the_run_before_the_agent_starts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
                exit_code = cli.main([
                    "run", "--workspace", directory, "--task", "Do the thing",
                    "--agent", "codex", "--verify-command", "",
                ])

            self.assertEqual(exit_code, 2)
            self.assertIn("contains no command", stderr.getvalue())
            self.assertFalse((Path(directory) / ".orchestrator").exists())


class PlanGenerateOverwriteTests(unittest.TestCase):
    """The agent writes the plan file, so the guard has to come first."""

    def test_an_existing_plan_file_is_not_replaced_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            existing = Path(directory) / "plan.json"
            existing.write_text('[{"description": "keep", "objective": "me"}]', encoding="utf-8")
            stderr = io.StringIO()
            with (
                patch.object(cli, "_build_workflow_for_cli") as build_workflow,
                contextlib.redirect_stderr(stderr),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                exit_code = cli.main(["plan", "generate", "do something", "--workspace", directory])

            self.assertEqual(exit_code, 2)
            self.assertIn("already exists", stderr.getvalue())
            self.assertIn("--force", stderr.getvalue())
            build_workflow.assert_not_called()
            self.assertIn("keep", existing.read_text(encoding="utf-8"))

    def test_force_allows_the_run_to_proceed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "plan.json").write_text("[]", encoding="utf-8")
            with (
                patch.object(cli, "_build_workflow_for_cli", return_value=None) as build_workflow,
                contextlib.redirect_stderr(io.StringIO()),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                cli.main(["plan", "generate", "do something", "--workspace", directory, "--force"])

            build_workflow.assert_called_once()


class ReportOutputTargetTests(unittest.TestCase):
    def test_a_directory_output_is_named_as_one_and_force_does_not_help(self) -> None:
        record = {
            "execution_id": "exec-1", "attempt_id": "attempt-1",
            "task": {"description": "Fix it", "objective": "It works"},
            "agent_id": "codex", "status": "completed", "duration_ms": 10,
            "verification": {"status": "passed"},
        }
        for extra in ([], ["--force"]):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                log = workspace / ".orchestrator" / "executions.jsonl"
                log.parent.mkdir(parents=True)
                log.write_text(json.dumps(record) + "\n", encoding="utf-8")
                target = workspace / "reports"
                target.mkdir()
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
                    exit_code = cli.main([
                        "report", "exec-1", "--workspace", str(workspace),
                        "--output", str(target), *extra,
                    ])

                self.assertEqual(exit_code, 1)
                self.assertIn("is a directory, not a file", stderr.getvalue())
                self.assertNotIn("already exists", stderr.getvalue())
                self.assertTrue(target.is_dir())


class EmptyTextFileTests(unittest.TestCase):
    def test_an_empty_file_names_the_option_and_the_path(self) -> None:
        for name, options in (
            ("description", ["--objective", "It works"]),
            ("objective", ["--description", "Fix it"]),
        ):
            for content in ("", "   \n\n"):
                with self.subTest(name=name, content=content), tempfile.TemporaryDirectory() as directory:
                    source = Path(directory) / "text.md"
                    source.write_text(content, encoding="utf-8")
                    stderr = io.StringIO()
                    with (
                        contextlib.redirect_stderr(stderr),
                        contextlib.redirect_stdout(io.StringIO()),
                        self.assertRaises(SystemExit) as raised,
                    ):
                        cli.main([
                            "run", "--workspace", directory, *options,
                            f"--{name}-file", str(source),
                        ])

                    self.assertEqual(raised.exception.code, 2)
                    self.assertIn(f"--{name}-file {source} is empty", stderr.getvalue())

    def test_a_file_holding_only_a_trailing_newline_still_reads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "text.md"
            source.write_text("Fix the parser\n", encoding="utf-8")
            args = type("Args", (), {"description": None, "description_file": source})()
            self.assertEqual(cli._resolve_description(args), "Fix the parser")


class PlanFileEncodingTests(unittest.TestCase):
    def test_a_byte_order_mark_does_not_fail_the_parse(self) -> None:
        # `plan generate` has an agent write this file; a BOM is a routine
        # artifact, not a malformed plan.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(
                json.dumps([{"description": "Step one", "objective": "First"}]),
                encoding="utf-8-sig",
            )
            tasks = cli._load_plan(path)
            self.assertEqual([task.description for task in tasks], ["Step one"])

    def test_plain_utf8_is_unaffected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(
                json.dumps([{"description": "단계 하나", "objective": "완료"}]),
                encoding="utf-8",
            )
            self.assertEqual(cli._load_plan(path)[0].description, "단계 하나")


class ShortIdentifierPrefixTests(unittest.TestCase):
    def _workspace(self, directory: str) -> Path:
        workspace = Path(directory)
        log = workspace / ".orchestrator" / "executions.jsonl"
        log.parent.mkdir(parents=True)
        log.write_text(json.dumps({
            "execution_id": "e5ea2bea-f524-4f1a-9276-191d75a613c7",
            "attempt_id": "attempt-1",
            "task": {"description": "Fix it", "objective": "It works"},
            "agent_id": "codex", "status": "completed", "duration_ms": 10,
            "verification": {"status": "passed"},
        }) + "\n", encoding="utf-8")
        return workspace

    def test_a_too_short_fragment_says_so(self) -> None:
        for command in ("show", "report", "retry"):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as directory:
                workspace = self._workspace(directory)
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
                    cli.main([command, "e5e", "--workspace", str(workspace)])

                self.assertIn("shorter than the 4 characters", stderr.getvalue())

    def test_a_long_wrong_identifier_gets_no_prefix_hint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace(directory)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
                cli.main(["show", "12345678", "--workspace", str(workspace)])

            self.assertIn("Execution not found", stderr.getvalue())
            self.assertNotIn("shorter than", stderr.getvalue())

    def test_a_legacy_row_number_gets_no_prefix_hint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self._workspace(directory)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
                cli.main(["show", "#9", "--workspace", str(workspace)])

            self.assertNotIn("shorter than", stderr.getvalue())


class ExplicitControlStateDirectoryTests(unittest.TestCase):
    """A typed control directory that names nothing is a typo, not an empty log."""

    def test_replay_refuses_a_missing_explicit_directory_and_creates_nothing(self) -> None:
        for extra in ([], ["--rebuild-state"], ["--reconcile-incomplete"]):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory) / "workspace"
                workspace.mkdir()
                control = Path(directory) / "typo"
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
                    exit_code = cli.main([
                        "replay", "--workspace", str(workspace),
                        "--control-state-dir", str(control), *extra,
                    ])

                self.assertEqual(exit_code, 2)
                self.assertIn("does not exist", stderr.getvalue())
                self.assertFalse(control.exists())

    def test_a_directory_inside_the_workspace_is_still_refused_as_such(self) -> None:
        # The safety rule outranks existence: reporting "does not exist" would
        # invite creating a directory that is rejected for a better reason.
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
                exit_code = cli.main([
                    "replay", "--workspace", str(workspace),
                    "--control-state-dir", str(workspace / "inside"),
                ])

            self.assertEqual(exit_code, 1)
            self.assertIn("must be outside the agent workspace", stderr.getvalue())

    def test_paired_analyze_refuses_a_missing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
                exit_code = cli.main([
                    "paired", "analyze", "manifest.json",
                    "--control-state-dir", str(Path(directory) / "typo"),
                ])

            self.assertEqual(exit_code, 2)
            self.assertIn("does not exist", stderr.getvalue())

    def test_the_default_path_is_left_to_come_into_existence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                exit_code = cli.main(["replay", "--workspace", str(workspace)])

            self.assertEqual(exit_code, 0)

    def test_an_existing_directory_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            control = Path(directory) / "control"
            control.mkdir()
            with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                exit_code = cli.main([
                    "replay", "--workspace", str(workspace), "--control-state-dir", str(control),
                ])

            self.assertEqual(exit_code, 0)

    def test_a_run_still_creates_the_directory_it_was_told_to_write(self) -> None:
        self.assertIsNone(cli._require_existing_control_state_dir(None))


class EscalatedFailureReasonTests(unittest.TestCase):
    """The reason on stderr describes the attempt the summary calls the outcome."""

    @staticmethod
    def _record(status: str, error: str | None, escalated: object = None) -> object:
        return SimpleNamespace(
            status=status,
            agent_id="codex",
            error=error,
            verification=SimpleNamespace(status="skipped"),
            execution_id="exec-1",
            escalation=None if escalated is None else SimpleNamespace(record=escalated),
        )

    def test_the_escalated_attempt_supplies_the_status_and_agent(self) -> None:
        escalated = SimpleNamespace(
            status="timed_out", agent_id="claude-code", error=None,
            verification=SimpleNamespace(status="skipped"), execution_id="exec-1",
            escalation=None,
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            cli._print_failure_reason(self._record("failed", None, escalated), "Run")

        self.assertIn("status=timed_out", stderr.getvalue())
        self.assertIn("agent=claude-code", stderr.getvalue())
        self.assertNotIn("status=failed", stderr.getvalue())

    def test_an_error_recorded_only_on_the_escalated_attempt_is_shown(self) -> None:
        escalated = SimpleNamespace(
            status="failed", agent_id="claude-code", error="boom\ndetail",
            verification=SimpleNamespace(status="skipped"), execution_id="exec-1",
            escalation=None,
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            cli._print_failure_reason(self._record("failed", None, escalated), "Run")

        self.assertIn("boom", stderr.getvalue())
        self.assertNotIn("detail", stderr.getvalue())

    def test_a_primary_error_still_shows_when_the_escalated_attempt_has_none(self) -> None:
        escalated = SimpleNamespace(
            status="failed", agent_id="claude-code", error=None,
            verification=SimpleNamespace(status="skipped"), execution_id="exec-1",
            escalation=None,
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            cli._print_failure_reason(self._record("failed", "primary blew up", escalated), "Run")

        self.assertIn("primary blew up", stderr.getvalue())

    def test_an_unescalated_record_is_reported_as_itself(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            cli._print_failure_reason(self._record("failed", "boom"), "Run")

        self.assertIn("status=failed", stderr.getvalue())
        self.assertIn("agent=codex", stderr.getvalue())
        self.assertIn("boom", stderr.getvalue())


class UnreadableExecutionLogTests(unittest.TestCase):
    """The log is read for routing history mid-run; check it before the agent."""

    def test_an_unreadable_log_is_one_line_and_stops_before_the_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            log = workspace / ".orchestrator" / "executions.jsonl"
            log.parent.mkdir(parents=True)
            log.write_text("", encoding="utf-8")
            # Unlinking it only needs write permission on the parent directory,
            # so the temporary directory still cleans up.
            log.chmod(0o000)
            if os.access(log, os.R_OK):  # running as root: the mode means nothing
                self.skipTest("cannot make a file unreadable for this user")

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
                exit_code = cli.main([
                    "run", "--workspace", str(workspace), "--task", "Do the thing",
                    "--agent", "codex", "--no-escalation",
                ])

            self.assertEqual(exit_code, 2)
            self.assertIn("cannot read the execution log", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())

    def test_a_log_path_that_is_a_directory_is_reported_not_raised(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / ".orchestrator" / "executions.jsonl"
            log.mkdir(parents=True)
            with self.assertRaisesRegex(OSError, "cannot read the execution log"):
                cli._require_readable_execution_log(log)

    def test_an_absent_log_is_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cli._require_readable_execution_log(Path(directory) / "nothing.jsonl")

    def test_a_readable_log_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "executions.jsonl"
            log.write_text("{}\n", encoding="utf-8")
            cli._require_readable_execution_log(log)


if __name__ == "__main__":
    unittest.main()
