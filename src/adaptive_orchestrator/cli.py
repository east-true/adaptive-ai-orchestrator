from __future__ import annotations

import argparse
import json
import shlex
from dataclasses import asdict
from pathlib import Path

from .agents import ClaudeCodeAgent, CodexAgent
from .domain import Capability, Priority, Task
from .kernel import OrchestratorKernel
from .logging import JsonlExecutionLogger
from .history import ExecutionHistory
from .routing import AdaptiveRouter, TaskAnalyzer
from .verification import CommandVerifier
from .workflow import EngineeringWorkflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one coding-agent task through the Orchestrator Kernel.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="plan, execute, and optionally verify one task")
    run.add_argument("--workspace", type=Path, default=Path.cwd())
    run.add_argument("--agent", choices=("auto", "claude-code", "codex"), default="auto")
    run.add_argument("--description", required=True)
    run.add_argument("--objective", required=True)
    run.add_argument("--capability", choices=[item.value for item in Capability], action="append", default=[])
    run.add_argument("--constraint", action="append", default=[])
    run.add_argument("--priority", choices=[item.value for item in Priority], default=Priority.NORMAL.value)
    run.add_argument("--time-limit", type=float)
    run.add_argument("--verify-command", help="Command text parsed into argument tokens; never run through a shell.")
    run.add_argument("--verify-time-limit", type=float)
    run.add_argument("--include-git-diff", action="store_true", help="Log the full workspace diff; use only when it contains no sensitive data.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    workspace = args.workspace.resolve()
    task = Task(
        description=args.description,
        objective=args.objective,
        constraints=tuple(args.constraint),
        required_capabilities=tuple(Capability(item) for item in args.capability),
        priority=Priority(args.priority),
        time_limit_seconds=args.time_limit,
    )
    agents = (ClaudeCodeAgent(), CodexAgent())
    logger = JsonlExecutionLogger(workspace / ".orchestrator" / "executions.jsonl")
    kernel = OrchestratorKernel({agent.agent_id: agent for agent in agents}, logger, workspace, include_git_diff=args.include_git_diff)
    verifier = CommandVerifier(tuple(shlex.split(args.verify_command)) if args.verify_command else (), args.verify_time_limit)
    router = AdaptiveRouter(TaskAnalyzer(), ExecutionHistory(workspace / ".orchestrator" / "executions.jsonl"))
    plan, record = EngineeringWorkflow(kernel, router, verifier).run(task, args.agent)
    print(json.dumps({"plan": asdict(plan), "execution": asdict(record)}, default=str, indent=2))
    return 0 if record.status.value == "completed" and record.verification and record.verification.status.value in {"passed", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
