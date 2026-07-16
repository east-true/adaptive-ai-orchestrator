import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.shell import OrchestratorShell
from adaptive_orchestrator.usage import CodexUsage


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


class ShellCliDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.shell = OrchestratorShell()
        self.shell.workspace = Path("/tmp/session-workspace")
        self.shell.agent = "claude-code"

    def test_run_builds_expected_argv(self) -> None:
        with patch("adaptive_orchestrator.shell.cli.main") as main:
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

    def test_run_plan_builds_expected_argv(self) -> None:
        with patch("adaptive_orchestrator.shell.cli.main") as main:
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
        with patch("adaptive_orchestrator.shell.cli.main") as main:
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
        with patch("adaptive_orchestrator.shell.cli.main") as main:
            self.shell.onecmd("plan_validate plan.json")
        main.assert_called_once_with(["plan", "validate", "plan.json"])

    def test_memory_record_builds_expected_argv(self) -> None:
        with patch("adaptive_orchestrator.shell.cli.main") as main:
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
        with patch("adaptive_orchestrator.shell.cli.main") as main:
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
        with patch("adaptive_orchestrator.shell.cli.main", side_effect=[SystemExit(2), None]) as main:
            with contextlib.redirect_stderr(stderr):
                self.shell.onecmd('run --description "Build it" --objective "Ship it"')
                self.shell.onecmd('memory_search --keyword cache')
        self.assertEqual(main.call_count, 2)
        self.assertIn("Error: run failed with exit code 2", stderr.getvalue())

    def test_run_plan_without_plan_file_prints_usage_error(self) -> None:
        stdout = io.StringIO()
        with patch("adaptive_orchestrator.shell.cli.main") as main:
            with contextlib.redirect_stdout(stdout):
                self.shell.onecmd("run_plan")
        main.assert_not_called()
        self.assertIn("Usage: run_plan <plan_file>", stdout.getvalue())

    def test_plan_generate_without_request_prints_usage_error(self) -> None:
        stdout = io.StringIO()
        with patch("adaptive_orchestrator.shell.cli.main") as main:
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
            self.assertEqual(len(output), 2)
            self.assertIn("codex:", output[0])
            self.assertIn("claude-code:", output[1])
            self.assertTrue(all("no data yet" in line for line in output))


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
                patch("adaptive_orchestrator.shell.read_codex_usage", return_value=codex_usage),
                patch("adaptive_orchestrator.shell.read_claude_subscription", return_value=subscription),
                patch("adaptive_orchestrator.shell.time.time", return_value=1_700_000_000),
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
