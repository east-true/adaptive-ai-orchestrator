from __future__ import annotations

import argparse
import json
import shlex
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from .agents import default_agent_ids, default_agents
from .domain import Capability, MemoryEntry, MemoryEntryType, Priority, Task
from .escalation import EscalationPolicy
from .kernel import OrchestratorKernel
from .memory import EngineeringMemoryStore
from .logging import JsonlExecutionLogger
from .history import ExecutionHistory
from .routing import AdaptiveRouter, TaskAnalyzer
from .process_runner import SubprocessRunner
from .verification import CommandVerifier
from .workflow import EngineeringWorkflow, execution_succeeded


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one coding-agent task through the Orchestrator Kernel.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="plan, execute, and optionally verify one task")
    run.add_argument("--workspace", type=Path, default=Path.cwd())
    _add_agent_argument(run)
    run.add_argument("--description")
    run.add_argument("--description-file", type=Path)
    run.add_argument("--objective")
    run.add_argument("--objective-file", type=Path)
    run.add_argument("--capability", choices=[item.value for item in Capability], action="append", default=[])
    run.add_argument("--constraint", action="append", default=[])
    run.add_argument("--priority", choices=[item.value for item in Priority], default=Priority.NORMAL.value)
    run.add_argument("--time-limit", type=float)
    _add_workflow_arguments(run)
    run.set_defaults(_parser=run)

    run_plan = subparsers.add_parser("run-plan", help="run an explicit, ordered sequence of tasks from a JSON plan file")
    run_plan.add_argument(
        "plan_file",
        type=Path,
        help='JSON file: a list of task specs, each {"description", "objective", "constraints": [...], '
        '"capabilities": [...], "priority", "time_limit_seconds"}. Only description/objective are required.',
    )
    run_plan.add_argument("--workspace", type=Path, default=Path.cwd())
    _add_agent_argument(run_plan)
    run_plan.add_argument("--continue-on-failure", action="store_true", help="Run every step even if an earlier one failed (default: stop at the first failure).")
    _add_workflow_arguments(run_plan)

    plan = subparsers.add_parser("plan", help="generate or validate a JSON plan file")
    plan_subparsers = plan.add_subparsers(dest="plan_command", required=True)

    plan_validate = plan_subparsers.add_parser("validate", help="validate a JSON plan file against the CLI plan schema")
    plan_validate.add_argument("plan_file", type=Path, help="JSON file containing a non-empty array of task specs.")

    plan_generate = plan_subparsers.add_parser("generate", help="generate a JSON plan file from a human request")
    plan_generate.add_argument("request", help="The vague human request to turn into an ordered plan.")
    plan_generate.add_argument("--workspace", type=Path, default=Path.cwd())
    plan_generate.add_argument("--output", type=Path, default=None, help="Plan file to write; defaults to plan.json in the workspace.")
    _add_agent_argument(plan_generate)
    _add_workflow_arguments(plan_generate)

    memory = subparsers.add_parser("memory", help="record or query engineering memory")
    memory_subparsers = memory.add_subparsers(dest="memory_command", required=True)

    memory_record = memory_subparsers.add_parser("record", help="append one engineering memory entry")
    memory_record.add_argument("--workspace", type=Path, default=Path.cwd())
    memory_record.add_argument("--type", required=True, choices=[item.value.lower() for item in MemoryEntryType])
    memory_record.add_argument("--title", required=True)
    memory_record.add_argument("--summary", required=True)
    memory_record.add_argument("--rationale", default="")
    memory_record.add_argument("--alternative", action="append", default=[])
    memory_record.add_argument("--tag", action="append", default=[])
    memory_record.add_argument("--related-task", dest="related_task", default=None)

    memory_search = memory_subparsers.add_parser("search", help="query engineering memory entries")
    memory_search.add_argument("--workspace", type=Path, default=Path.cwd())
    memory_search.add_argument("--type", choices=[item.value.lower() for item in MemoryEntryType])
    memory_search.add_argument("--tag")
    memory_search.add_argument("--keyword")

    return parser


def _add_agent_argument(parser: argparse.ArgumentParser) -> None:
    """The --agent flag, shared by every subcommand that routes a task."""
    parser.add_argument("--agent", choices=("auto", *default_agent_ids()), default="auto")


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
    parser.add_argument("--verbose", action="store_true", help="Stream subprocess stdout to stderr while the CLI waits for completion.")


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


def _validate_plan_file(path: Path) -> tuple[bool, str | None]:
    try:
        _load_plan(path)
    except Exception as exc:  # noqa: BLE001 - deliberate CLI boundary: convert any parse failure into a one-line error.
        return False, f"Invalid plan file {path}: {exc}"
    return True, None


def _unexpected_modified_files(modified_files: Sequence[str], expected_relative_path: str) -> list[str]:
    return [item for item in modified_files if item != expected_relative_path]


def _build_plan_generation_task(request: str, workspace: Path, output_path: Path) -> Task:
    valid_capabilities = ", ".join(item.value for item in Capability)
    valid_priorities = ", ".join(item.value for item in Priority)
    description = (
        "Inspect the repository as needed to understand it.\n"
        f"Human request: {request}\n"
        f"Workspace: {workspace}\n"
        f"Resolved output path: {output_path}\n\n"
        f"Write only a JSON array to {output_path}. Never modify any other file.\n"
        "Break the request into as many ordered steps as are genuinely warranted; one step is acceptable if that is sufficient.\n"
        "Each array element must be an object with exactly this schema:\n"
        '- description: string, required\n'
        '- objective: string, required\n'
        '- constraints: array of strings, optional\n'
        f"- capabilities: array of strings, optional; valid values: {valid_capabilities}\n"
        f"- priority: string, optional; valid values: {valid_priorities}\n"
        "- time_limit_seconds: number or null, optional\n"
    )
    objective = f"Write a valid JSON plan array to {output_path} for this request: {request}"
    constraints = (
        f"Write only the JSON array to {output_path}.",
        "Do not modify any file other than the resolved output path.",
        "Create parent directories for the output path if needed.",
    )
    return Task(
        description=description,
        objective=objective,
        constraints=constraints,
        required_capabilities=(Capability.REPOSITORY_UNDERSTANDING, Capability.PLANNING),
        context={"request": request, "workspace": str(workspace), "output_path": str(output_path)},
    )


def _memory_entry_from_args(args: argparse.Namespace) -> MemoryEntry:
    return MemoryEntry(
        entry_type=MemoryEntryType(args.type.upper()),
        title=args.title,
        summary=args.summary,
        rationale=args.rationale,
        alternatives_considered=tuple(args.alternative),
        tags=tuple(args.tag),
        related_task_description=args.related_task,
    )


def _memory_search_filters_from_args(args: argparse.Namespace) -> tuple[MemoryEntryType | None, str | None, str | None]:
    return (
        MemoryEntryType(args.type.upper()) if getattr(args, "type", None) else None,
        getattr(args, "tag", None),
        getattr(args, "keyword", None),
    )


def _resolve_text_argument(
    args: argparse.Namespace,
    value_name: str,
    file_name: str,
    label: str,
    parser: argparse.ArgumentParser | None = None,
) -> str:
    value = getattr(args, value_name, None)
    path = getattr(args, file_name, None)
    provided = sum(item is not None for item in (value, path))
    if provided != 1:
        message = f"exactly one of --{value_name.replace('_', '-')} or --{file_name.replace('_', '-')} must be provided for {label}"
        if parser is not None:
            parser.error(message)
        raise ValueError(message)
    if path is not None:
        text = path.read_text(encoding="utf-8")
        return text[:-1] if text.endswith("\n") else text
    return value


def _resolve_description(args: argparse.Namespace, parser: argparse.ArgumentParser | None = None) -> str:
    return _resolve_text_argument(args, "description", "description_file", "description", parser)


def _resolve_objective(args: argparse.Namespace, parser: argparse.ArgumentParser | None = None) -> str:
    return _resolve_text_argument(args, "objective", "objective_file", "objective", parser)


def _build_workflow(args: argparse.Namespace, workspace: Path) -> EngineeringWorkflow:
    agents = default_agents()
    logger = JsonlExecutionLogger(workspace / ".orchestrator" / "executions.jsonl")
    runner = SubprocessRunner(_verbose_output_callback(f"[{args.command}:{args.agent}]")) if args.verbose else SubprocessRunner()
    kernel = OrchestratorKernel({agent.agent_id: agent for agent in agents}, logger, workspace, runner=runner, include_git_diff=args.include_git_diff)
    commands = [tuple(shlex.split(item)) for item in args.verify_command]
    verifier = CommandVerifier(commands[0] if commands else (), args.verify_time_limit, tuple(commands[1:]))
    router = AdaptiveRouter(TaskAnalyzer(), ExecutionHistory(workspace / ".orchestrator" / "executions.jsonl"))
    escalation_policy = None if args.no_escalation else EscalationPolicy(
        args.escalation_risk_threshold, args.escalation_uncertainty_threshold, args.escalation_difficulty_threshold
    )
    return EngineeringWorkflow(kernel, router, verifier, escalation_policy)


def _verbose_output_callback(prefix: str):
    def write_line(line: str) -> None:
        sys.stderr.write(f"{prefix} {line}")
        sys.stderr.flush()

    return write_line


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # `plan validate` takes an explicit file path and has no --workspace of its own; it must be
    # handled before resolving args.workspace, which does not exist on its subparser's namespace.
    if args.command == "plan" and args.plan_command == "validate":
        valid, error = _validate_plan_file(args.plan_file)
        if not valid:
            print(error, file=sys.stderr)
            return 1
        tasks = _load_plan(args.plan_file)
        print(f"Valid plan file: {args.plan_file} ({len(tasks)} task(s))")
        return 0

    workspace = args.workspace.resolve()

    if args.command == "memory":
        store = EngineeringMemoryStore(workspace / ".orchestrator" / "memory.jsonl")
        if args.memory_command == "record":
            entry = _memory_entry_from_args(args)
            store.record(entry)
            print(json.dumps(asdict(entry), default=str, indent=2))
            return 0
        entry_type, tag, keyword = _memory_search_filters_from_args(args)
        entries = store.search(entry_type=entry_type, tag=tag, keyword=keyword)
        print(json.dumps([asdict(entry) for entry in entries], default=str, indent=2))
        return 0

    if args.command == "run-plan":
        workflow = _build_workflow(args, workspace)
        tasks = _load_plan(args.plan_file)
        result = workflow.run_plan(tasks, args.agent, stop_on_failure=not args.continue_on_failure)
        print(json.dumps({"steps": [{"plan": asdict(step.plan), "execution": asdict(step.record)} for step in result.steps], "stopped_early": result.stopped_early}, default=str, indent=2))
        return 0 if result.succeeded else 1

    if args.command == "plan":
        output = args.output or Path("plan.json")
        resolved_output = (workspace / output).resolve()
        validate_command = [sys.executable, "-m", "adaptive_orchestrator.cli", "plan", "validate", str(resolved_output)]
        args.verify_command = [shlex.join(validate_command), *args.verify_command]
        task = _build_plan_generation_task(args.request, workspace, resolved_output)
        workflow = _build_workflow(args, workspace)
        plan, record = workflow.run(task, args.agent)
        if not execution_succeeded(record):
            print(json.dumps({"plan": asdict(plan), "execution": asdict(record)}, default=str, indent=2))
            return 1
        try:
            tasks = _load_plan(resolved_output)
        except Exception as exc:  # noqa: BLE001 - the file should already have been validated; surface the failure cleanly if it changed.
            print(f"Generated plan could not be read back from {resolved_output}: {exc}", file=sys.stderr)
            return 1
        try:
            expected_relative_path = str(resolved_output.relative_to(workspace))
        except ValueError:
            expected_relative_path = str(resolved_output)
        unexpected = _unexpected_modified_files(record.workspace_modified_files, expected_relative_path)
        if unexpected:
            print(f"Warning: workspace modified files other than the generated plan: {', '.join(unexpected)}", file=sys.stderr)
        print(f"Plan written to {resolved_output}")
        print(f"Steps: {len(tasks)}")
        print(f"Next: PYTHONPATH=src python3 -m adaptive_orchestrator.cli run-plan {resolved_output} --workspace {workspace} ...")
        return 0

    run_parser = getattr(args, "_parser", None)
    workflow = _build_workflow(args, workspace)
    description = _resolve_description(args, run_parser)
    objective = _resolve_objective(args, run_parser)
    task = Task(
        description=description,
        objective=objective,
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
