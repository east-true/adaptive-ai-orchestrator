from __future__ import annotations

import cmd
import difflib
import math
import signal
import shlex
import sys
import time
from importlib import metadata
from pathlib import Path

from adaptive_orchestrator.execution.agents import ClaudeCodeAgent, default_agent_ids
from adaptive_orchestrator.infrastructure.configuration import (
    ProjectConfigError,
    configured_agent_ids,
    load_project_config,
)
from adaptive_orchestrator.infrastructure.history import ExecutionHistory
from adaptive_orchestrator.interfaces import cli
from adaptive_orchestrator.operations.reporting import (
    ExecutionBundle,
    ExecutionLookupError,
    ExecutionReportStore,
)
from adaptive_orchestrator.operations.usage import CodexUsage, read_claude_subscription, read_codex_usage
from adaptive_orchestrator.orchestration.kernel import KERNEL_VERSION


class _ShellTermination(BaseException):
    """Unwind embedded CLI work when the shell receives a termination signal."""

    def __init__(self, signum: int) -> None:
        super().__init__(signum)
        self.signum = signum


def _source_tree_version() -> str | None:
    """Read this checkout's project version when the module lives in a source tree."""
    pyproject = Path(__file__).parents[3] / "pyproject.toml"
    try:
        lines = pyproject.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return None

    project_values: dict[str, str] = {}
    in_project = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_project = stripped == "[project]"
            continue
        key, separator, raw_value = stripped.partition("=")
        value = raw_value.strip()
        if (
            in_project
            and separator
            and len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            project_values[key.strip()] = value[1:-1]

    if project_values.get("name") != "adaptive-ai-orchestrator":
        return None
    return project_values.get("version")


def _package_version() -> str:
    """Return the active source release, then installed distribution metadata."""
    # Prefer a verified checkout over possibly stale installed metadata when
    # the documented ``PYTHONPATH=src`` development entry point is in use.
    source_version = _source_tree_version()
    if source_version:
        return source_version
    try:
        return metadata.version("adaptive-ai-orchestrator")
    except metadata.PackageNotFoundError:
        return "dev"


def _shell_banner(
    version: str | None = None,
    kernel_version: str = KERNEL_VERSION,
) -> str:
    """Render the compact, color-free startup wordmark."""
    resolved_version = version or _package_version()
    return "\n".join((
        "    _        _        ___",
        "   / \\      / \\      / _ \\",
        "  / _ \\    / _ \\    | | | |",
        " /_/ \\_\\  /_/ \\_\\    \\___/",
        "",
        " Adaptive AI Orchestrator",
        f" Shell v{resolved_version} | Kernel v{kernel_version}",
        " Type help or ?; task <request> starts a quick run.",
    ))


class OrchestratorShell(cmd.Cmd):
    intro = _shell_banner()
    prompt = "adaptive[auto]> "

    def __init__(self) -> None:
        super().__init__()
        self.workspace = Path.cwd()
        # None means the active workspace profile remains authoritative. An
        # explicit "auto" is distinct: it overrides a profile-pinned agent.
        self.agent_override: str | None = None
        self.default_verbose: bool | None = None
        self.default_no_escalation: bool | None = None
        self.default_time_limit: float | None = None
        self.default_time_limit_disabled = False
        self.default_verify_command: str | None = None
        self.default_verify_commands_disabled = False
        self._refresh_prompt()

    @property
    def agent(self) -> str:
        """Return the effective agent while preserving the original string API."""
        if self.agent_override is not None:
            return self.agent_override
        try:
            return load_project_config(self.workspace).agent
        except ProjectConfigError:
            return "invalid-profile"

    @agent.setter
    def agent(self, value: str | None) -> None:
        """Set the session override; assigning None restores profile inheritance."""
        self.agent_override = value

    def cmdloop(self, intro: str | None = None) -> None:
        """Run with shell completion and restore completer/delimiters afterward."""
        try:
            import readline
        except ImportError:
            return super().cmdloop(intro=intro)

        original_delimiters = readline.get_completer_delims()
        original_completer = readline.get_completer()
        readline.set_completer_delims(" \t\n")
        readline.set_completer(self.complete)
        try:
            return super().cmdloop(intro=intro)
        finally:
            readline.set_completer(original_completer)
            # readline state is process-global; restore it even when Ctrl-C
            # escapes cmd.Cmd's loop and main() starts the same shell again.
            readline.set_completer_delims(original_delimiters)

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

        try:
            workspace = self._resolve_workspace_path(tokens[0])
        except (OSError, RuntimeError) as exc:
            print(f"Error: could not resolve workspace: {exc}")
            return
        if not workspace.exists():
            print(f"Error: workspace does not exist: {workspace}")
            return
        if not workspace.is_dir():
            print(f"Error: workspace is not a directory: {workspace}")
            return

        self.workspace = workspace
        self._refresh_prompt()
        print(f"Workspace set to {self.workspace}")
        warning = self._agent_profile_warning()
        if warning is not None:
            print(f"Warning: {warning}")

    def do_cd(self, arg: str) -> None:
        """Alias for workspace."""
        self.do_workspace(arg)

    def do_agent(self, arg: str) -> None:
        """Set/show the session agent; use `agent inherit` for the workspace profile."""
        text = arg.strip()
        if not text:
            print(self._format_agent_state())
            return

        if text == "inherit":
            self.agent_override = None
            self._refresh_prompt()
            print(f"Agent set to {self._format_agent_state()}")
            return

        try:
            allowed = ("auto", *configured_agent_ids(load_project_config(self.workspace)))
        except ProjectConfigError as exc:
            print(f"Error: cannot select an agent until the project config is valid: {exc}")
            return
        if text not in allowed:
            print(f"Error: agent must be one of inherit, {', '.join(allowed)}")
            return
        self.agent_override = text
        self._refresh_prompt()
        print(f"Agent set to {self.agent_override}")

    def do_status(self, arg: str) -> None:
        """Show the current session workspace and agent."""
        del arg
        print(f"Workspace: {self.workspace}")
        print(f"Agent: {self._format_agent_state()}")

    def do_settings(self, arg: str) -> None:
        """Show session overrides applied to task and plan commands."""
        del arg
        print(f"Agent: {self._format_agent_state()}")
        print(f"Verbose: {self._format_toggle(self.default_verbose)}")
        print(f"No escalation: {self._format_toggle(self.default_no_escalation)}")
        if self.default_time_limit_disabled:
            time_limit = "off"
        elif self.default_time_limit is not None:
            time_limit = f"{self.default_time_limit:g}s"
        else:
            time_limit = "inherit"
        print(f"Time limit: {time_limit}")
        if self.default_verify_commands_disabled:
            verify = "off"
        else:
            verify = self.default_verify_command or "inherit"
        print(f"Verify command: {verify}")

    def do_set(self, arg: str) -> None:
        """Set a session default: verbose, no_escalation, time_limit, or verify."""
        text = arg.strip()
        parts = text.split(maxsplit=1)
        if len(parts) != 2:
            print("Usage: set <verbose|no_escalation|time_limit|verify> <value>")
            return
        name, value = parts

        if name in {"verbose", "no_escalation"}:
            if value.lower() in {"inherit", "unset", "default"}:
                if name == "verbose":
                    self.default_verbose = None
                else:
                    self.default_no_escalation = None
                print(f"{name} set to inherit")
                return
            enabled = self._parse_toggle(value)
            if enabled is None:
                print(f"Error: {name} must be on, off, or inherit")
                return
            if name == "verbose":
                self.default_verbose = enabled
            else:
                self.default_no_escalation = enabled
            print(f"{name} set to {self._format_toggle(enabled)}")
            return

        if name == "time_limit":
            normalized = value.lower()
            if normalized in {"off", "none"}:
                self.default_time_limit = None
                self.default_time_limit_disabled = True
                print("time_limit set to off")
                return
            if normalized in {"inherit", "unset", "default"}:
                self.default_time_limit = None
                self.default_time_limit_disabled = False
                print("time_limit set to inherit")
                return
            try:
                seconds = float(value)
            except ValueError:
                print("Error: time_limit must be a positive number, off, or inherit")
                return
            if not math.isfinite(seconds) or seconds <= 0:
                print("Error: time_limit must be a positive number, off, or inherit")
                return
            self.default_time_limit = seconds
            self.default_time_limit_disabled = False
            print(f"time_limit set to {seconds:g}s")
            return

        if name == "verify":
            normalized = value.lower()
            if normalized in {"off", "none"}:
                self.default_verify_command = None
                self.default_verify_commands_disabled = True
                print("verify set to off")
                return
            if normalized in {"inherit", "unset", "default"}:
                self.default_verify_command = None
                self.default_verify_commands_disabled = False
                print("verify set to inherit")
                return
            tokens = self._split(value, "set verify")
            if tokens is None:
                return
            # cli.py parses this value once more. Re-quoting the validated tokens
            # preserves their exact boundaries across that second shlex split.
            self.default_verify_command = shlex.join(tokens)
            self.default_verify_commands_disabled = False
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
            except KeyboardInterrupt:
                print("\nCompose cancelled")
                return
            except EOFError:
                print("\nCompose cancelled")
                return
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
            *self._agent_default_args(),
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
            *self._agent_default_args(),
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
            "--workspace",
            str(self.workspace),
            *self._agent_default_args(),
            *self._workflow_default_args(),
            *tokens,
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
            "--workspace",
            str(self.workspace),
            *self._agent_default_args(),
            *self._workflow_default_args(),
            *tokens,
        ]
        self._invoke_cli(argv, "plan_generate")

    def do_plan_validate(self, arg: str) -> None:
        """Validate a plan file through the existing CLI dispatch."""
        tokens = self._split(arg, "plan_validate")
        if tokens is None:
            return
        if len(tokens) != 1:
            print("Usage: plan_validate <plan_file>")
            return
        plan_file = tokens[0]
        if not plan_file.startswith("-"):
            try:
                plan_file = str(self._resolve_workspace_path(plan_file))
            except (OSError, RuntimeError) as exc:
                print(f"Error: plan_validate: could not resolve plan file: {exc}", file=sys.stderr)
                return
        self._invoke_cli(["plan", "validate", plan_file], "plan_validate")

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
        try:
            for agent_id in self._history_agent_ids(history):
                metrics = history.metrics_for(agent_id)
                print(
                    self._format_history_line(
                        agent_id,
                        metrics.executions,
                        metrics.success_rate,
                        metrics.verification_pass_rate,
                    )
                )
        except (OSError, UnicodeError, AttributeError, TypeError, ValueError) as exc:
            print(f"Error: could not read execution history: {exc}", file=sys.stderr)

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

        executions = self._indexed_execution_bundles()
        if executions is None:
            return
        if not executions:
            print("No executions logged yet")
            return
        for index, bundle in reversed(executions[-count:]):
            primary = bundle.primary
            displayed = {**primary, **bundle.outcome, "task": primary.get("task")}
            print(self._format_recent_execution(index, displayed, bundle.attempt_count))

    def do_show(self, arg: str) -> None:
        """Show one execution by id, attempt id, or the #number printed by recent."""
        tokens = self._split(arg, "show")
        if tokens is None:
            return
        if not tokens:
            print("Usage: show <execution-id|attempt-id|#number> [args...]")
            return
        self._invoke_cli(
            ["show", "--workspace", str(self.workspace), *tokens],
            "show",
        )

    def do_retry(self, arg: str) -> None:
        """Retry one execution by id, attempt id, or the #number printed by recent."""
        tokens = self._split(arg, "retry")
        if tokens is None:
            return
        if not tokens:
            print("Usage: retry <execution-id|attempt-id|#number> [args...]")
            return
        self._invoke_cli(
            [
                "retry",
                "--workspace",
                str(self.workspace),
                *self._agent_default_args(),
                *self._workflow_default_args(),
                *tokens,
            ],
            "retry",
        )

    def do_report(self, arg: str) -> None:
        """Render a Markdown report by execution id, attempt id, or recent #number."""
        tokens = self._split(arg, "report")
        if tokens is None:
            return
        if not tokens:
            print("Usage: report <execution-id|attempt-id|#number> [args...]")
            return
        self._invoke_cli(
            ["report", "--workspace", str(self.workspace), *tokens],
            "report",
        )

    def _history_agent_ids(self, history: ExecutionHistory) -> list[str]:
        # Registered agents always show, so a freshly added one reports "no data yet" instead of
        # vanishing; ids that exist only in the log still show, so past runs survive a rename.
        try:
            registered = list(configured_agent_ids(load_project_config(self.workspace)))
        except ProjectConfigError:
            registered = list(default_agent_ids())
        return registered + [item for item in history.agent_ids() if item not in registered]

    def do_usage(self, arg: str) -> None:
        """Show locally available account usage information."""
        del arg
        codex_usage = read_codex_usage()
        print(self._format_codex_usage(codex_usage))

        subscription = read_claude_subscription()
        try:
            metrics = ExecutionHistory(
                self.workspace / ".orchestrator" / "executions.jsonl"
            ).metrics_for_base(ClaudeCodeAgent.base_id)
        except (OSError, UnicodeError, AttributeError, TypeError, ValueError) as exc:
            print(f"Claude Code: project usage data not available ({exc})")
            return
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

    def postcmd(self, stop: bool, line: str) -> bool:
        """Refresh profile-derived prompt state before the next input."""
        del line
        self._refresh_prompt()
        return stop

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
        """Complete the active profile's exact registered agent ids."""
        del line, begidx, endidx
        try:
            available = (
                "auto",
                *configured_agent_ids(load_project_config(self.workspace)),
            )
        except ProjectConfigError:
            available = ()
        choices = ("inherit", *available)
        return [item for item in choices if item.startswith(text)]

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
            return [item for item in ("on", "off", "inherit") if item.startswith(text)]
        if len(words) == 2 and words[1] in {"time_limit", "verify"}:
            return [item for item in ("off", "inherit") if item.startswith(text)]
        return []

    def complete_workspace(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        """Complete directory names for workspace selection."""
        return self._complete_path(text, line, begidx, endidx, directories_only=True)

    def complete_cd(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        """Complete directory names for the workspace alias."""
        return self.complete_workspace(text, line, begidx, endidx)

    def complete_run_plan(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        """Complete plan file paths."""
        return self._complete_path(text, line, begidx, endidx)

    def complete_plan_validate(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        """Complete plan file paths."""
        return self._complete_path(text, line, begidx, endidx)

    def complete_show(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        """Complete the first execution identifier."""
        return self._complete_execution_identifier(text, line, begidx, endidx)

    def complete_retry(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        """Complete the first execution identifier."""
        return self._complete_execution_identifier(text, line, begidx, endidx)

    def complete_report(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        """Complete the first execution identifier."""
        return self._complete_execution_identifier(text, line, begidx, endidx)

    def help_run(self) -> None:
        """Show the existing CLI help for run."""
        self._show_cli_help("run", use_workspace=True)

    def help_show(self) -> None:
        """Show the existing CLI help for show."""
        self._show_cli_help("show")

    def help_retry(self) -> None:
        """Show the existing CLI help for retry."""
        self._show_cli_help("retry", use_workspace=True)

    def help_report(self) -> None:
        """Show the existing CLI help for report."""
        self._show_cli_help("report")

    def help_run_plan(self) -> None:
        """Show the existing CLI help for run-plan."""
        self._show_cli_help("run-plan", use_workspace=True)

    def help_plan_generate(self) -> None:
        """Show the existing CLI help for plan generate."""
        self._show_cli_help("plan", "generate", use_workspace=True)

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
        original_program = sys.argv[0]
        sys.argv[0] = "adaptive-orchestrator"
        try:
            exit_code = cli.main(argv)
            if isinstance(exit_code, int) and exit_code != 0:
                print(f"Error: {label} failed with exit code {exit_code}", file=sys.stderr)
        except KeyboardInterrupt:
            print(f"Interrupted: {label}", file=sys.stderr)
        except SystemExit as exc:
            if exc.code not in (None, 0):
                print(f"Error: {label} failed with exit code {exc.code}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 - shell boundary: keep the loop alive on any failure.
            print(f"Error: {label} failed: {exc}", file=sys.stderr)
        finally:
            sys.argv[0] = original_program

    def _show_cli_help(self, *command: str, use_workspace: bool = False) -> None:
        original_program = sys.argv[0]
        try:
            sys.argv[0] = "adaptive-orchestrator"
            try:
                argv = [*command]
                if use_workspace:
                    argv.extend(("--workspace", str(self.workspace)))
                cli.main([*argv, "--help"])
            except SystemExit as exc:
                if exc.code not in (None, 0):
                    print(f"Error: help failed with exit code {exc.code}", file=sys.stderr)
        finally:
            sys.argv[0] = original_program

    def _workflow_default_args(self, include_time_limit: bool = False) -> list[str]:
        argv: list[str] = []
        if self.default_verify_commands_disabled:
            argv.append("--clear-verify-commands")
        elif self.default_verify_command is not None:
            argv.extend(("--verify-command", self.default_verify_command))
        if self.default_no_escalation is True:
            argv.append("--no-escalation")
        elif self.default_no_escalation is False:
            argv.append("--escalation")
        if self.default_verbose is True:
            argv.append("--verbose")
        elif self.default_verbose is False:
            argv.append("--no-verbose")
        if include_time_limit:
            if self.default_time_limit_disabled:
                argv.append("--no-time-limit")
            elif self.default_time_limit is not None:
                argv.extend(("--time-limit", f"{self.default_time_limit:g}"))
        return argv

    def _agent_default_args(self) -> list[str]:
        if self.agent_override is None:
            return []
        return ["--agent", self.agent_override]

    def _complete_execution_identifier(
        self,
        text: str,
        line: str,
        begidx: int,
        endidx: int,
    ) -> list[str]:
        """Complete a command's first identifier from compatibility history."""
        del endidx
        try:
            preceding = shlex.split(line[:begidx])
        except ValueError:
            return []
        if len(preceding) != 1:
            return []

        executions = self._indexed_execution_bundles()
        if not executions:
            return []

        choices: list[str] = []
        seen: set[str] = set()

        def add(value: object) -> None:
            if isinstance(value, str) and value and value not in seen:
                seen.add(value)
                choices.append(value)

        for index, _bundle in reversed(executions):
            add(f"#{index}")

        for _index, bundle in reversed(executions):
            for record in reversed(bundle.attempts):
                add(record.get("execution_id"))
                add(record.get("attempt_id"))
        return [choice for choice in choices if choice.startswith(text)]

    def _indexed_execution_bundles(
        self,
    ) -> tuple[tuple[int, ExecutionBundle], ...] | None:
        path = self.workspace / ".orchestrator" / "executions.jsonl"
        try:
            indexed = ExecutionReportStore(path).indexed_bundles()
        except (ExecutionLookupError, OSError, UnicodeError) as exc:
            print(f"Error: could not read execution history: {exc}", file=sys.stderr)
            return None
        return tuple(sorted(indexed, key=lambda item: item[0]))

    @staticmethod
    def _format_recent_execution(
        index: int,
        record: dict[str, object],
        attempt_count: int = 1,
    ) -> str:
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
        attempt_suffix = f" attempts={attempt_count}" if attempt_count > 1 else ""
        suffix = f" — {summary}" if summary else ""
        return (
            f"#{index} {agent} {status} verify={verify_status} "
            f"duration={duration_seconds:.1f}s{attempt_suffix}{suffix}"
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
    def _format_toggle(value: bool | None) -> str:
        if value is None:
            return "inherit"
        return "on" if value else "off"

    def _format_agent_state(self) -> str:
        try:
            config = load_project_config(self.workspace)
        except ProjectConfigError as exc:
            if self.agent_override is None:
                return f"inherit (profile error: {exc})"
            return f"{self.agent_override} (session override; profile error: {exc})"

        if self.agent_override is None:
            return f"inherit (effective: {config.agent})"
        available = ("auto", *configured_agent_ids(config))
        if self.agent_override not in available:
            return f"{self.agent_override} (session override; unavailable in active profile)"
        return f"{self.agent_override} (session override)"

    def _agent_profile_warning(self) -> str | None:
        if self.agent_override is None:
            try:
                load_project_config(self.workspace)
            except ProjectConfigError as exc:
                return f"project config is invalid: {exc}"
            return None
        try:
            available = (
                "auto",
                *configured_agent_ids(load_project_config(self.workspace)),
            )
        except ProjectConfigError as exc:
            return f"project config is invalid: {exc}"
        if self.agent_override not in available:
            return (
                f"session agent {self.agent_override!r} is unavailable in this workspace; "
                "use 'agent inherit' or select one of "
                f"{', '.join(available)}"
            )
        return None

    def _refresh_prompt(self) -> None:
        workspace_label = self.workspace.name or str(self.workspace)
        self.prompt = f"adaptive[{self.agent}:{workspace_label}]> "

    def _resolve_workspace_path(self, value: str) -> Path:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = self.workspace / path
        return path.resolve()

    def _complete_path(
        self,
        text: str,
        line: str,
        begidx: int,
        endidx: int,
        directories_only: bool = False,
    ) -> list[str]:
        token_start = self._completion_token_start(line, endidx)
        raw_token = line[token_start:endidx] if token_start < begidx else text
        raw_prefix = line[token_start:begidx] if token_start < begidx else ""
        path_text = self._decode_partial_token(raw_token)
        values = self._path_completions(
            path_text,
            directories_only=directories_only,
            quote=False,
        )
        replacements = (
            self._completion_replacement(value, raw_token, raw_prefix)
            for value in values
        )
        return [replacement for replacement in replacements if replacement]

    @staticmethod
    def _completion_token_start(line: str, endidx: int) -> int:
        token_start = endidx
        in_token = False
        quote: str | None = None
        escaped = False
        for index, character in enumerate(line[:endidx]):
            if escaped:
                escaped = False
                continue
            if character == "\\" and quote != "'":
                if not in_token:
                    token_start = index
                    in_token = True
                escaped = True
                continue
            if quote is not None:
                if character == quote:
                    quote = None
                continue
            if character in {"'", '"'}:
                if not in_token:
                    token_start = index
                    in_token = True
                quote = character
            elif character.isspace():
                in_token = False
                token_start = index + 1
            elif not in_token:
                token_start = index
                in_token = True
        return token_start if in_token else endidx

    @staticmethod
    def _decode_partial_token(raw_token: str) -> str:
        decoded: list[str] = []
        quote: str | None = None
        escaped = False
        for character in raw_token:
            if escaped:
                decoded.append(character)
                escaped = False
            elif character == "\\" and quote != "'":
                escaped = True
            elif quote is not None:
                if character == quote:
                    quote = None
                else:
                    decoded.append(character)
            elif character in {"'", '"'}:
                quote = character
            else:
                decoded.append(character)
        if escaped:
            decoded.append("\\")
        return "".join(decoded)

    @staticmethod
    def _completion_replacement(value: str, raw_token: str, raw_prefix: str) -> str:
        del raw_token
        if not raw_prefix:
            return shlex.quote(value)

        decoded_prefix = OrchestratorShell._decode_partial_token(raw_prefix)
        if not value.startswith(decoded_prefix):
            # Readline replaces only begidx:endidx. Returning a whole, differently
            # spelled token here would duplicate the already typed prefix.
            return ""
        suffix = value[len(decoded_prefix):]
        quote = OrchestratorShell._partial_token_quote(raw_prefix)
        if quote == "'":
            return suffix.replace("'", "'\"'\"'") + "'"
        if quote == '"':
            return suffix.replace("\\", "\\\\").replace('"', '\\"') + '"'
        return "".join(
            f"\\{character}" if character.isspace() or character in "\\'\"" else character
            for character in suffix
        )

    @staticmethod
    def _partial_token_quote(raw_prefix: str) -> str | None:
        quote: str | None = None
        escaped = False
        for character in raw_prefix:
            if escaped:
                escaped = False
            elif character == "\\" and quote != "'":
                escaped = True
            elif quote is not None:
                if character == quote:
                    quote = None
            elif character in {"'", '"'}:
                quote = character
        return quote

    def _path_completions(
        self,
        text: str,
        directories_only: bool = False,
        quote: bool = True,
    ) -> list[str]:
        try:
            typed_path = Path(text).expanduser() if text else Path(".")
            lookup_path = typed_path if typed_path.is_absolute() else self.workspace / typed_path
            if not text or text.endswith("/"):
                directory = lookup_path
                prefix = ""
            else:
                directory = lookup_path.parent
                prefix = lookup_path.name
            matches = sorted(
                (item for item in directory.iterdir() if item.name.startswith(prefix)),
                key=lambda item: item.name,
            )
        except (OSError, RuntimeError):
            return []

        completions: list[str] = []
        for match in matches:
            if directories_only and not match.is_dir():
                continue
            if text.startswith("~") and "/" not in text:
                display = text
            else:
                slash = text.rfind("/")
                display_prefix = text[: slash + 1] if slash >= 0 else ""
                display = f"{display_prefix}{match.name}"
            if match.is_dir():
                display += "/"
            completions.append(shlex.quote(display) if quote else display)
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
    def terminate(signum: int, _frame: object) -> None:
        raise _ShellTermination(signum)

    # Agent processes run in an isolated POSIX session so cleanup can target
    # only this shell's process tree. Handle terminal hangup/quit as well as an
    # explicit terminate request; otherwise those isolated children could
    # outlive a shell whose terminal disappeared.
    termination_signals = tuple(dict.fromkeys(
        signum
        for name in ("SIGTERM", "SIGHUP", "SIGQUIT")
        if (signum := getattr(signal, name, None)) is not None
    ))
    installed_handlers: list[tuple[int, object]] = []
    try:
        for signum in termination_signals:
            original_handler = signal.getsignal(signum)
            signal.signal(signum, terminate)
            installed_handlers.append((signum, original_handler))

        shell = OrchestratorShell()
        intro: str | None = None
        while True:
            try:
                shell.cmdloop(intro=intro)
                return
            except KeyboardInterrupt:
                # Ctrl-C at the prompt clears the current input without discarding
                # session state or repeating the banner.
                print()
                intro = ""
    except _ShellTermination as exc:
        raise SystemExit(128 + exc.signum) from None
    finally:
        for signum, original_handler in reversed(installed_handlers):
            signal.signal(signum, original_handler)


if __name__ == "__main__":
    main()
