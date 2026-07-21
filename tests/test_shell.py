import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.execution.agents import default_agent_ids
from adaptive_orchestrator.interfaces.shell import OrchestratorShell
from adaptive_orchestrator.operations.usage import CodexUsage


class ShellStateTests(unittest.TestCase):
    def test_workspace_command_sets_and_shows_session_workspace(self) -> None:
        shell = OrchestratorShell()
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                shell.onecmd(f"workspace {workspace}")
            self.assertEqual(shell.workspace, workspace.resolve())
            self.assertIn("Workspace set to", stdout.getvalue())
            self.assertIn(workspace.name, shell.prompt)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                shell.onecmd("workspace")
            self.assertEqual(stdout.getvalue().strip(), str(workspace.resolve()))

    def test_agent_command_sets_and_shows_session_agent(self) -> None:
        shell = OrchestratorShell()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            shell.onecmd("agent codex")
        self.assertEqual(shell.agent, "codex")
        self.assertIn("Agent set to codex", stdout.getvalue())
        self.assertIn("codex", shell.prompt)

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            shell.onecmd("agent")
        self.assertEqual(stdout.getvalue().strip(), "codex")

    def test_invalid_agent_is_rejected_without_changing_state(self) -> None:
        shell = OrchestratorShell()
        shell.agent = "claude-code"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            shell.onecmd("agent llama")
        self.assertEqual(shell.agent, "claude-code")
        self.assertIn("Error: agent must be one of auto, claude-code, codex", stdout.getvalue())

    def test_workspace_expands_quoted_directory_and_cd_is_an_alias(self) -> None:
        shell = OrchestratorShell()
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace with spaces"
            workspace.mkdir()
            with contextlib.redirect_stdout(io.StringIO()):
                shell.onecmd(f'workspace "{workspace}"')
            self.assertEqual(shell.workspace, workspace.resolve())

            with contextlib.redirect_stdout(io.StringIO()):
                shell.onecmd(f"cd {directory}")
            self.assertEqual(shell.workspace, Path(directory).resolve())

    def test_workspace_rejects_missing_path_and_regular_file(self) -> None:
        shell = OrchestratorShell()
        original = shell.workspace
        with tempfile.TemporaryDirectory() as directory:
            regular_file = Path(directory) / "file.txt"
            regular_file.write_text("not a directory", encoding="utf-8")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                shell.onecmd(f"workspace {Path(directory) / 'missing'}")
                shell.onecmd(f"workspace {regular_file}")
        self.assertEqual(shell.workspace, original)
        self.assertIn("workspace does not exist", stdout.getvalue())
        self.assertIn("workspace is not a directory", stdout.getvalue())

    def test_status_shows_current_session_state(self) -> None:
        shell = OrchestratorShell()
        shell.workspace = Path("/tmp/session-workspace")
        shell.agent = "codex"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            shell.onecmd("status")
        self.assertEqual(stdout.getvalue().splitlines(), [
            "Workspace: /tmp/session-workspace",
            "Agent: codex",
        ])

    def test_empty_line_does_not_repeat_last_command(self) -> None:
        shell = OrchestratorShell()
        with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
            shell.onecmd("task Run tests")
            shell.onecmd("")
        self.assertEqual(main.call_count, 1)

    def test_unknown_command_suggests_a_close_match(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            OrchestratorShell().onecmd("stats")
        self.assertIn("Did you mean 'status'?", stdout.getvalue())

    def test_agent_and_path_completion(self) -> None:
        shell = OrchestratorShell()
        self.assertEqual(shell.complete_agent("c", "agent c", 6, 7), ["claude-code", "codex"])
        self.assertEqual(shell.complete_set("v", "set v", 4, 5), ["verbose", "verify"])
        self.assertEqual(shell.complete_set("o", "set verbose o", 12, 13), ["on", "off"])
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "worktree"
            workspace.mkdir()
            (Path(directory) / "plan.json").write_text("[]", encoding="utf-8")
            path_prefix = f"{directory}/"
            self.assertEqual(
                shell.complete_workspace(path_prefix, f"workspace {path_prefix}", 10, 10 + len(path_prefix)),
                [f"{workspace}/"],
            )
            self.assertIn(
                f"{directory}/plan.json",
                shell.complete_run_plan(path_prefix, f"run_plan {path_prefix}", 9, 9 + len(path_prefix)),
            )


class ShellCliDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.shell = OrchestratorShell()
        self.shell.workspace = Path("/tmp/session-workspace")
        self.shell.agent = "claude-code"

    def test_run_builds_expected_argv(self) -> None:
        with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
            self.shell.onecmd('run --workspace /override --agent codex --description "Build it" --objective "Ship it"')
        main.assert_called_once_with([
            "run",
            "--workspace",
            "/tmp/session-workspace",
            "--agent",
            "claude-code",
            "--workspace",
            "/override",
            "--agent",
            "codex",
            "--description",
            "Build it",
            "--objective",
            "Ship it",
        ])

    def test_task_uses_request_as_description_and_objective(self) -> None:
        with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
            self.shell.onecmd("task Run the unit tests and fix failures")
        main.assert_called_once_with([
            "run",
            "--workspace",
            "/tmp/session-workspace",
            "--agent",
            "claude-code",
            "--description",
            "Run the unit tests and fix failures",
            "--objective",
            "Run the unit tests and fix failures",
        ])

    def test_task_without_request_prints_usage_error(self) -> None:
        stdout = io.StringIO()
        with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
            with contextlib.redirect_stdout(stdout):
                self.shell.onecmd("task")
        main.assert_not_called()
        self.assertIn("Usage: task <request>", stdout.getvalue())

    def test_compose_runs_a_multiline_request(self) -> None:
        with (
            patch("builtins.input", side_effect=["Run all tests.", "Fix any failures.", "."]),
            patch("adaptive_orchestrator.interfaces.shell.cli.main") as main,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.shell.onecmd("compose")
        request = "Run all tests.\nFix any failures."
        main.assert_called_once_with([
            "run",
            "--workspace",
            "/tmp/session-workspace",
            "--agent",
            "claude-code",
            "--description",
            request,
            "--objective",
            request,
        ])

    def test_compose_empty_request_is_cancelled(self) -> None:
        stdout = io.StringIO()
        with (
            patch("builtins.input", side_effect=["."]),
            patch("adaptive_orchestrator.interfaces.shell.cli.main") as main,
            contextlib.redirect_stdout(stdout),
        ):
            self.shell.onecmd("compose")
        main.assert_not_called()
        self.assertIn("Compose cancelled", stdout.getvalue())

    def test_session_defaults_are_added_to_task_argv(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            self.shell.onecmd("set verbose on")
            self.shell.onecmd("set no_escalation on")
            self.shell.onecmd("set time_limit 30")
            self.shell.onecmd("set verify python3 -m unittest")
        with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
            self.shell.onecmd("task Run tests")
        main.assert_called_once_with([
            "run",
            "--workspace",
            "/tmp/session-workspace",
            "--agent",
            "claude-code",
            "--verify-command",
            "python3 -m unittest",
            "--no-escalation",
            "--verbose",
            "--time-limit",
            "30",
            "--description",
            "Run tests",
            "--objective",
            "Run tests",
        ])

    def test_run_plan_uses_workflow_defaults_but_not_task_time_limit(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            self.shell.onecmd("set verbose on")
            self.shell.onecmd("set time_limit 30")
        with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
            self.shell.onecmd("run_plan plan.json")
        main.assert_called_once_with([
            "run-plan",
            "plan.json",
            "--workspace",
            "/tmp/session-workspace",
            "--agent",
            "claude-code",
            "--verbose",
        ])

    def test_settings_show_and_clear_defaults(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.shell.onecmd('set verify "python3 -m unittest"')
            self.shell.onecmd("set time_limit 12.5")
            self.shell.onecmd("settings")
            self.shell.onecmd("set verify off")
            self.shell.onecmd("set time_limit off")
        output = stdout.getvalue()
        self.assertIn("Time limit: 12.5s", output)
        self.assertIn("Verify command: python3 -m unittest", output)
        self.assertIsNone(self.shell.default_verify_command)
        self.assertIsNone(self.shell.default_time_limit)

    def test_invalid_setting_does_not_change_defaults(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.shell.onecmd("set verbose maybe")
            self.shell.onecmd("set time_limit -1")
            self.shell.onecmd("set time_limit nan")
            self.shell.onecmd("set unknown value")
        self.assertFalse(self.shell.default_verbose)
        self.assertIsNone(self.shell.default_time_limit)
        self.assertIn("verbose must be on or off", stdout.getvalue())
        self.assertIn("unknown setting", stdout.getvalue())

    def test_run_plan_builds_expected_argv(self) -> None:
        with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
            self.shell.onecmd('run_plan plan.json --workspace /override --agent auto --continue-on-failure')
        main.assert_called_once_with([
            "run-plan",
            "plan.json",
            "--workspace",
            "/tmp/session-workspace",
            "--agent",
            "claude-code",
            "--workspace",
            "/override",
            "--agent",
            "auto",
            "--continue-on-failure",
        ])

    def test_plan_generate_builds_expected_argv(self) -> None:
        with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
            self.shell.onecmd('plan_generate "Add a dark mode toggle" --output x.json --agent codex')
        main.assert_called_once_with([
            "plan",
            "generate",
            "Add a dark mode toggle",
            "--workspace",
            "/tmp/session-workspace",
            "--agent",
            "claude-code",
            "--output",
            "x.json",
            "--agent",
            "codex",
        ])

    def test_plan_validate_builds_expected_argv(self) -> None:
        with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
            self.shell.onecmd("plan_validate plan.json")
        main.assert_called_once_with(["plan", "validate", "plan.json"])

    def test_memory_record_builds_expected_argv(self) -> None:
        with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
            self.shell.onecmd(
                'memory_record --type architecture_decision --title "Use JSONL" --summary "Store memory"'
            )
        main.assert_called_once_with([
            "memory",
            "record",
            "--workspace",
            "/tmp/session-workspace",
            "--type",
            "architecture_decision",
            "--title",
            "Use JSONL",
            "--summary",
            "Store memory",
        ])

    def test_memory_search_builds_expected_argv(self) -> None:
        with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
            self.shell.onecmd('memory_search --keyword cache --tag memory')
        main.assert_called_once_with([
            "memory",
            "search",
            "--workspace",
            "/tmp/session-workspace",
            "--keyword",
            "cache",
            "--tag",
            "memory",
        ])

    def test_system_exit_from_cli_does_not_escape_shell(self) -> None:
        stderr = io.StringIO()
        with patch("adaptive_orchestrator.interfaces.shell.cli.main", side_effect=[SystemExit(2), None]) as main:
            with contextlib.redirect_stderr(stderr):
                self.shell.onecmd('run --description "Build it" --objective "Ship it"')
                self.shell.onecmd('memory_search --keyword cache')
        self.assertEqual(main.call_count, 2)
        self.assertIn("Error: run failed with exit code 2", stderr.getvalue())

    def test_successful_system_exit_from_cli_help_is_not_reported_as_an_error(self) -> None:
        stderr = io.StringIO()
        with patch("adaptive_orchestrator.interfaces.shell.cli.main", side_effect=SystemExit(0)):
            with contextlib.redirect_stderr(stderr):
                self.shell.onecmd("run --help")
        self.assertEqual(stderr.getvalue(), "")

    def test_help_run_delegates_to_existing_cli_help(self) -> None:
        original_program = sys.argv[0]
        with patch("adaptive_orchestrator.interfaces.shell.cli.main", side_effect=SystemExit(0)) as main:
            self.shell.onecmd("help run")
        main.assert_called_once_with(["run", "--help"])
        self.assertEqual(sys.argv[0], original_program)

    def test_run_plan_without_plan_file_prints_usage_error(self) -> None:
        stdout = io.StringIO()
        with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
            with contextlib.redirect_stdout(stdout):
                self.shell.onecmd("run_plan")
        main.assert_not_called()
        self.assertIn("Usage: run_plan <plan_file>", stdout.getvalue())

    def test_plan_generate_without_request_prints_usage_error(self) -> None:
        stdout = io.StringIO()
        with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
            with contextlib.redirect_stdout(stdout):
                self.shell.onecmd("plan_generate")
        main.assert_not_called()
        self.assertIn("Usage: plan_generate <request>", stdout.getvalue())


class ShellHistoryTests(unittest.TestCase):
    def test_history_prints_no_data_for_missing_execution_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            shell = OrchestratorShell()
            shell.workspace = Path(directory)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                shell.onecmd("history")
            output = stdout.getvalue().strip().splitlines()
            self.assertEqual([line.split(":")[0] for line in output], list(default_agent_ids()))
            self.assertTrue(all("no data yet" in line for line in output))

    def test_history_includes_agent_ids_found_only_in_the_log(self) -> None:
        # A rename or unregistration must not hide past runs, so the log is a source too.
        with tempfile.TemporaryDirectory() as directory:
            shell = OrchestratorShell()
            shell.workspace = Path(directory)
            log = shell.workspace / ".orchestrator" / "executions.jsonl"
            log.parent.mkdir()
            log.write_text(json.dumps({"agent_id": "retired-agent", "status": "completed", "duration_ms": 1}) + "\n")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                shell.onecmd("history")
            output = stdout.getvalue().strip().splitlines()
            self.assertEqual([line.split(":")[0] for line in output], [*default_agent_ids(), "retired-agent"])

    def test_recent_shows_newest_executions_first_and_skips_malformed_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            shell = OrchestratorShell()
            shell.workspace = Path(directory)
            log = shell.workspace / ".orchestrator" / "executions.jsonl"
            log.parent.mkdir()
            records = [
                {
                    "agent_id": "claude-code",
                    "status": "failed",
                    "duration_ms": 250,
                    "task": {"description": "First task"},
                },
                {
                    "agent_id": "codex",
                    "status": "completed",
                    "duration_ms": 1250,
                    "verification": {"status": "passed"},
                    "task": {"description": "Second task"},
                },
            ]
            log.write_text(
                json.dumps(records[0]) + "\nnot-json\n" + json.dumps(records[1]) + "\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                shell.onecmd("recent 2")
            output = stdout.getvalue().strip().splitlines()
            self.assertIn("#2 codex completed verify=passed duration=1.2s — Second task", output[0])
            self.assertIn("#1 claude-code failed verify=not-run duration=0.2s — First task", output[1])

    def test_recent_validates_count_and_handles_missing_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            shell = OrchestratorShell()
            shell.workspace = Path(directory)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                shell.onecmd("recent many")
                shell.onecmd("recent 0")
                shell.onecmd("recent")
            output = stdout.getvalue()
            self.assertIn("Usage: recent [count]", output)
            self.assertIn("between 1 and 100", output)
            self.assertIn("No executions logged yet", output)


class ShellUsageTests(unittest.TestCase):
    def _run_usage(
        self,
        codex_usage: CodexUsage | None,
        subscription: str | None,
        execution_lines: list[dict[str, object]] | None = None,
    ) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            shell = OrchestratorShell()
            shell.workspace = Path(directory)
            if execution_lines is not None:
                log = shell.workspace / ".orchestrator" / "executions.jsonl"
                log.parent.mkdir()
                log.write_text("\n".join(json.dumps(line) for line in execution_lines), encoding="utf-8")
            stdout = io.StringIO()
            with (
                patch("adaptive_orchestrator.interfaces.shell.read_codex_usage", return_value=codex_usage),
                patch("adaptive_orchestrator.interfaces.shell.read_claude_subscription", return_value=subscription),
                patch("adaptive_orchestrator.interfaces.shell.time.time", return_value=1_700_000_000),
                contextlib.redirect_stdout(stdout),
            ):
                shell.onecmd("usage")
            return stdout.getvalue().strip().splitlines()

    def test_both_available(self) -> None:
        usage = CodexUsage("plus", 12.5, 10080, 1_700_432_000)
        executions = [
            {"agent_id": "claude-code", "status": "completed", "metadata": {"cost_usd": 1.2}},
            {"agent_id": "claude-code", "status": "completed", "metadata": {"cost_usd": 0.25}},
        ]
        self.assertEqual(self._run_usage(usage, "pro", executions), [
            "Codex: plus plan, 12.5% used (resets in 5d)",
            "Claude Code: pro subscription; logged in this project: $1.45 across 2 executions with cost data (no live quota % available locally)",
        ])

    def test_codex_unavailable_but_claude_available(self) -> None:
        executions = [{"agent_id": "claude-code", "metadata": {"cost_usd": 0.5}}]
        self.assertEqual(self._run_usage(None, "max", executions), [
            "Codex: usage data not available",
            "Claude Code: max subscription; logged in this project: $0.50 across 1 execution with cost data (no live quota % available locally)",
        ])

    def test_both_unavailable(self) -> None:
        self.assertEqual(self._run_usage(None, None), [
            "Codex: usage data not available",
            "Claude Code: logged in this project: no cost data logged yet (no live quota % available locally)",
        ])

    def test_claude_available_with_zero_cost_samples(self) -> None:
        self.assertEqual(self._run_usage(None, "pro"), [
            "Codex: usage data not available",
            "Claude Code: pro subscription; logged in this project: no cost data logged yet (no live quota % available locally)",
        ])


if __name__ == "__main__":
    unittest.main()
