import argparse
import contextlib
import io
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.interfaces import cli
from adaptive_orchestrator.infrastructure.configuration import ProjectConfig, config_path
from adaptive_orchestrator.core.domain import Capability, EvaluatorRole, MemoryEntryType, Priority
from adaptive_orchestrator.infrastructure.events import JsonlEventStore, LifecycleEventType
from adaptive_orchestrator.routing.state import LifecycleRecorder, RoutingStateStore


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


if __name__ == "__main__":
    unittest.main()
