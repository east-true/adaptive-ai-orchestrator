import contextlib
import io
import json
import signal
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.execution.agents import default_agent_ids
from adaptive_orchestrator.infrastructure.configuration import (
    ProjectConfig,
    config_path,
    load_project_config,
)
from adaptive_orchestrator.interfaces import shell as shell_interface
from adaptive_orchestrator.interfaces.shell import OrchestratorShell
from adaptive_orchestrator.operations.usage import CodexUsage


def _write_project_config(
    workspace: Path,
    *,
    agent: str = "auto",
    claude_model: str | None = None,
    codex_model: str | None = None,
    codex_reasoning_effort: str | None = None,
) -> Path:
    path = config_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "agent": agent,
                "models": {
                    "claude": claude_model,
                    "codex": codex_model,
                    "codex_reasoning_effort": codex_reasoning_effort,
                },
            }
        ),
        encoding="utf-8",
    )
    return path


class ShellStateTests(unittest.TestCase):
    def test_startup_banner_contains_wordmark_version_and_quick_help(self) -> None:
        banner = shell_interface._shell_banner("9.8.7", "4.2")

        self.assertIn("/ _ \\", banner)
        self.assertIn("Adaptive AI Orchestrator", banner)
        self.assertIn("Shell v9.8.7 | Kernel v4.2", banner)
        self.assertIn("Type help or ?; task <request>", banner)

    def test_banner_reports_the_shared_package_version(self) -> None:
        # The version helpers moved to infrastructure.version so the CLI can
        # report --version too; the banner must still read from that one source.
        with patch.object(shell_interface, "package_version", return_value="7.7.7"):
            self.assertIn("Shell v7.7.7", shell_interface._shell_banner())

    def test_settings_reports_the_effective_value_behind_each_inherited_row(self) -> None:
        # "inherit" alone does not say what will happen; only the agent row used
        # to reveal the profile value it falls back to.
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            path = config_path(workspace)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({
                    "version": 1,
                    "agent": "auto",
                    "execution": {"verbose": True, "time_limit_seconds": 600},
                    "verification": {"commands": ["python3 -m unittest"]},
                    "escalation": {"enabled": False},
                }),
                encoding="utf-8",
            )
            shell = OrchestratorShell()
            shell.workspace = workspace
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                shell.onecmd("settings")

        output = stdout.getvalue()
        self.assertIn("Verbose: inherit (effective: on)", output)
        self.assertIn("No escalation: inherit (effective: on)", output)
        self.assertIn("Time limit: inherit (effective: 600s)", output)
        self.assertIn("Verify command: inherit (effective: python3 -m unittest)", output)

    def test_settings_shows_explicit_overrides_without_an_effective_suffix(self) -> None:
        shell = OrchestratorShell()
        shell.default_verbose = False
        shell.default_time_limit = 30.0
        shell.default_verify_commands_disabled = True
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            shell.onecmd("settings")

        output = stdout.getvalue()
        self.assertIn("Verbose: off", output)
        self.assertNotIn("Verbose: inherit", output)
        self.assertIn("Time limit: 30s", output)
        self.assertIn("Verify command: off", output)

    def test_session_verify_command_is_shown_as_added_to_the_profile(self) -> None:
        # `--verify-command` appends to the profile's list at the CLI boundary,
        # so a row printing only the session value read as a replacement.
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            path = config_path(workspace)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({
                    "version": 1,
                    "agent": "auto",
                    "verification": {"commands": ["python3 -m unittest"]},
                }),
                encoding="utf-8",
            )
            shell = OrchestratorShell()
            shell.workspace = workspace
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                shell.onecmd("set verify echo session")
                shell.onecmd("settings")

        output = stdout.getvalue()
        self.assertIn("Note: this runs in addition to 1 verify command(s)", output)
        self.assertIn("Verify command: python3 -m unittest; echo session", output)

    def test_session_verify_command_stands_alone_without_a_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            shell = OrchestratorShell()
            shell.workspace = Path(directory)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                shell.onecmd("set verify echo session")
                shell.onecmd("settings")

        output = stdout.getvalue()
        self.assertNotIn("Note: this runs in addition", output)
        self.assertIn("Verify command: echo session", output)

    def test_settings_survives_an_invalid_project_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            path = config_path(workspace)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{broken", encoding="utf-8")
            shell = OrchestratorShell()
            shell.workspace = workspace
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                shell.onecmd("settings")

        self.assertIn("profile error", stdout.getvalue())

    def test_unknown_setting_lists_the_valid_names(self) -> None:
        shell = OrchestratorShell()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            shell.onecmd("set nope on")

        for name in shell_interface._SETTING_NAMES:
            self.assertIn(name, stdout.getvalue())

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
        self.assertEqual(stdout.getvalue().strip(), "codex (session override)")

    def test_invalid_agent_is_rejected_without_changing_state(self) -> None:
        shell = OrchestratorShell()
        shell.agent = "claude-code"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            shell.onecmd("agent llama")
        self.assertEqual(shell.agent, "claude-code")
        self.assertIn("Error: agent must be one of inherit, auto, claude-code, codex", stdout.getvalue())

    def test_agent_inherits_active_profile_and_accepts_exact_variants(self) -> None:
        shell = OrchestratorShell()
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            _write_project_config(
                workspace,
                agent="codex:gpt-5.5:high",
                claude_model="opus",
                codex_model="gpt-5.5",
                codex_reasoning_effort="high",
            )
            with contextlib.redirect_stdout(io.StringIO()):
                shell.onecmd(f"workspace {workspace}")

            self.assertIsNone(shell.agent_override)
            self.assertEqual(shell.agent, "codex:gpt-5.5:high")
            self.assertIn("codex:gpt-5.5:high", shell.prompt)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                shell.onecmd("agent")
            self.assertEqual(
                stdout.getvalue().strip(),
                "inherit (effective: codex:gpt-5.5:high)",
            )
            self.assertEqual(
                shell.complete_agent("c", "agent c", 6, 7),
                ["claude-code:opus", "codex:gpt-5.5:high"],
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                shell.onecmd("agent codex")
                shell.onecmd("agent codex:gpt-5.5:high")
            self.assertIn("agent must be one of", stdout.getvalue())
            self.assertEqual(shell.agent, "codex:gpt-5.5:high")
            self.assertIn("Agent set to codex:gpt-5.5:high", stdout.getvalue())

            with contextlib.redirect_stdout(io.StringIO()):
                shell.onecmd("agent inherit")
            self.assertIsNone(shell.agent_override)

    def test_workspace_warns_when_agent_override_is_not_in_new_profile(self) -> None:
        shell = OrchestratorShell()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()
            _write_project_config(second, codex_model="gpt-5.5")
            with contextlib.redirect_stdout(io.StringIO()):
                shell.onecmd(f"workspace {first}")
                shell.onecmd("agent codex")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                shell.onecmd(f"workspace {second}")
                shell.onecmd("status")
            self.assertEqual(shell.agent, "codex")
            self.assertIn("session agent 'codex' is unavailable", stdout.getvalue())
            self.assertIn("unavailable in active profile", stdout.getvalue())

    def test_invalid_profile_does_not_break_agent_status_or_completion(self) -> None:
        shell = OrchestratorShell()
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            path = config_path(workspace)
            path.parent.mkdir(parents=True)
            path.write_text("not-json", encoding="utf-8")
            shell.workspace = workspace

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                shell.onecmd("agent")
                shell.onecmd("status")
            self.assertIn("profile error", stdout.getvalue())
            self.assertEqual(shell.complete_agent("", "agent ", 6, 6), ["inherit"])

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

    def test_relative_workspace_is_resolved_from_current_session_workspace(self) -> None:
        shell = OrchestratorShell()
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / "parent"
            child = parent / "child"
            child.mkdir(parents=True)
            shell.workspace = parent.resolve()

            with contextlib.redirect_stdout(io.StringIO()):
                shell.onecmd("cd child")

            self.assertEqual(shell.workspace, child.resolve())

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

    def test_workspace_rejects_unresolvable_home_without_escaping_shell(self) -> None:
        shell = OrchestratorShell()
        original = shell.workspace
        stdout = io.StringIO()
        with (
            patch.object(Path, "expanduser", side_effect=RuntimeError("unknown home")),
            contextlib.redirect_stdout(stdout),
        ):
            shell.onecmd("workspace ~/project")
        self.assertEqual(shell.workspace, original)
        self.assertIn("could not resolve workspace", stdout.getvalue())

    def test_status_shows_current_session_state(self) -> None:
        shell = OrchestratorShell()
        shell.workspace = Path("/tmp/session-workspace")
        shell.agent = "codex"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            shell.onecmd("status")
        self.assertEqual(stdout.getvalue().splitlines(), [
            "Workspace: /tmp/session-workspace",
            "Agent: codex (session override)",
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
        self.assertEqual(shell.complete_set("i", "set verbose i", 12, 13), ["inherit"])
        with tempfile.TemporaryDirectory() as directory:
            shell.workspace = Path(directory)
            workspace = Path(directory) / "worktree"
            workspace.mkdir()
            (Path(directory) / "plan.json").write_text("[]", encoding="utf-8")
            plans = Path(directory) / "plans"
            plans.mkdir()
            (plans / "task.json").write_text("[]", encoding="utf-8")
            path_prefix = f"{directory}/"
            self.assertEqual(
                shell.complete_workspace(path_prefix, f"workspace {path_prefix}", 10, 10 + len(path_prefix)),
                [f"{plans}/", f"{workspace}/"],
            )
            self.assertIn(
                f"{directory}/plan.json",
                shell.complete_run_plan(path_prefix, f"run_plan {path_prefix}", 9, 9 + len(path_prefix)),
            )
            self.assertEqual(
                shell.complete_workspace("w", "workspace w", 10, 11),
                ["worktree/"],
            )
            self.assertEqual(
                shell.complete_run_plan("p", "run_plan p", 9, 10),
                ["plan.json", "plans/"],
            )
            self.assertEqual(
                shell.complete_run_plan("plans/", "run_plan plans/", 9, 15),
                ["plans/task.json"],
            )

    def test_readline_completion_receives_whole_hyphenated_and_nested_tokens(self) -> None:
        import readline

        shell = OrchestratorShell()
        with tempfile.TemporaryDirectory() as directory:
            shell.workspace = Path(directory)
            plans = shell.workspace / "plans"
            plans.mkdir()
            (plans / "task.json").write_text("[]", encoding="utf-8")
            spaced = shell.workspace / "space dir"
            spaced.mkdir()
            nested = shell.workspace / "foo" / "space dir"
            nested.mkdir(parents=True)
            apostrophe = shell.workspace / "weird file's"
            apostrophe.mkdir()

            with (
                patch.object(readline, "get_line_buffer", return_value="run_plan plans/t"),
                patch.object(readline, "get_begidx", return_value=9),
                patch.object(readline, "get_endidx", return_value=16),
            ):
                self.assertEqual(shell.complete("plans/t", 0), "plans/task.json")

            with (
                patch.object(readline, "get_line_buffer", return_value="agent claude-c"),
                patch.object(readline, "get_begidx", return_value=6),
                patch.object(readline, "get_endidx", return_value=14),
            ):
                self.assertEqual(shell.complete("claude-c", 0), "claude-code")

            for line, expected in (
                ("run_plan 'space d", "run_plan 'space dir/'"),
                ('run_plan "space d', 'run_plan "space dir/"'),
                ("run_plan space\\ d", "run_plan space\\ dir/"),
                ("run_plan './space d", "run_plan './space dir/'"),
                ("run_plan foo/'space d", "run_plan foo/'space dir/'"),
                ("run_plan weird\\ f", "run_plan weird\\ file\\'s/"),
            ):
                begidx = line.rfind(" ") + 1
                endidx = len(line)
                text = line[begidx:endidx]
                with (
                    patch.object(readline, "get_line_buffer", return_value=line),
                    patch.object(readline, "get_begidx", return_value=begidx),
                    patch.object(readline, "get_endidx", return_value=endidx),
                ):
                    completion = shell.complete(text, 0)
                completed = line[:begidx] + completion
                self.assertEqual(completed, expected)
                self.assertEqual(len(shlex.split(completed)), 2)

    def test_cmdloop_restores_process_global_readline_delimiters_on_interrupt(self) -> None:
        import readline

        shell = OrchestratorShell()
        original_delimiters = readline.get_completer_delims()
        original_completer = readline.get_completer()
        observed_delimiters: list[str] = []
        observed_completers: list[object] = []

        def interrupt(_shell: object, intro: str | None = None) -> None:
            del _shell, intro
            observed_delimiters.append(readline.get_completer_delims())
            observed_completers.append(readline.get_completer())
            raise KeyboardInterrupt

        with patch.object(
            shell_interface.cmd.Cmd,
            "cmdloop",
            autospec=True,
            side_effect=interrupt,
        ):
            with self.assertRaises(KeyboardInterrupt):
                shell.cmdloop()

        self.assertEqual(observed_delimiters, [" \t\n"])
        self.assertEqual(observed_completers, [shell.complete])
        self.assertEqual(readline.get_completer_delims(), original_delimiters)
        self.assertEqual(readline.get_completer(), original_completer)

    def test_cmdloop_keeps_cmds_tab_completion_binding(self) -> None:
        import readline

        shell = OrchestratorShell()
        with (
            patch.object(readline, "parse_and_bind") as parse_and_bind,
            patch("builtins.input", return_value="exit"),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            shell.cmdloop(intro="")

        parse_and_bind.assert_called_once_with("tab: complete")

    def test_main_recovers_from_interrupt_at_prompt_without_repeating_intro(self) -> None:
        with patch.object(shell_interface, "OrchestratorShell") as shell_type:
            shell = shell_type.return_value
            shell.cmdloop.side_effect = [KeyboardInterrupt(), None]
            with contextlib.redirect_stdout(io.StringIO()):
                shell_interface.main([])

        self.assertEqual(shell.cmdloop.call_count, 2)
        self.assertIsNone(shell.cmdloop.call_args_list[0].kwargs["intro"])
        self.assertEqual(shell.cmdloop.call_args_list[1].kwargs["intro"], "")

    def test_main_translates_sigterm_to_exit_143_and_restores_handler(self) -> None:
        installed: list[tuple[signal.Signals, object]] = []

        def install(signum: signal.Signals, handler: object) -> None:
            installed.append((signum, handler))

        with (
            patch.object(shell_interface.signal, "getsignal", return_value=signal.SIG_DFL),
            patch.object(shell_interface.signal, "signal", side_effect=install),
            patch.object(shell_interface, "OrchestratorShell") as shell_type,
        ):
            shell = shell_type.return_value

            def terminate_from_loop(*, intro: str | None = None) -> None:
                del intro
                installed[0][1](signal.SIGTERM, None)  # type: ignore[operator]

            shell.cmdloop.side_effect = terminate_from_loop
            with self.assertRaises(SystemExit) as raised:
                shell_interface.main([])

        self.assertEqual(raised.exception.code, 143)
        self.assertEqual(installed[-1], (signal.SIGTERM, signal.SIG_DFL))

    @unittest.skipUnless(hasattr(signal, "SIGHUP"), "POSIX hangup signal")
    def test_main_unwinds_on_hangup_and_restores_every_installed_handler(self) -> None:
        installed: list[tuple[signal.Signals, object]] = []

        def install(signum: signal.Signals, handler: object) -> None:
            installed.append((signum, handler))

        with (
            patch.object(shell_interface.signal, "getsignal", return_value=signal.SIG_DFL),
            patch.object(shell_interface.signal, "signal", side_effect=install),
            patch.object(shell_interface, "OrchestratorShell") as shell_type,
        ):
            shell = shell_type.return_value

            def hangup_from_loop(*, intro: str | None = None) -> None:
                del intro
                handlers = dict(installed)
                handlers[signal.SIGHUP](signal.SIGHUP, None)  # type: ignore[operator]

            shell.cmdloop.side_effect = hangup_from_loop
            with self.assertRaises(SystemExit) as raised:
                shell_interface.main([])

        self.assertEqual(raised.exception.code, 128 + signal.SIGHUP)
        restored = installed[-len({signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT}) :]
        self.assertEqual(
            {signum for signum, handler in restored if handler is signal.SIG_DFL},
            {signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT},
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

    def test_inherited_agent_is_omitted_so_project_profile_remains_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            _write_project_config(
                workspace,
                agent="codex:gpt-5.5:high",
                codex_model="gpt-5.5",
                codex_reasoning_effort="high",
            )
            self.shell.workspace = workspace
            self.shell.agent_override = None
            with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
                self.shell.onecmd("task Run tests")

            argv = main.call_args.args[0]
            self.assertNotIn("--agent", argv)
            parsed = shell_interface.cli.build_parser(
                load_project_config(workspace)
            ).parse_args(argv)
            self.assertEqual(parsed.agent, "codex:gpt-5.5:high")

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

    def test_compose_interrupt_discards_partial_request(self) -> None:
        stdout = io.StringIO()
        with (
            patch("builtins.input", side_effect=["Run all tests.", KeyboardInterrupt()]),
            patch("adaptive_orchestrator.interfaces.shell.cli.main") as main,
            contextlib.redirect_stdout(stdout),
        ):
            self.shell.onecmd("compose")
        main.assert_not_called()
        self.assertIn("Compose cancelled", stdout.getvalue())

    def test_compose_eof_discards_partial_request(self) -> None:
        stdout = io.StringIO()
        with (
            patch("builtins.input", side_effect=["Run all tests.", EOFError()]),
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
            "--workspace",
            "/tmp/session-workspace",
            "--agent",
            "claude-code",
            "--verbose",
            "plan.json",
        ])

    def test_settings_show_and_clear_defaults(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.shell.onecmd("set verify python3 -m unittest")
            self.shell.onecmd("set time_limit 12.5")
            self.shell.onecmd("settings")
            self.shell.onecmd("set verify off")
            self.shell.onecmd("set time_limit off")
            self.shell.onecmd("settings")
        output = stdout.getvalue()
        self.assertIn("Verbose: inherit", output)
        self.assertIn("No escalation: inherit", output)
        self.assertIn("Time limit: 12.5s", output)
        self.assertIn("Verify command: python3 -m unittest", output)
        self.assertIn("Time limit: off", output)
        self.assertIn("Verify command: off", output)
        self.assertIsNone(self.shell.default_verify_command)
        self.assertIsNone(self.shell.default_time_limit)
        self.assertTrue(self.shell.default_verify_commands_disabled)
        self.assertTrue(self.shell.default_time_limit_disabled)

    def test_verify_setting_preserves_a_quoted_executable_as_one_token(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            self.shell.onecmd('set verify "/tmp/check tool"')

        self.assertEqual(self.shell.default_verify_command, "'/tmp/check tool'")
        with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
            self.shell.onecmd("task Run tests")
        argv = main.call_args.args[0]
        stored = argv[argv.index("--verify-command") + 1]
        self.assertEqual(shlex.split(stored), ["/tmp/check tool"])

    def test_explicit_off_defaults_override_profiles_and_can_return_to_inherit(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            self.shell.onecmd("set verbose off")
            self.shell.onecmd("set no_escalation off")
            self.shell.onecmd("set time_limit off")
            self.shell.onecmd("set verify off")
        with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
            self.shell.onecmd("task Run tests")
        argv = main.call_args.args[0]
        self.assertIn("--no-verbose", argv)
        self.assertIn("--escalation", argv)
        self.assertIn("--no-time-limit", argv)
        self.assertIn("--clear-verify-commands", argv)
        profile = ProjectConfig(
            verbose=True,
            escalation_enabled=False,
            time_limit_seconds=90,
            verify_commands=("configured-check",),
        )
        parsed = shell_interface.cli.build_parser(profile).parse_args(argv)
        self.assertFalse(parsed.verbose)
        self.assertFalse(parsed.no_escalation)
        self.assertIsNone(parsed.time_limit)
        self.assertEqual(parsed.verify_command, [])

        with contextlib.redirect_stdout(io.StringIO()):
            self.shell.onecmd("set verbose inherit")
            self.shell.onecmd("set no_escalation unset")
            self.shell.onecmd("set time_limit inherit")
            self.shell.onecmd("set verify unset")
        with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
            self.shell.onecmd("task Run tests")
        inherited_argv = main.call_args.args[0]
        self.assertNotIn("--verbose", inherited_argv)
        self.assertNotIn("--no-verbose", inherited_argv)
        self.assertNotIn("--escalation", inherited_argv)
        self.assertNotIn("--no-escalation", inherited_argv)
        self.assertNotIn("--time-limit", inherited_argv)
        self.assertNotIn("--no-time-limit", inherited_argv)
        self.assertNotIn("--verify-command", inherited_argv)
        self.assertNotIn("--clear-verify-commands", inherited_argv)
        inherited = shell_interface.cli.build_parser(profile).parse_args(inherited_argv)
        self.assertTrue(inherited.verbose)
        self.assertTrue(inherited.no_escalation)
        self.assertEqual(inherited.time_limit, 90)
        self.assertEqual(inherited.verify_command, ["configured-check"])

    def test_invalid_setting_does_not_change_defaults(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.shell.onecmd("set verbose maybe")
            self.shell.onecmd("set time_limit -1")
            self.shell.onecmd("set time_limit nan")
            self.shell.onecmd("set unknown value")
        self.assertIsNone(self.shell.default_verbose)
        self.assertIsNone(self.shell.default_time_limit)
        self.assertIn("verbose must be on, off, or inherit", stdout.getvalue())
        self.assertIn("unknown setting", stdout.getvalue())

    def test_run_plan_preserves_flags_first_argv(self) -> None:
        with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
            self.shell.onecmd(
                "run_plan --workspace /override --agent auto "
                "--continue-on-failure plan.json"
            )
        main.assert_called_once_with([
            "run-plan",
            "--workspace",
            "/tmp/session-workspace",
            "--agent",
            "claude-code",
            "--workspace",
            "/override",
            "--agent",
            "auto",
            "--continue-on-failure",
            "plan.json",
        ])
        parsed = shell_interface.cli.build_parser(ProjectConfig()).parse_args(
            main.call_args.args[0]
        )
        self.assertEqual(parsed.plan_file, Path("plan.json"))
        self.assertEqual(parsed.workspace, Path("/override"))
        self.assertEqual(parsed.agent, "auto")

    def test_plan_generate_preserves_flags_first_argv(self) -> None:
        with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
            self.shell.onecmd(
                'plan_generate --output x.json --agent codex "Add a dark mode toggle"'
            )
        main.assert_called_once_with([
            "plan",
            "generate",
            "--workspace",
            "/tmp/session-workspace",
            "--agent",
            "claude-code",
            "--output",
            "x.json",
            "--agent",
            "codex",
            "Add a dark mode toggle",
        ])
        parsed = shell_interface.cli.build_parser(ProjectConfig()).parse_args(
            main.call_args.args[0]
        )
        self.assertEqual(parsed.request, "Add a dark mode toggle")
        self.assertEqual(parsed.output, Path("x.json"))
        self.assertEqual(parsed.agent, "codex")

    def test_plan_validate_builds_expected_argv(self) -> None:
        with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
            self.shell.onecmd("plan_validate plan.json")
        main.assert_called_once_with(["plan", "validate", "/tmp/session-workspace/plan.json"])

    def test_show_uses_session_workspace_and_recent_number(self) -> None:
        with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
            self.shell.onecmd("show #7")
        main.assert_called_once_with([
            "show",
            "--workspace",
            "/tmp/session-workspace",
            "#7",
        ])

    def test_retry_uses_session_defaults_and_recent_number(self) -> None:
        with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
            self.shell.onecmd("retry #7")
        main.assert_called_once_with([
            "retry",
            "--workspace",
            "/tmp/session-workspace",
            "--agent",
            "claude-code",
            "#7",
        ])

    def test_report_uses_session_workspace_and_preserves_options(self) -> None:
        with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
            self.shell.onecmd("report #7 --output report.md --include-diff")
        main.assert_called_once_with([
            "report",
            "--workspace",
            "/tmp/session-workspace",
            "#7",
            "--output",
            "report.md",
            "--include-diff",
        ])

    def test_plan_validate_rejects_extra_arguments_instead_of_ignoring_them(self) -> None:
        stdout = io.StringIO()
        with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
            with contextlib.redirect_stdout(stdout):
                self.shell.onecmd("plan_validate plan.json ignored.json")
        main.assert_not_called()
        self.assertIn("Usage: plan_validate <plan_file>", stdout.getvalue())

    def test_plan_commands_preserve_help_options_instead_of_resolving_them_as_paths(self) -> None:
        with patch(
            "adaptive_orchestrator.interfaces.shell.cli.main",
            side_effect=SystemExit(0),
        ) as main:
            self.shell.onecmd("run_plan --help")
        self.assertEqual(main.call_args.args[0], [
            "run-plan",
            "--workspace",
            "/tmp/session-workspace",
            "--agent",
            "claude-code",
            "--help",
        ])

        with patch(
            "adaptive_orchestrator.interfaces.shell.cli.main",
            side_effect=SystemExit(0),
        ) as main:
            self.shell.onecmd("plan_validate -h")
        main.assert_called_once_with(["plan", "validate", "-h"])

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

    def test_nonzero_cli_return_is_reported(self) -> None:
        stderr = io.StringIO()
        with patch("adaptive_orchestrator.interfaces.shell.cli.main", return_value=2):
            with contextlib.redirect_stderr(stderr):
                self.shell.onecmd('run --description "Build it" --objective "Ship it"')
        self.assertIn("Error: run failed with exit code 2", stderr.getvalue())

    def test_failure_that_explained_itself_is_not_restated_as_an_exit_code(self) -> None:
        # Every CLI failure path prints its own reason first; repeating it as
        # "failed with exit code 1" gave one problem two lines and pushed the
        # useful half up the scrollback.
        def explain_and_fail(argv: list[str]) -> int:
            print("Show failed: No executions are recorded in /w/executions.jsonl", file=sys.stderr)
            return 1

        stderr = io.StringIO()
        with patch("adaptive_orchestrator.interfaces.shell.cli.main", side_effect=explain_and_fail):
            with contextlib.redirect_stderr(stderr):
                self.shell.onecmd("show #1")

        output = stderr.getvalue()
        self.assertIn("Show failed: No executions are recorded", output)
        self.assertNotIn("failed with exit code", output)

    def test_silent_nonzero_exit_is_still_announced(self) -> None:
        stderr = io.StringIO()
        with patch("adaptive_orchestrator.interfaces.shell.cli.main", return_value=3):
            with contextlib.redirect_stderr(stderr):
                self.shell.onecmd("show #1")

        self.assertIn("Error: show failed with exit code 3", stderr.getvalue())

    def test_command_output_still_reaches_the_terminal(self) -> None:
        def emit(argv: list[str]) -> int:
            print("Execution: abc123")
            return 0

        stdout = io.StringIO()
        with patch("adaptive_orchestrator.interfaces.shell.cli.main", side_effect=emit):
            with contextlib.redirect_stdout(stdout):
                self.shell.onecmd("show #1")

        self.assertIn("Execution: abc123", stdout.getvalue())

    def test_keyboard_interrupt_cancels_command_without_escaping_shell(self) -> None:
        stderr = io.StringIO()
        with patch(
            "adaptive_orchestrator.interfaces.shell.cli.main",
            side_effect=[KeyboardInterrupt(), 0],
        ) as main:
            with contextlib.redirect_stderr(stderr):
                self.shell.onecmd("task Build it")
                self.shell.onecmd("memory_search --keyword cache")
        self.assertEqual(main.call_count, 2)
        self.assertIn("Interrupted: task", stderr.getvalue())

    def test_sigterm_unwind_is_not_swallowed_by_embedded_cli_boundary(self) -> None:
        original_program = sys.argv[0]
        with patch(
            "adaptive_orchestrator.interfaces.shell.cli.main",
            side_effect=shell_interface._ShellTermination(signal.SIGTERM),
        ):
            with self.assertRaises(shell_interface._ShellTermination):
                self.shell.onecmd("task Build it")
        self.assertEqual(sys.argv[0], original_program)

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
        main.assert_called_once_with([
            "run",
            "--workspace",
            "/tmp/session-workspace",
            "--help",
        ])
        self.assertEqual(sys.argv[0], original_program)

    def test_config_sensitive_help_uses_the_active_session_workspace(self) -> None:
        with patch(
            "adaptive_orchestrator.interfaces.shell.cli.main",
            side_effect=SystemExit(0),
        ) as main:
            self.shell.onecmd("help run_plan")
            self.shell.onecmd("help plan_generate")

        self.assertEqual(main.call_args_list[0].args[0], [
            "run-plan",
            "--workspace",
            "/tmp/session-workspace",
            "--help",
        ])
        self.assertEqual(main.call_args_list[1].args[0], [
            "plan",
            "generate",
            "--workspace",
            "/tmp/session-workspace",
            "--help",
        ])

    def test_help_show_delegates_to_existing_cli_help(self) -> None:
        with patch(
            "adaptive_orchestrator.interfaces.shell.cli.main",
            side_effect=SystemExit(0),
        ) as main:
            self.shell.onecmd("help show")
        main.assert_called_once_with(["show", "--help"])

    def test_help_retry_and_report_delegate_to_existing_cli_help(self) -> None:
        with patch(
            "adaptive_orchestrator.interfaces.shell.cli.main",
            side_effect=SystemExit(0),
        ) as main:
            self.shell.onecmd("help retry")
            self.shell.onecmd("help report")

        self.assertEqual(main.call_args_list[0].args[0], [
            "retry",
            "--workspace",
            "/tmp/session-workspace",
            "--help",
        ])
        self.assertEqual(main.call_args_list[1].args[0], ["report", "--help"])

    def test_inline_help_uses_canonical_program_name_and_restores_argv(self) -> None:
        original_program = sys.argv[0]
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.shell.onecmd("show --help")
        self.assertIn(
            f"usage: {shell_interface.cli.PROGRAM_NAME} show",
            stdout.getvalue(),
        )
        self.assertNotIn("adaptive-ai-orchestrator-shell", stdout.getvalue())
        self.assertEqual(sys.argv[0], original_program)

    def test_canonical_program_name_matches_the_installed_console_script(self) -> None:
        # Usage text told users to run "adaptive-orchestrator", which is not the
        # name pyproject installs. Pin the two together so they cannot drift.
        pyproject = Path(__file__).parents[1] / "pyproject.toml"
        self.assertIn(
            f"{shell_interface.cli.PROGRAM_NAME} = ",
            pyproject.read_text(encoding="utf-8"),
        )

    def test_show_without_identifier_prints_usage_error(self) -> None:
        stdout = io.StringIO()
        with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
            with contextlib.redirect_stdout(stdout):
                self.shell.onecmd("show")
        main.assert_not_called()
        self.assertIn("Usage: show <execution-id|attempt-id|#number>", stdout.getvalue())

    def test_retry_and_report_without_identifier_print_usage_errors(self) -> None:
        stdout = io.StringIO()
        with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
            with contextlib.redirect_stdout(stdout):
                self.shell.onecmd("retry")
                self.shell.onecmd("report")
        main.assert_not_called()
        self.assertIn("Usage: retry <execution-id|attempt-id|#number>", stdout.getvalue())
        self.assertIn("Usage: report <execution-id|attempt-id|#number>", stdout.getvalue())

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

    def test_workspace_scoped_commands_prepend_the_session_workspace(self) -> None:
        with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
            self.shell.onecmd("doctor")
            self.shell.onecmd("init --force")
            self.shell.onecmd("replay --rebuild-state")

        self.assertEqual(main.call_args_list[0].args[0], [
            "doctor",
            "--workspace",
            "/tmp/session-workspace",
        ])
        self.assertEqual(main.call_args_list[1].args[0], [
            "init",
            "--workspace",
            "/tmp/session-workspace",
            "--force",
        ])
        self.assertEqual(main.call_args_list[2].args[0], [
            "replay",
            "--workspace",
            "/tmp/session-workspace",
            "--rebuild-state",
        ])

    def test_workspace_scoped_commands_do_not_receive_session_workflow_defaults(self) -> None:
        self.shell.default_verbose = True
        self.shell.default_time_limit = 30.0
        with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
            self.shell.onecmd("doctor")

        argv = main.call_args.args[0]
        self.assertNotIn("--verbose", argv)
        self.assertNotIn("--time-limit", argv)
        self.assertNotIn("--agent", argv)

    def test_paired_commands_supply_source_repository_only_where_defined(self) -> None:
        parser = shell_interface.cli.build_parser()
        expected_source_repository = {
            "paired_validate": True,
            "paired_plan": False,
            "paired_dry_run": True,
            "paired_analyze": False,
            "paired_run": True,
            "paired_resume": True,
        }
        extra_arguments = {
            "paired_validate": "",
            "paired_plan": " --workspace-root /tmp/root",
            "paired_dry_run": " --workspace-root /tmp/root",
            "paired_analyze": " --control-state-dir /tmp/state",
            "paired_run": " --workspace-root /tmp/root --control-state-dir /tmp/state",
            "paired_resume": " --workspace-root /tmp/root --control-state-dir /tmp/state",
        }

        for command, supplies_source in expected_source_repository.items():
            with self.subTest(command=command):
                with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
                    self.shell.onecmd(f"{command} manifest.json{extra_arguments[command]}")

                argv = main.call_args.args[0]
                self.assertEqual(argv[0], "paired")
                self.assertEqual(
                    "--source-repository" in argv,
                    supplies_source,
                    msg=f"{command} produced {argv}",
                )
                if supplies_source:
                    index = argv.index("--source-repository")
                    self.assertEqual(argv[index + 1], "/tmp/session-workspace")
                # The generated argv must remain acceptable to the canonical parser.
                parser.parse_args(argv)

    def test_paired_manifest_resolves_against_the_session_workspace(self) -> None:
        with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
            self.shell.onecmd("paired_validate manifests/smoke.json")

        self.assertIn("/tmp/session-workspace/manifests/smoke.json", main.call_args.args[0])

    def test_paired_leading_option_leaves_following_tokens_untouched(self) -> None:
        with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
            self.shell.onecmd("paired_plan --workspace-root relative/root manifest.json")

        argv = main.call_args.args[0]
        self.assertIn("relative/root", argv)
        self.assertIn("manifest.json", argv)

    def test_paired_run_never_injects_agent_execution_confirmation(self) -> None:
        parser = shell_interface.cli.build_parser()
        for command in ("paired_run", "paired_resume"):
            with self.subTest(command=command):
                with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
                    self.shell.onecmd(
                        f"{command} manifest.json --workspace-root /tmp/root "
                        "--control-state-dir /tmp/state"
                    )

                argv = main.call_args.args[0]
                self.assertNotIn("--confirm-agent-execution", argv)
                self.assertFalse(parser.parse_args(argv).confirm_agent_execution)

    def test_explicit_paired_source_repository_overrides_the_session_default(self) -> None:
        with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
            self.shell.onecmd("paired_validate manifest.json --source-repository /explicit")

        parsed = shell_interface.cli.build_parser().parse_args(main.call_args.args[0])
        self.assertEqual(parsed.source_repository, Path("/explicit"))

    def test_paired_commands_without_a_manifest_print_usage_errors(self) -> None:
        stdout = io.StringIO()
        with patch("adaptive_orchestrator.interfaces.shell.cli.main") as main:
            with contextlib.redirect_stdout(stdout):
                self.shell.onecmd("paired_validate")
                self.shell.onecmd("paired_run")
        main.assert_not_called()
        self.assertIn("Usage: paired_validate <manifest>", stdout.getvalue())
        self.assertIn("Usage: paired_run <manifest>", stdout.getvalue())

    def test_new_commands_delegate_help_to_the_existing_cli_help(self) -> None:
        expected = {
            "doctor": ["doctor", "--workspace", "/tmp/session-workspace", "--help"],
            "init": ["init", "--workspace", "/tmp/session-workspace", "--help"],
            "replay": ["replay", "--workspace", "/tmp/session-workspace", "--help"],
            "paired_validate": ["paired", "validate", "--help"],
            "paired_dry_run": ["paired", "dry-run", "--help"],
            "paired_resume": ["paired", "resume", "--help"],
        }
        for command, argv in expected.items():
            with self.subTest(command=command):
                with patch(
                    "adaptive_orchestrator.interfaces.shell.cli.main",
                    side_effect=SystemExit(0),
                ) as main:
                    self.shell.onecmd(f"help {command}")
                main.assert_called_once_with(argv)


class ShellHelpOverviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.shell = OrchestratorShell()

    def _capture(self, line: str) -> str:
        # cmd.Cmd writes a command's own docstring to the stdout it bound at
        # construction, while the shell's own output uses print; capture both.
        stdout = io.StringIO()
        self.shell.stdout = stdout
        with contextlib.redirect_stdout(stdout):
            self.shell.onecmd(line)
        return stdout.getvalue()

    def _overview(self) -> str:
        return self._capture("help")

    def test_overview_groups_commands_under_task_oriented_headings(self) -> None:
        overview = self._overview()

        for heading in (
            "Session:",
            "Project:",
            "Run:",
            "History:",
            "Memory:",
            "Paired experiments:",
            "Shell:",
        ):
            self.assertIn(heading, overview)
        self.assertIn("Type `help <command>` for one command's full options.", overview)

    def test_overview_shows_usage_and_summary_for_every_command(self) -> None:
        overview = self._overview()

        for name, arguments in (
            entry for _title, entries in shell_interface._COMMAND_GROUPS for entry in entries
        ):
            with self.subTest(command=name):
                self.assertIn(f"{name} {arguments}".strip(), overview)
                self.assertIn(self.shell.command_summary(name), overview)

    def test_summaries_come_from_docstrings_so_they_cannot_drift(self) -> None:
        # The group table stores no summary text; `help <command>` and the
        # overview must therefore describe each command identically.
        for name, _arguments in (
            entry for _title, entries in shell_interface._COMMAND_GROUPS for entry in entries
        ):
            with self.subTest(command=name):
                docstring = getattr(self.shell, f"do_{name}").__doc__
                self.assertTrue(docstring, msg=f"do_{name} needs a docstring to summarize")
                self.assertEqual(
                    self.shell.command_summary(name),
                    docstring.strip().splitlines()[0].strip(),
                )

    def test_every_command_is_reachable_from_the_overview(self) -> None:
        # A command added without a group entry must still surface, so the
        # overview can never silently omit part of the shell's surface.
        self.assertEqual(self.shell._ungrouped_commands(), [])

        grouped = {
            name
            for _title, entries in shell_interface._COMMAND_GROUPS
            for name, _arguments in entries
        }
        commands = {
            name[3:] for name in self.shell.get_names() if name.startswith("do_")
        }
        self.assertEqual(commands - grouped, set(shell_interface._HELP_COVERED_ALIASES))

    def test_every_grouped_entry_names_a_real_command(self) -> None:
        for name, _arguments in (
            entry for _title, entries in shell_interface._COMMAND_GROUPS for entry in entries
        ):
            with self.subTest(command=name):
                self.assertTrue(callable(getattr(self.shell, f"do_{name}", None)))

    def test_ungrouped_commands_are_listed_under_other(self) -> None:
        with patch.object(
            OrchestratorShell,
            "do_experimental",
            lambda self, arg: None,
            create=True,
        ):
            self.assertEqual(self.shell._ungrouped_commands(), ["experimental"])
            overview = self._overview()

        self.assertIn("Other:", overview)
        self.assertIn("experimental", overview)

    def test_help_for_one_command_still_shows_its_own_documentation(self) -> None:
        output = self._capture("help compose")

        self.assertIn("Compose a multiline task", output)
        self.assertNotIn("Paired experiments:", output)


class ShellHistoryTests(unittest.TestCase):
    def test_execution_identifier_completion_covers_recent_execution_and_attempt_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            shell = OrchestratorShell()
            shell.workspace = Path(directory)
            log = shell.workspace / ".orchestrator" / "executions.jsonl"
            log.parent.mkdir()
            records = [
                {
                    "execution_id": "execution-1",
                    "attempt_id": "attempt-1",
                    "parent_attempt_id": None,
                },
                {
                    "execution_id": "execution-1",
                    "attempt_id": "attempt-2",
                    "parent_attempt_id": "attempt-1",
                },
                {
                    "execution_id": "execution-2",
                    "attempt_id": "attempt-3",
                    "parent_attempt_id": None,
                },
            ]
            log.write_text(
                "\n".join(json.dumps(record) for record in records),
                encoding="utf-8",
            )

            for complete, command in (
                (shell.complete_show, "show"),
                (shell.complete_retry, "retry"),
                (shell.complete_report, "report"),
            ):
                with self.subTest(command=command):
                    start = len(command) + 1
                    self.assertEqual(
                        complete("#", f"{command} #", start, start + 1),
                        ["#3", "#2"],
                    )
                    self.assertEqual(
                        complete("execution", f"{command} execution", start, start + 9),
                        ["execution-2", "execution-1"],
                    )
                    self.assertEqual(
                        complete("attempt", f"{command} attempt", start, start + 7),
                        ["attempt-3", "attempt-2", "attempt-1"],
                    )
                    self.assertEqual(
                        complete("", f"{command} #3 ", start + 3, start + 3),
                        [],
                    )

    def test_execution_identifier_completion_survives_history_read_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            shell = OrchestratorShell()
            shell.workspace = Path(directory)
            log = shell.workspace / ".orchestrator" / "executions.jsonl"
            log.mkdir(parents=True)
            stderr = io.StringIO()

            with contextlib.redirect_stderr(stderr):
                completed = shell.complete_show("", "show ", 5, 5)

            self.assertEqual(completed, [])
            self.assertIn("could not read execution history", stderr.getvalue())

    def test_execution_identifier_completion_survives_history_stat_failure(self) -> None:
        shell = OrchestratorShell()
        stderr = io.StringIO()
        with (
            patch.object(Path, "exists", side_effect=OSError("stat failed")),
            contextlib.redirect_stderr(stderr),
        ):
            completed = shell.complete_show("", "show ", 5, 5)

        self.assertEqual(completed, [])
        self.assertIn("stat failed", stderr.getvalue())

    def test_history_uses_exact_agent_variants_from_the_active_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            shell = OrchestratorShell()
            shell.workspace = Path(directory)
            _write_project_config(
                shell.workspace,
                claude_model="opus",
                codex_model="gpt-5.5",
                codex_reasoning_effort="high",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                shell.onecmd("history")

            self.assertEqual(
                [line.split(": 0", 1)[0] for line in stdout.getvalue().splitlines()],
                ["claude-code:opus", "codex:gpt-5.5:high"],
            )

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
            output = [
                line
                for line in stdout.getvalue().strip().splitlines()
                if line != shell_interface._HISTORY_CAVEAT
            ]
            self.assertEqual([line.split(":")[0] for line in output], [*default_agent_ids(), "retired-agent"])

    def test_history_warns_against_ranking_agents_when_it_prints_rates(self) -> None:
        # The percentages come from whichever agent was selected, not from a
        # controlled assignment, so the output itself has to say so.
        with tempfile.TemporaryDirectory() as directory:
            shell = OrchestratorShell()
            shell.workspace = Path(directory)
            log = shell.workspace / ".orchestrator" / "executions.jsonl"
            log.parent.mkdir()
            log.write_text(
                json.dumps({"agent_id": "codex", "status": "completed", "duration_ms": 1}) + "\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                shell.onecmd("history")

            output = stdout.getvalue()
            self.assertIn("% success", output)
            self.assertIn("Do not use them to rank agents.", output)

    def test_history_omits_the_ranking_caveat_when_there_are_no_rates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            shell = OrchestratorShell()
            shell.workspace = Path(directory)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                shell.onecmd("history")

            self.assertNotIn("rank agents", stdout.getvalue())

    def test_history_read_error_does_not_print_a_caveat_for_absent_rates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            shell = OrchestratorShell()
            shell.workspace = Path(directory)
            log = shell.workspace / ".orchestrator" / "executions.jsonl"
            log.mkdir(parents=True)
            stdout = io.StringIO()
            stderr = io.StringIO()

            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                shell.onecmd("history")

            self.assertIn("could not read execution history", stderr.getvalue())
            self.assertNotIn("rank agents", stdout.getvalue())

    def test_history_read_error_does_not_escape_shell(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            shell = OrchestratorShell()
            shell.workspace = Path(directory)
            log = shell.workspace / ".orchestrator" / "executions.jsonl"
            log.mkdir(parents=True)
            stderr = io.StringIO()

            with contextlib.redirect_stderr(stderr):
                shell.onecmd("history")

            self.assertIn("could not read execution history", stderr.getvalue())

    def test_invalid_utf8_history_does_not_escape_history_or_recent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            shell = OrchestratorShell()
            shell.workspace = Path(directory)
            log = shell.workspace / ".orchestrator" / "executions.jsonl"
            log.parent.mkdir()
            log.write_bytes(b"\xff\xfe\n")
            stderr = io.StringIO()

            with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
                shell.onecmd("history")
                shell.onecmd("recent")

            self.assertEqual(stderr.getvalue().count("could not read execution history"), 2)

    def test_malformed_record_shape_does_not_escape_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            shell = OrchestratorShell()
            shell.workspace = Path(directory)
            log = shell.workspace / ".orchestrator" / "executions.jsonl"
            log.parent.mkdir()
            log.write_text(json.dumps({"routing_decision": ["not", "a", "mapping"]}))
            stderr = io.StringIO()

            with contextlib.redirect_stderr(stderr):
                shell.onecmd("history")

            self.assertIn("could not read execution history", stderr.getvalue())

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

    def test_recent_and_show_report_the_final_escalated_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            shell = OrchestratorShell()
            shell.workspace = Path(directory)
            log = shell.workspace / ".orchestrator" / "executions.jsonl"
            log.parent.mkdir()
            primary = {
                "execution_id": "execution-1",
                "attempt_id": "attempt-1",
                "parent_attempt_id": None,
                "agent_id": "codex",
                "status": "failed",
                "duration_ms": 500,
                "task": {"description": "Escalated task"},
            }
            escalation = {
                **primary,
                "attempt_id": "attempt-2",
                "parent_attempt_id": "attempt-1",
                "agent_id": "claude-code",
                "status": "completed",
            }
            log.write_text(
                json.dumps(primary) + "\n" + json.dumps(escalation) + "\n",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                shell.onecmd("recent")
            self.assertEqual(len(stdout.getvalue().splitlines()), 1)
            self.assertIn(
                "#2 claude-code completed verify=not-run duration=0.5s attempts=2 — Escalated task",
                stdout.getvalue(),
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                shell.onecmd("show #2")
            self.assertIn("Execution: execution-1", stdout.getvalue())
            self.assertIn("Agent: claude-code", stdout.getvalue())
            self.assertIn("Status: completed", stdout.getvalue())
            self.assertIn("Attempts: 2", stdout.getvalue())

    def test_recent_matches_show_for_legacy_nested_only_escalation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            shell = OrchestratorShell()
            shell.workspace = Path(directory)
            log = shell.workspace / ".orchestrator" / "executions.jsonl"
            log.parent.mkdir()
            child = {
                "attempt_id": "attempt-2",
                "parent_attempt_id": "attempt-1",
                "agent_id": "claude-code",
                "status": "completed",
                "duration_ms": 750,
                "verification": {"status": "passed"},
            }
            primary = {
                "attempt_id": "attempt-1",
                "parent_attempt_id": None,
                "agent_id": "codex",
                "status": "failed",
                "duration_ms": 250,
                "verification": {"status": "failed"},
                "task": {"description": "Legacy recovery"},
                "escalation": {"record": child},
            }
            log.write_text(json.dumps(primary), encoding="utf-8")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                shell.onecmd("recent")
            self.assertIn(
                "#1 claude-code completed verify=passed duration=0.8s "
                "attempts=2 — Legacy recovery",
                stdout.getvalue(),
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                shell.onecmd("show #1")
            self.assertIn("Status: completed", stdout.getvalue())
            self.assertIn("Agent: claude-code", stdout.getvalue())
            self.assertIn("Attempts: 2", stdout.getvalue())

    def test_recent_groups_idless_standalone_child_with_nested_primary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            shell = OrchestratorShell()
            shell.workspace = Path(directory)
            log = shell.workspace / ".orchestrator" / "executions.jsonl"
            log.parent.mkdir()
            child = {
                "agent_id": "claude-code",
                "status": "completed",
                "duration_ms": 750,
                "verification": {"status": "passed"},
            }
            primary = {
                "agent_id": "codex",
                "status": "failed",
                "duration_ms": 250,
                "verification": {"status": "failed"},
                "task": {"description": "Legacy standalone recovery"},
                "escalation": {"record": dict(child)},
            }
            log.write_text(
                json.dumps(child) + "\n" + json.dumps(primary),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                shell.onecmd("recent")
            self.assertEqual(len(stdout.getvalue().splitlines()), 1)
            self.assertIn(
                "#2 claude-code completed verify=passed duration=0.8s "
                "attempts=2 — Legacy standalone recovery",
                stdout.getvalue(),
            )
            self.assertEqual(shell.complete_show("#", "show #", 5, 6), ["#2"])

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                shell.onecmd("show #2")
            self.assertIn("Status: completed", stdout.getvalue())
            self.assertIn("Attempts: 2", stdout.getvalue())

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

    def test_reset_delay_uses_a_resolution_the_number_actually_has(self) -> None:
        # Whole-day truncation showed every reset inside the next 24 hours as
        # "0d", which reads as "already reset" exactly when the wait matters.
        shell = OrchestratorShell()
        self.assertEqual(shell._format_reset_delay(5 * 86400), "5d")
        self.assertEqual(shell._format_reset_delay(86400), "1d")
        self.assertEqual(shell._format_reset_delay(5 * 3600), "5h")
        self.assertEqual(shell._format_reset_delay(90 * 60), "1h")
        self.assertEqual(shell._format_reset_delay(120), "2m")
        self.assertEqual(shell._format_reset_delay(5), "under a minute")

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

    def test_project_history_read_error_does_not_escape_usage_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            shell = OrchestratorShell()
            shell.workspace = Path(directory)
            log = shell.workspace / ".orchestrator" / "executions.jsonl"
            log.mkdir(parents=True)
            stdout = io.StringIO()
            with (
                patch("adaptive_orchestrator.interfaces.shell.read_codex_usage", return_value=None),
                patch("adaptive_orchestrator.interfaces.shell.read_claude_subscription", return_value="pro"),
                contextlib.redirect_stdout(stdout),
            ):
                shell.onecmd("usage")

            output = stdout.getvalue()
            self.assertIn("Codex: usage data not available", output)
            self.assertIn("Claude Code: project usage data not available", output)

    def test_invalid_utf8_project_history_does_not_escape_usage_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            shell = OrchestratorShell()
            shell.workspace = Path(directory)
            log = shell.workspace / ".orchestrator" / "executions.jsonl"
            log.parent.mkdir()
            log.write_bytes(b"\xff\xfe\n")
            stdout = io.StringIO()
            with (
                patch("adaptive_orchestrator.interfaces.shell.read_codex_usage", return_value=None),
                patch("adaptive_orchestrator.interfaces.shell.read_claude_subscription", return_value="pro"),
                contextlib.redirect_stdout(stdout),
            ):
                shell.onecmd("usage")

            self.assertIn("Claude Code: project usage data not available", stdout.getvalue())


class ShellEntryPointArgumentTests(unittest.TestCase):
    """The console script used to discard everything handed to it."""

    def test_workspace_option_selects_the_session_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "repo"
            workspace.mkdir()
            self.assertEqual(
                shell_interface._parse_shell_arguments(["--workspace", str(workspace)]),
                workspace.resolve(),
            )

    def test_no_arguments_still_means_the_current_directory(self) -> None:
        self.assertEqual(shell_interface._parse_shell_arguments([]), Path.cwd().resolve())

    def test_a_workspace_that_is_not_a_directory_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "notes.txt"
            target.write_text("x", encoding="utf-8")
            for value, expected in ((Path(directory) / "typo", "does not exist"), (target, "not a directory")):
                with self.subTest(value=value), contextlib.redirect_stderr(io.StringIO()) as stderr:
                    with self.assertRaises(SystemExit) as raised:
                        shell_interface._parse_shell_arguments(["--workspace", str(value)])
                self.assertEqual(raised.exception.code, 2)
                self.assertIn(expected, stderr.getvalue())

    def test_an_unknown_option_is_an_error_rather_than_ignored(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            with self.assertRaises(SystemExit) as raised:
                shell_interface._parse_shell_arguments(["--nonsense"])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("unrecognized arguments", stderr.getvalue())

    def test_version_names_this_console_script(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            with self.assertRaises(SystemExit) as raised:
                shell_interface._parse_shell_arguments(["--version"])

        self.assertEqual(raised.exception.code, 0)
        self.assertIn(shell_interface.SHELL_PROGRAM_NAME, stdout.getvalue())

    def test_the_shell_still_constructs_without_a_workspace(self) -> None:
        self.assertEqual(shell_interface.OrchestratorShell().workspace, Path.cwd())


if __name__ == "__main__":
    unittest.main()
