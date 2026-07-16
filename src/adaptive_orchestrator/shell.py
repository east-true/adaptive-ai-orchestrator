from __future__ import annotations

import cmd
import shlex
import sys
from pathlib import Path

from . import cli
from .history import ExecutionHistory


class OrchestratorShell(cmd.Cmd):
    intro = "Adaptive Orchestrator shell. Type help or ? for commands."
    prompt = "adaptive-orchestrator> "

    def __init__(self) -> None:
        super().__init__()
        self.workspace = Path.cwd()
        self.agent = "auto"

    def do_workspace(self, arg: str) -> None:
        """Set or show the session workspace."""
        text = arg.strip()
        if not text:
            print(self.workspace)
            return
        self.workspace = Path(text).resolve()
        print(f"Workspace set to {self.workspace}")

    def do_agent(self, arg: str) -> None:
        """Set or show the session agent."""
        text = arg.strip()
        if not text:
            print(self.agent)
            return
        if text not in {"auto", "claude-code", "codex"}:
            print("Error: agent must be one of auto, claude-code, codex")
            return
        self.agent = text
        print(f"Agent set to {self.agent}")

    def do_run(self, arg: str) -> None:
        """Run one task through the existing CLI dispatch."""
        tokens = self._split(arg, "run")
        if tokens is None:
            return
        argv = ["run", "--workspace", str(self.workspace), "--agent", self.agent, *tokens]
        self._invoke_cli(argv, "run")

    def do_run_plan(self, arg: str) -> None:
        """Run a plan file through the existing CLI dispatch."""
        tokens = self._split(arg, "run_plan")
        if tokens is None:
            return
        if not tokens:
            print("Usage: run_plan <plan_file> [args...]")
            return
        argv = ["run-plan", tokens[0], "--workspace", str(self.workspace), "--agent", self.agent, *tokens[1:]]
        self._invoke_cli(argv, "run_plan")

    def do_plan_generate(self, arg: str) -> None:
        """Generate a plan file through the existing CLI dispatch."""
        tokens = self._split(arg, "plan_generate")
        if tokens is None:
            return
        if not tokens:
            print("Usage: plan_generate <request> [args...]")
            return
        argv = ["plan", "generate", tokens[0], "--workspace", str(self.workspace), "--agent", self.agent, *tokens[1:]]
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
        for agent_id in ("codex", "claude-code"):
            metrics = history.metrics_for(agent_id)
            print(self._format_history_line(agent_id, metrics.executions, metrics.success_rate, metrics.verification_pass_rate))

    def do_exit(self, arg: str) -> bool:
        """Exit the shell."""
        del arg
        return True

    def do_quit(self, arg: str) -> bool:
        """Exit the shell."""
        del arg
        return True

    def do_EOF(self, arg: str) -> bool:
        """Exit on end-of-file."""
        del arg
        print()
        return True

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
            print(f"Error: {label} failed with exit code {exc.code}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 - shell boundary: keep the loop alive on any failure.
            print(f"Error: {label} failed: {exc}", file=sys.stderr)

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


if __name__ == "__main__":
    OrchestratorShell().cmdloop()
