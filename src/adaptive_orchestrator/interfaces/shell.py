from __future__ import annotations

import cmd
import difflib
import json
import math
import shlex
import sys
import time
from pathlib import Path

from adaptive_orchestrator.execution.agents import ClaudeCodeAgent, default_agent_ids
from adaptive_orchestrator.infrastructure.history import ExecutionHistory
from adaptive_orchestrator.interfaces import cli
from adaptive_orchestrator.operations.usage import CodexUsage, read_claude_subscription, read_codex_usage


class OrchestratorShell(cmd.Cmd):
    intro = "Adaptive Orchestrator shell. Type help or ? for commands; task <request> for a quick run."
    prompt = "adaptive[auto]> "

    def __init__(self) -> None:
        super().__init__()
        self.workspace = Path.cwd()
        self.agent = "auto"
        self.default_verbose = False
        self.default_no_escalation = False
        self.default_time_limit: float | None = None
        self.default_verify_command: str | None = None
        self._refresh_prompt()

    def do_workspace(self, arg: str) -> None:
        """Set or show the session workspace."""
        text = arg.strip()
        if not text:
            print(self.workspace)
            return

        tokens = self._split(text, "workspace")
        if tokens is None:
            return
        if len(tokens) != 1:
            print("Usage: workspace <directory>")
            return

        workspace = Path(tokens[0]).expanduser().resolve()
        if not workspace.exists():
            print(f"Error: workspace does not exist: {workspace}")
            return
        if not workspace.is_dir():
            print(f"Error: workspace is not a directory: {workspace}")
            return

        self.workspace = workspace
        self._refresh_prompt()
        print(f"Workspace set to {self.workspace}")

    def do_cd(self, arg: str) -> None:
        """Alias for workspace."""
        self.do_workspace(arg)

    def do_agent(self, arg: str) -> None:
        """Set or show the session agent."""
        text = arg.strip()
        if not text:
            print(self.agent)
            return
        allowed = ("auto", *default_agent_ids())
        if text not in allowed:
            print(f"Error: agent must be one of {', '.join(allowed)}")
            return
        self.agent = text
        self._refresh_prompt()
        print(f"Agent set to {self.agent}")

    def do_status(self, arg: str) -> None:
        """Show the current session workspace and agent."""
        del arg
        print(f"Workspace: {self.workspace}")
        print(f"Agent: {self.agent}")

    def do_settings(self, arg: str) -> None:
        """Show defaults automatically applied to task and plan commands."""
        del arg
        print(f"Verbose: {self._format_toggle(self.default_verbose)}")
        print(f"No escalation: {self._format_toggle(self.default_no_escalation)}")
        time_limit = f"{self.default_time_limit:g}s" if self.default_time_limit is not None else "unset"
        print(f"Time limit: {time_limit}")
        print(f"Verify command: {self.default_verify_command or 'unset'}")

    def do_set(self, arg: str) -> None:
        """Set a session default: verbose, no_escalation, time_limit, or verify."""
        text = arg.strip()
        parts = text.split(maxsplit=1)
        if len(parts) != 2:
            print("Usage: set <verbose|no_escalation|time_limit|verify> <value>")
            return
        name, value = parts

        if name in {"verbose", "no_escalation"}:
            enabled = self._parse_toggle(value)
            if enabled is None:
                print(f"Error: {name} must be on or off")
                return
            if name == "verbose":
                self.default_verbose = enabled
            else:
                self.default_no_escalation = enabled
            print(f"{name} set to {self._format_toggle(enabled)}")
            return

        if name == "time_limit":
            if value.lower() in {"off", "unset", "none"}:
                self.default_time_limit = None
                print("time_limit unset")
                return
            try:
                seconds = float(value)
            except ValueError:
                print("Error: time_limit must be a positive number or off")
                return
            if not math.isfinite(seconds) or seconds <= 0:
                print("Error: time_limit must be a positive number or off")
                return
            self.default_time_limit = seconds
            print(f"time_limit set to {seconds:g}s")
            return

        if name == "verify":
            if value.lower() in {"off", "unset", "none"}:
                self.default_verify_command = None
                print("verify unset")
                return
            tokens = self._split(value, "set verify")
            if tokens is None:
                return
            # Quotes around the entire command are for shell input convenience, not part of
            # the command text that cli.py will parse again with shlex.split.
            self.default_verify_command = tokens[0] if len(tokens) == 1 else value
            print(f"verify set to {self.default_verify_command}")
            return

        print(f"Error: unknown setting: {name}")

    def do_task(self, arg: str) -> None:
        """Run a request using it as both the task description and objective."""
        request = arg.strip()
        if not request:
            print("Usage: task <request>")
            return
        self._run_task(request, "task")

    def do_compose(self, arg: str) -> None:
        """Compose a multiline task; finish with a line containing only a period."""
        if arg.strip():
            print("Usage: compose")
            return
        print("Enter request. Finish with a line containing only '.'")
        lines: list[str] = []
        while True:
            try:
                line = input("> ")
            except EOFError:
                print()
                break
            if line == ".":
                break
            lines.append(line)
        request = "\n".join(lines).strip()
        if not request:
            print("Compose cancelled: request was empty")
            return
        self._run_task(request, "compose")

    def _run_task(self, request: str, label: str) -> None:
        argv = [
            "run",
            "--workspace",
            str(self.workspace),
            "--agent",
            self.agent,
            *self._workflow_default_args(include_time_limit=True),
            "--description",
            request,
            "--objective",
            request,
        ]
        self._invoke_cli(argv, label)

    def do_run(self, arg: str) -> None:
        """Run one task through the existing CLI dispatch."""
        tokens = self._split(arg, "run")
        if tokens is None:
            return
        argv = [
            "run",
            "--workspace",
            str(self.workspace),
            "--agent",
            self.agent,
            *self._workflow_default_args(include_time_limit=True),
            *tokens,
        ]
        self._invoke_cli(argv, "run")

    def do_run_plan(self, arg: str) -> None:
        """Run a plan file through the existing CLI dispatch."""
        tokens = self._split(arg, "run_plan")
        if tokens is None:
            return
        if not tokens:
            print("Usage: run_plan <plan_file> [args...]")
            return
        argv = [
            "run-plan",
            tokens[0],
            "--workspace",
            str(self.workspace),
            "--agent",
            self.agent,
            *self._workflow_default_args(),
            *tokens[1:],
        ]
        self._invoke_cli(argv, "run_plan")

    def do_plan_generate(self, arg: str) -> None:
        """Generate a plan file through the existing CLI dispatch."""
        tokens = self._split(arg, "plan_generate")
        if tokens is None:
            return
        if not tokens:
            print("Usage: plan_generate <request> [args...]")
            return
        argv = [
            "plan",
            "generate",
            tokens[0],
            "--workspace",
            str(self.workspace),
            "--agent",
            self.agent,
            *self._workflow_default_args(),
            *tokens[1:],
        ]
        self._invoke_cli(argv, "plan_generate")

    def do_plan_validate(self, arg: str) -> None:
        """Validate a plan file through the existing CLI dispatch."""
        tokens = self._split(arg, "plan_validate")
        if tokens is None:
            return
        if not tokens:
            print("Usage: plan_validate <plan_file>")
            return
        self._invoke_cli(["plan", "validate", tokens[0]], "plan_validate")

    def do_memory_record(self, arg: str) -> None:
        """Record engineering memory through the existing CLI dispatch."""
        tokens = self._split(arg, "memory_record")
        if tokens is None:
            return
        argv = ["memory", "record", "--workspace", str(self.workspace), *tokens]
        self._invoke_cli(argv, "memory_record")

    def do_memory_search(self, arg: str) -> None:
        """Search engineering memory through the existing CLI dispatch."""
        tokens = self._split(arg, "memory_search")
        if tokens is None:
            return
        argv = ["memory", "search", "--workspace", str(self.workspace), *tokens]
        self._invoke_cli(argv, "memory_search")

    def do_history(self, arg: str) -> None:
        """Show per-agent execution history for the current workspace."""
        del arg
        history = ExecutionHistory(self.workspace / ".orchestrator" / "executions.jsonl")
        for agent_id in self._history_agent_ids(history):
            metrics = history.metrics_for(agent_id)
            print(self._format_history_line(agent_id, metrics.executions, metrics.success_rate, metrics.verification_pass_rate))

    def do_recent(self, arg: str) -> None:
        """Show recent executions for the current workspace (default: 5)."""
        text = arg.strip()
        try:
            count = int(text) if text else 5
        except ValueError:
            print("Usage: recent [count]")
            return
        if not 1 <= count <= 100:
            print("Error: recent count must be between 1 and 100")
            return

        records = self._read_execution_records()
        if not records:
            print("No executions logged yet")
            return
        first_index = max(0, len(records) - count)
        selected = list(enumerate(records[first_index:], start=first_index + 1))
        for index, record in reversed(selected):
            print(self._format_recent_execution(index, record))

    @staticmethod
    def _history_agent_ids(history: ExecutionHistory) -> list[str]:
        # Registered agents always show, so a freshly added one reports "no data yet" instead of
        # vanishing; ids that exist only in the log still show, so past runs survive a rename.
        registered = list(default_agent_ids())
        return registered + [item for item in history.agent_ids() if item not in registered]

    def do_usage(self, arg: str) -> None:
        """Show locally available account usage information."""
        del arg
        codex_usage = read_codex_usage()
        print(self._format_codex_usage(codex_usage))

        subscription = read_claude_subscription()
        metrics = ExecutionHistory(self.workspace / ".orchestrator" / "executions.jsonl").metrics_for_base(ClaudeCodeAgent.base_id)
        clauses = [f"{subscription} subscription"] if subscription is not None else []
        if metrics.cost_samples:
            noun = "execution" if metrics.cost_samples == 1 else "executions"
            clauses.append(
                f"logged in this project: ${metrics.total_cost_usd:.2f} across "
                f"{metrics.cost_samples} {noun} with cost data"
            )
        else:
            clauses.append("logged in this project: no cost data logged yet")
        print(f"Claude Code: {'; '.join(clauses)} (no live quota % available locally)")

    def do_exit(self, arg: str) -> bool:
        """Exit the shell."""
        del arg
        return True

    def do_quit(self, arg: str) -> bool:
        """Exit the shell."""
        del arg
        return True

    def do_q(self, arg: str) -> bool:
        """Exit the shell."""
        return self.do_quit(arg)

    def do_EOF(self, arg: str) -> bool:
        """Exit on end-of-file."""
        del arg
        print()
        return True

    def emptyline(self) -> None:
        """Do nothing instead of repeating a potentially expensive command."""
        return None

    def default(self, line: str) -> None:
        """Report unknown commands with a likely command name when available."""
        command = line.partition(" ")[0]
        commands = [
            name[3:]
            for name in self.get_names()
            if name.startswith("do_") and name != "do_EOF"
        ]
        matches = difflib.get_close_matches(command, commands, n=1, cutoff=0.6)
        suggestion = f" Did you mean '{matches[0]}'?" if matches else ""
        print(f"Unknown command: {command}.{suggestion} Type help or ? for commands.")

    def complete_agent(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        """Complete registered agent ids."""
        del line, begidx, endidx
        return [item for item in ("auto", *default_agent_ids()) if item.startswith(text)]

    def complete_set(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        """Complete setting names and toggle values."""
        del endidx
        words = line[:begidx].split()
        if len(words) <= 1:
            return [
                item
                for item in ("verbose", "no_escalation", "time_limit", "verify")
                if item.startswith(text)
            ]
        if len(words) == 2 and words[1] in {"verbose", "no_escalation"}:
            return [item for item in ("on", "off") if item.startswith(text)]
        if len(words) == 2 and words[1] in {"time_limit", "verify"}:
            return [item for item in ("off",) if item.startswith(text)]
        return []

    def complete_workspace(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        """Complete directory names for workspace selection."""
        del line, begidx, endidx
        return self._path_completions(text, directories_only=True)

    def complete_cd(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        """Complete directory names for the workspace alias."""
        return self.complete_workspace(text, line, begidx, endidx)

    def complete_run_plan(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        """Complete plan file paths."""
        del line, begidx, endidx
        return self._path_completions(text)

    def complete_plan_validate(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        """Complete plan file paths."""
        del line, begidx, endidx
        return self._path_completions(text)

    def help_run(self) -> None:
        """Show the existing CLI help for run."""
        self._show_cli_help("run")

    def help_run_plan(self) -> None:
        """Show the existing CLI help for run-plan."""
        self._show_cli_help("run-plan")

    def help_plan_generate(self) -> None:
        """Show the existing CLI help for plan generate."""
        self._show_cli_help("plan", "generate")

    def help_plan_validate(self) -> None:
        """Show the existing CLI help for plan validate."""
        self._show_cli_help("plan", "validate")

    def help_memory_record(self) -> None:
        """Show the existing CLI help for memory record."""
        self._show_cli_help("memory", "record")

    def help_memory_search(self) -> None:
        """Show the existing CLI help for memory search."""
        self._show_cli_help("memory", "search")

    def _split(self, arg: str, label: str) -> list[str] | None:
        try:
            return shlex.split(arg)
        except ValueError as exc:
            print(f"Error: {label}: {exc}", file=sys.stderr)
            return None

    def _invoke_cli(self, argv: list[str], label: str) -> None:
        try:
            cli.main(argv)
        except SystemExit as exc:
            if exc.code not in (None, 0):
                print(f"Error: {label} failed with exit code {exc.code}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 - shell boundary: keep the loop alive on any failure.
            print(f"Error: {label} failed: {exc}", file=sys.stderr)

    @staticmethod
    def _show_cli_help(*command: str) -> None:
        original_program = sys.argv[0]
        try:
            sys.argv[0] = "adaptive-orchestrator"
            try:
                cli.main([*command, "--help"])
            except SystemExit as exc:
                if exc.code not in (None, 0):
                    print(f"Error: help failed with exit code {exc.code}", file=sys.stderr)
        finally:
            sys.argv[0] = original_program

    def _workflow_default_args(self, include_time_limit: bool = False) -> list[str]:
        argv: list[str] = []
        if self.default_verify_command is not None:
            argv.extend(("--verify-command", self.default_verify_command))
        if self.default_no_escalation:
            argv.append("--no-escalation")
        if self.default_verbose:
            argv.append("--verbose")
        if include_time_limit and self.default_time_limit is not None:
            argv.extend(("--time-limit", f"{self.default_time_limit:g}"))
        return argv

    def _read_execution_records(self) -> list[dict[str, object]]:
        path = self.workspace / ".orchestrator" / "executions.jsonl"
        if not path.exists():
            return []
        records: list[dict[str, object]] = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            print(f"Error: could not read execution history: {exc}", file=sys.stderr)
            return []
        for line in lines:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                records.append(item)
        return records

    @staticmethod
    def _format_recent_execution(index: int, record: dict[str, object]) -> str:
        agent = record.get("agent_id") or "unknown-agent"
        status = record.get("status") or "unknown"
        verification = record.get("verification")
        verify_status = verification.get("status") if isinstance(verification, dict) else "not-run"
        try:
            duration_seconds = float(record.get("duration_ms") or 0) / 1000
        except (TypeError, ValueError):
            duration_seconds = 0
        task = record.get("task")
        description = task.get("description", "") if isinstance(task, dict) else ""
        summary = " ".join(str(description).split())
        if len(summary) > 72:
            summary = f"{summary[:69]}..."
        suffix = f" — {summary}" if summary else ""
        return (
            f"#{index} {agent} {status} verify={verify_status} "
            f"duration={duration_seconds:.1f}s{suffix}"
        )

    @staticmethod
    def _parse_toggle(value: str) -> bool | None:
        normalized = value.lower()
        if normalized in {"on", "true", "yes", "1"}:
            return True
        if normalized in {"off", "false", "no", "0"}:
            return False
        return None

    @staticmethod
    def _format_toggle(value: bool) -> str:
        return "on" if value else "off"

    def _refresh_prompt(self) -> None:
        workspace_label = self.workspace.name or str(self.workspace)
        self.prompt = f"adaptive[{self.agent}:{workspace_label}]> "

    @staticmethod
    def _path_completions(text: str, directories_only: bool = False) -> list[str]:
        typed_path = Path(text).expanduser() if text else Path(".")
        if text.endswith("/"):
            directory = typed_path
            prefix = ""
        else:
            directory = typed_path.parent
            prefix = typed_path.name

        try:
            matches = sorted(
                (item for item in directory.iterdir() if item.name.startswith(prefix)),
                key=lambda item: item.name,
            )
        except OSError:
            return []

        completions: list[str] = []
        for match in matches:
            if directories_only and not match.is_dir():
                continue
            if text.startswith("~"):
                home = str(Path("~").expanduser())
                display = str(match).replace(home, "~", 1)
            elif typed_path.is_absolute():
                display = str(match)
            else:
                display = str(Path(text).parent / match.name) if text else match.name
                if display.startswith("./"):
                    display = display[2:]
            if match.is_dir():
                display += "/"
            completions.append(shlex.quote(display))
        return completions

    def _format_history_line(
        self,
        agent_id: str,
        executions: int,
        success_rate: float | None,
        verification_pass_rate: float | None,
    ) -> str:
        if executions == 0:
            return f"{agent_id}: 0 executions, no data yet"
        noun = "execution" if executions == 1 else "executions"
        success_text = f"{self._format_percentage(success_rate)} success" if success_rate is not None else "no success data"
        verification_text = f"{self._format_percentage(verification_pass_rate)} verification pass" if verification_pass_rate is not None else "no verification data"
        return f"{agent_id}: {executions} {noun}, {success_text}, {verification_text}"

    def _format_percentage(self, value: float) -> str:
        return f"{round(value * 100)}%"

    def _format_codex_usage(self, usage: CodexUsage | None) -> str:
        if usage is None:
            return "Codex: usage data not available"
        clauses = []
        if usage.plan_type is not None:
            clauses.append(f"{usage.plan_type} plan")
        if usage.used_percent is not None:
            clauses.append(f"{usage.used_percent:g}% used")
        reset_text = ""
        if usage.resets_at is not None:
            seconds = usage.resets_at - time.time()
            if seconds >= 0:
                reset_text = f" (resets in {int(seconds // 86400)}d)"
        return f"Codex: {', '.join(clauses)}{reset_text}" if clauses else "Codex: usage data not available"


def main() -> None:
    OrchestratorShell().cmdloop()


if __name__ == "__main__":
    main()
