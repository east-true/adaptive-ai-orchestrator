from __future__ import annotations

import argparse
import json
import shlex
from dataclasses import asdict
from pathlib import Path

from .agents import ClaudeCodeAgent, CodexAgent
from .domain import Capability, Priority, Task
from .escalation import EscalationPolicy
from .kernel import OrchestratorKernel
from .logging import JsonlExecutionLogger
from .history import ExecutionHistory
from .routing import AdaptiveRouter, TaskAnalyzer
from .verification import CommandVerifier
from .workflow import EngineeringWorkflow, execution_succeeded


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
    _add_workflow_arguments(run)

    run_plan = subparsers.add_parser("run-plan", help="run an explicit, ordered sequence of tasks from a JSON plan file")
    run_plan.add_argument(
        "plan_file",
        type=Path,
        help='JSON file: a list of task specs, each {"description", "objective", "constraints": [...], '
        '"capabilities": [...], "priority", "time_limit_seconds"}. Only description/objective are required.',
    )
    run_plan.add_argument("--workspace", type=Path, default=Path.cwd())
    run_plan.add_argument("--agent", choices=("auto", "claude-code", "codex"), default="auto")
    run_plan.add_argument("--continue-on-failure", action="store_true", help="Run every step even if an earlier one failed (default: stop at the first failure).")
    _add_workflow_arguments(run_plan)

    return parser


def _add_workflow_arguments(parser: argparse.ArgumentParser) -> None:
    """Verification and escalation flags shared by `run` and `run-plan` (the same policy applies to every step)."""
    parser.add_argument(
        "--verify-command",
        action="append",
        default=[],
        help="Command text parsed into argument tokens; never run through a shell. Repeatable: every check runs and the worst outcome wins.",
    )
    parser.add_argument("--verify-time-limit", type=float)
    parser.add_argument("--include-git-diff", action="store_true", help="Log the full workspace diff; use only when it contains no sensitive data.")
    parser.add_argument("--no-escalation", action="store_true", help="Disable escalating to a second agent on failure, high risk, or high uncertainty.")
    parser.add_argument("--escalation-risk-threshold", type=int, default=3, help="Minimum analyzed risk (0-5) that triggers escalation.")
    parser.add_argument("--escalation-uncertainty-threshold", type=int, default=3, help="Minimum analyzed uncertainty (0-5) that triggers escalation.")
    parser.add_argument("--escalation-difficulty-threshold", type=int, default=4, help="Minimum analyzed difficulty (1-5) that triggers escalation.")


def _task_from_spec(spec: dict) -> Task:
    """Builds a Task from one JSON plan-file entry; same field names as `run`'s flags, all but description/objective optional."""
    return Task(
        description=spec["description"],
        objective=spec["objective"],
        constraints=tuple(spec.get("constraints", ())),
        required_capabilities=tuple(Capability(item) for item in spec.get("capabilities", ())),
        priority=Priority(spec.get("priority", Priority.NORMAL.value)),
        time_limit_seconds=spec.get("time_limit_seconds"),
    )


def _load_plan(path: Path) -> list[Task]:
    specs = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(specs, list) or not specs:
        raise ValueError(f"Plan file must contain a non-empty JSON list of task specs: {path}")
    return [_task_from_spec(spec) for spec in specs]


def _build_workflow(args: argparse.Namespace, workspace: Path) -> EngineeringWorkflow:
    agents = (ClaudeCodeAgent(), CodexAgent())
    logger = JsonlExecutionLogger(workspace / ".orchestrator" / "executions.jsonl")
    kernel = OrchestratorKernel({agent.agent_id: agent for agent in agents}, logger, workspace, include_git_diff=args.include_git_diff)
    commands = [tuple(shlex.split(item)) for item in args.verify_command]
    verifier = CommandVerifier(commands[0] if commands else (), args.verify_time_limit, tuple(commands[1:]))
    router = AdaptiveRouter(TaskAnalyzer(), ExecutionHistory(workspace / ".orchestrator" / "executions.jsonl"))
    escalation_policy = None if args.no_escalation else EscalationPolicy(
        args.escalation_risk_threshold, args.escalation_uncertainty_threshold, args.escalation_difficulty_threshold
    )
    return EngineeringWorkflow(kernel, router, verifier, escalation_policy)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    workspace = args.workspace.resolve()
    workflow = _build_workflow(args, workspace)

    if args.command == "run-plan":
        tasks = _load_plan(args.plan_file)
        result = workflow.run_plan(tasks, args.agent, stop_on_failure=not args.continue_on_failure)
        print(json.dumps({"steps": [{"plan": asdict(step.plan), "execution": asdict(step.record)} for step in result.steps], "stopped_early": result.stopped_early}, default=str, indent=2))
        return 0 if result.succeeded else 1

    task = Task(
        description=args.description,
        objective=args.objective,
        constraints=tuple(args.constraint),
        required_capabilities=tuple(Capability(item) for item in args.capability),
        priority=Priority(args.priority),
        time_limit_seconds=args.time_limit,
    )
    plan, record = workflow.run(task, args.agent)
    print(json.dumps({"plan": asdict(plan), "execution": asdict(record)}, default=str, indent=2))
    return 0 if execution_succeeded(record) else 1


if __name__ == "__main__":
    raise SystemExit(main())
