from __future__ import annotations

import argparse
import json
import shlex
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from .agents import Agent, ClaudeCodeAgent, CodexAgent, default_agents
from .configuration import (
    ProjectConfig,
    ProjectConfigError,
    initialize_project_config,
    load_project_config,
)
from .diagnostics import diagnose_project, diagnostics_succeeded
from .domain import Capability, EvaluatorRole, EvaluatorSpec, MemoryEntry, MemoryEntryType, Priority, Task
from .escalation import EscalationPolicy
from .events import EventLogError, JsonlEventStore
from .kernel import OrchestratorKernel
from .memory import EngineeringMemoryStore
from .notifications import notify_execution
from .reporting import (
    ExecutionLookupError,
    ExecutionReportStore,
    render_markdown_report,
    render_text_summary,
    task_spec_for_retry,
)
from .logging import JsonlExecutionLogger
from .history import ExecutionHistory
from .paired_experiment import (
    PairedExperimentError,
    analyze_paired_observations,
    assign_pairs,
    load_paired_manifest,
    observations_from_routing_state,
    plan_paired_workspaces,
    prepare_paired_workspaces,
    validate_paired_environment,
)
from .paired_runner import PairedSmokeRunner
from .routing import TaskAnalyzer
from .routing_policy import RoutingPolicyRouter
from .routing_state import LifecycleRecorder, ReplayError, RoutingStateStore
from .state_paths import resolve_control_state_directory
from .replay import replay_digest, replay_event_log, summarize_attempts, validate_legacy_execution_log
from .process_runner import SubprocessRunner
from .verification import CommandVerifier, evaluator_content_version, validate_evaluator_artifacts
from .workflow import EngineeringWorkflow, execution_succeeded


def build_parser(config: ProjectConfig | None = None) -> argparse.ArgumentParser:
    config = config or ProjectConfig()
    parser = argparse.ArgumentParser(description="Run one coding-agent task through the Orchestrator Kernel.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="create a project config with detected verification commands")
    init.add_argument("--workspace", type=Path, default=Path.cwd())
    init.add_argument("--force", action="store_true", help="Replace an existing project config.")

    doctor = subparsers.add_parser("doctor", help="check project config, agent login, and runtime prerequisites")
    doctor.add_argument("--workspace", type=Path, default=Path.cwd())

    show = subparsers.add_parser("show", help="show a human-readable execution summary")
    show.add_argument("identifier", help="Execution ID, attempt ID, or legacy #number.")
    show.add_argument("--workspace", type=Path, default=Path.cwd())

    report = subparsers.add_parser("report", help="render a Markdown execution report")
    report.add_argument("identifier", help="Execution ID, attempt ID, or legacy #number.")
    report.add_argument("--workspace", type=Path, default=Path.cwd())
    report.add_argument("--output", type=Path, help="Write Markdown to this path instead of stdout.")
    report.add_argument("--include-diff", action="store_true", help="Include the recorded workspace diff when available.")
    report.add_argument("--force", action="store_true", help="Replace an existing output file.")

    retry = subparsers.add_parser("retry", help="run the task from a recorded execution again")
    retry.add_argument("identifier", help="Execution ID, attempt ID, or legacy #number.")
    retry.add_argument("--workspace", type=Path, default=Path.cwd())
    _add_agent_argument(retry, config)
    retry.set_defaults(agent="same")
    _add_workflow_arguments(retry, config)

    run = subparsers.add_parser("run", help="plan, execute, and optionally verify one task")
    run.add_argument("--workspace", type=Path, default=Path.cwd())
    _add_agent_argument(run, config)
    run.add_argument("--description")
    run.add_argument("--description-file", type=Path)
    run.add_argument("--objective")
    run.add_argument("--objective-file", type=Path)
    run.add_argument("--capability", choices=[item.value for item in Capability], action="append", default=[])
    run.add_argument("--constraint", action="append", default=[])
    run.add_argument("--priority", choices=[item.value for item in Priority], default=Priority.NORMAL.value)
    run.add_argument("--time-limit", type=float, default=config.time_limit_seconds)
    _add_workflow_arguments(run, config)
    run.set_defaults(_parser=run)

    run_plan = subparsers.add_parser("run-plan", help="run an explicit, ordered sequence of tasks from a JSON plan file")
    run_plan.add_argument(
        "plan_file",
        type=Path,
        help='JSON file: a list of task specs, each {"description", "objective", "constraints": [...], '
        '"capabilities": [...], "priority", "time_limit_seconds", "cost_limit_usd"}. '
        'Only description/objective are required.',
    )
    run_plan.add_argument("--workspace", type=Path, default=Path.cwd())
    _add_agent_argument(run_plan, config)
    run_plan.add_argument("--continue-on-failure", action="store_true", help="Run every step even if an earlier one failed (default: stop at the first failure).")
    _add_workflow_arguments(run_plan, config)

    plan = subparsers.add_parser("plan", help="generate or validate a JSON plan file")
    plan_subparsers = plan.add_subparsers(dest="plan_command", required=True)

    plan_validate = plan_subparsers.add_parser("validate", help="validate a JSON plan file against the CLI plan schema")
    plan_validate.add_argument("plan_file", type=Path, help="JSON file containing a non-empty array of task specs.")

    plan_generate = plan_subparsers.add_parser("generate", help="generate a JSON plan file from a human request")
    plan_generate.add_argument("request", help="The vague human request to turn into an ordered plan.")
    plan_generate.add_argument("--workspace", type=Path, default=Path.cwd())
    plan_generate.add_argument("--output", type=Path, default=None, help="Plan file to write; defaults to plan.json in the workspace.")
    _add_agent_argument(plan_generate, config)
    _add_workflow_arguments(plan_generate, config)

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

    replay = subparsers.add_parser("replay", help="validate lifecycle events and optionally rebuild derived routing state")
    replay.add_argument("--workspace", type=Path, default=Path.cwd())
    replay.add_argument("--control-state-dir", type=Path, help="Protected event/state directory; defaults to an XDG state path keyed by workspace.")
    replay.add_argument("--rebuild-state", action="store_true", help="Rewrite routing-state.json solely from the event log.")
    replay.add_argument(
        "--reconcile-incomplete",
        action="store_true",
        help="Append abandoned reconciliation events for non-live started attempts, then rebuild state.",
    )

    paired = subparsers.add_parser("paired", help="plan, validate, dry-run, or execute the Phase 2a paired smoke")
    paired_subparsers = paired.add_subparsers(dest="paired_command", required=True)

    paired_validate = paired_subparsers.add_parser("validate", help="validate a paired manifest and its pinned environment")
    paired_validate.add_argument("manifest", type=Path)
    paired_validate.add_argument("--source-repository", type=Path, default=Path.cwd())

    paired_plan = paired_subparsers.add_parser(
        "plan",
        help="project deterministic workspace identities without reading or creating them",
    )
    paired_plan.add_argument("manifest", type=Path)
    paired_plan.add_argument("--workspace-root", type=Path, required=True)

    paired_dry_run = paired_subparsers.add_parser(
        "dry-run",
        help="create and verify independent exact-base checkouts without invoking either agent",
    )
    paired_dry_run.add_argument("manifest", type=Path)
    paired_dry_run.add_argument("--source-repository", type=Path, default=Path.cwd())
    paired_dry_run.add_argument("--workspace-root", type=Path, required=True)

    paired_analyze = paired_subparsers.add_parser("analyze", help="project paired outcomes from a lifecycle event source")
    paired_analyze.add_argument("manifest", type=Path)
    paired_analyze.add_argument("--control-state-dir", type=Path, required=True)

    paired_run = paired_subparsers.add_parser(
        "run",
        help="execute a pre-registered paired smoke (requires explicit confirmation)",
    )
    paired_run.add_argument("manifest", type=Path)
    paired_run.add_argument("--source-repository", type=Path, default=Path.cwd())
    paired_run.add_argument("--workspace-root", type=Path, required=True)
    paired_run.add_argument("--control-state-dir", type=Path, required=True)
    paired_run.add_argument(
        "--confirm-agent-execution",
        action="store_true",
        help="explicitly allow the eight agent/evaluator attempts described by the manifest",
    )

    return parser


def _add_agent_argument(parser: argparse.ArgumentParser, config: ProjectConfig) -> None:
    """The --agent flag, shared by every subcommand that routes a task."""
    parser.add_argument("--agent", default=config.agent, help="Agent id from the configured registry, or auto.")
    parser.add_argument("--claude-model", default=config.claude_model)
    parser.add_argument("--codex-model", default=config.codex_model)
    parser.add_argument("--codex-reasoning-effort", default=config.codex_reasoning_effort)


def _add_workflow_arguments(parser: argparse.ArgumentParser, config: ProjectConfig) -> None:
    """Verification and escalation flags shared by `run` and `run-plan` (the same policy applies to every step)."""
    parser.add_argument(
        "--verify-command",
        action="append",
        default=list(config.verify_commands),
        help="Constraint command parsed into argument tokens; never run through a shell. Repeatable: every check runs and the worst outcome wins. It is not task-quality evidence.",
    )
    parser.add_argument("--verify-time-limit", type=float, default=config.verify_time_limit_seconds)
    parser.add_argument(
        "--quality-evaluator-command",
        action="append",
        default=[],
        help="Task-specific objective-quality command. Repeatable and shell-free; requires protected evaluator artifact(s).",
    )
    parser.add_argument(
        "--quality-evaluator-artifact",
        action="append",
        type=Path,
        default=[],
        help="Read-only evaluator or golden-fixture path outside the agent workspace. Repeatable and shared by quality commands.",
    )
    parser.add_argument("--quality-evaluator-time-limit", type=float)
    parser.add_argument(
        "--routing-policy",
        choices=("legacy", "static"),
        default="legacy",
        help="Active deterministic policy. 'static' is corrected L0 and requires an explicit baseline agent.",
    )
    parser.add_argument("--routing-baseline-agent", help="Configured baseline agent used by corrected static routing and its shadow.")
    parser.add_argument("--routing-shadow", action="store_true", help="Record execution-free baseline decisions without changing the selected agent.")
    parser.add_argument("--routing-seed", type=int, default=0, help="Seed used only for deterministic shadow assignments; exploration remains disabled.")
    parser.add_argument("--environment-epoch", default="default-v1", help="Version boundary for model/CLI/permission/cache evidence.")
    parser.add_argument("--control-state-dir", type=Path, help="Protected event/state directory outside the agent workspace.")
    parser.add_argument(
        "--include-git-diff",
        action=argparse.BooleanOptionalAction,
        default=config.include_git_diff,
        help="Log the full workspace diff; use only when it contains no sensitive data.",
    )
    escalation = parser.add_mutually_exclusive_group()
    escalation.add_argument("--escalation", dest="no_escalation", action="store_false", help="Enable escalation when warranted.")
    escalation.add_argument("--no-escalation", dest="no_escalation", action="store_true", help="Disable escalating to a second agent on failure, high risk, or high uncertainty.")
    parser.set_defaults(no_escalation=not config.escalation_enabled)
    parser.add_argument("--escalation-risk-threshold", type=int, default=config.escalation_risk_threshold, help="Minimum analyzed risk (0-5) that triggers escalation.")
    parser.add_argument("--escalation-uncertainty-threshold", type=int, default=config.escalation_uncertainty_threshold, help="Minimum analyzed uncertainty (0-5) that triggers escalation.")
    parser.add_argument("--escalation-difficulty-threshold", type=int, default=config.escalation_difficulty_threshold, help="Minimum analyzed difficulty (1-5) that triggers escalation.")
    parser.add_argument(
        "--verbose",
        action=argparse.BooleanOptionalAction,
        default=config.verbose,
        help="Stream subprocess stdout to stderr while the CLI waits for completion.",
    )


def _task_from_spec(spec: dict) -> Task:
    """Builds a Task from one JSON plan-file entry; same field names as `run`'s flags, all but description/objective optional."""
    return Task(
        description=spec["description"],
        objective=spec["objective"],
        constraints=tuple(spec.get("constraints", ())),
        required_capabilities=tuple(Capability(item) for item in spec.get("capabilities", ())),
        priority=Priority(spec.get("priority", Priority.NORMAL.value)),
        time_limit_seconds=spec.get("time_limit_seconds"),
        cost_limit_usd=spec.get("cost_limit_usd"),
        task_id=spec.get("task_id"),
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
        "- cost_limit_usd: non-negative number or null, optional\n"
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


def _configured_agents(args: argparse.Namespace) -> tuple[Agent, ...]:
    claude_model = getattr(args, "claude_model", None)
    codex_model = getattr(args, "codex_model", None)
    codex_reasoning_effort = getattr(args, "codex_reasoning_effort", None)
    if claude_model is None and codex_model is None and codex_reasoning_effort is None:
        return default_agents()
    return (
        ClaudeCodeAgent(model=claude_model),
        CodexAgent(model=codex_model, reasoning_effort=codex_reasoning_effort),
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
    agents = _configured_agents(args)
    logger = JsonlExecutionLogger(workspace / ".orchestrator" / "executions.jsonl")
    runner = SubprocessRunner(_verbose_output_callback(f"[{args.command}:{args.agent}]")) if args.verbose else SubprocessRunner()
    control_dir = resolve_control_state_directory(workspace, getattr(args, "control_state_dir", None))
    lifecycle = LifecycleRecorder(
        JsonlEventStore(control_dir / "events.jsonl"),
        RoutingStateStore(control_dir / "routing-state.json"),
    )
    kernel = OrchestratorKernel(
        {agent.agent_id: agent for agent in agents},
        logger,
        workspace,
        runner=runner,
        include_git_diff=args.include_git_diff,
        lifecycle_recorder=lifecycle,
    )
    commands = [tuple(shlex.split(item)) for item in args.verify_command]
    quality_specs = _quality_evaluator_specs(args, workspace)
    verifier = CommandVerifier(commands[0] if commands else (), args.verify_time_limit, tuple(commands[1:]), quality_specs)
    history = ExecutionHistory(workspace / ".orchestrator" / "executions.jsonl")
    router = RoutingPolicyRouter(
        getattr(args, "routing_policy", "legacy"),
        TaskAnalyzer(),
        history,
        baseline_agent_id=getattr(args, "routing_baseline_agent", None),
        shadow=bool(getattr(args, "routing_shadow", False)),
        seed=int(getattr(args, "routing_seed", 0)),
        environment_epoch=str(getattr(args, "environment_epoch", "default-v1")),
        objective_evaluator_available=bool(quality_specs),
        constraint_evaluator_count=len(commands),
        routing_state_provider=lifecycle.rebuild_state,
    )
    escalation_policy = None if args.no_escalation else EscalationPolicy(
        args.escalation_risk_threshold, args.escalation_uncertainty_threshold, args.escalation_difficulty_threshold
    )
    return EngineeringWorkflow(kernel, router, verifier, escalation_policy)


def _quality_evaluator_specs(args: argparse.Namespace, workspace: Path) -> tuple[EvaluatorSpec, ...]:
    command_texts = tuple(getattr(args, "quality_evaluator_command", ()) or ())
    configured_artifacts = tuple(getattr(args, "quality_evaluator_artifact", ()) or ())
    if not command_texts:
        if configured_artifacts:
            raise ValueError("--quality-evaluator-artifact requires --quality-evaluator-command.")
        return ()
    artifact_paths = tuple(str(path.expanduser().resolve()) for path in configured_artifacts)
    validate_evaluator_artifacts(artifact_paths, workspace)
    commands = tuple(tuple(shlex.split(item)) for item in command_texts)
    if any(not command for command in commands):
        raise ValueError("Quality evaluator commands cannot be empty.")
    artifact_roots = tuple(Path(path) for path in artifact_paths)
    for command in commands:
        referenced_paths = []
        for token in command:
            candidate = Path(token).expanduser()
            if candidate.is_absolute() and candidate.exists():
                referenced_paths.append(candidate.resolve())
        if not any(candidate == root or candidate.is_relative_to(root) for candidate in referenced_paths for root in artifact_roots):
            raise ValueError("Every quality evaluator command must directly reference a protected artifact path.")

    timeout = getattr(args, "quality_evaluator_time_limit", None)
    specs = []
    for index, command in enumerate(commands, start=1):
        version = evaluator_content_version(command, artifact_paths)
        specs.append(EvaluatorSpec(
            evaluator_id=f"quality-command-{index}",
            version=version,
            role=EvaluatorRole.QUALITY,
            subject="task objective",
            command=command,
            timeout_seconds=timeout,
            evidence_scope="Task-specific objective-quality command with protected external artifacts.",
            artifact_paths=artifact_paths,
        ))
    return tuple(specs)


def _build_workflow_for_cli(args: argparse.Namespace, workspace: Path) -> EngineeringWorkflow | None:
    try:
        return _build_workflow(args, workspace)
    except (EventLogError, ReplayError, OSError, ValueError) as exc:
        print(f"Workflow configuration failed: {exc}", file=sys.stderr)
        return None


def _verbose_output_callback(prefix: str):
    def write_line(line: str) -> None:
        sys.stderr.write(f"{prefix} {line}")
        sys.stderr.flush()

    return write_line


def _workspace_from_argv(argv: Sequence[str]) -> Path:
    for index, item in enumerate(argv):
        if item == "--workspace" and index + 1 < len(argv):
            return Path(argv[index + 1]).expanduser()
        if item.startswith("--workspace="):
            return Path(item.partition("=")[2]).expanduser()
    return Path.cwd()


def _config_for_argv(argv: Sequence[str]) -> ProjectConfig:
    if not argv or argv[0] not in {"run", "run-plan", "plan", "retry"}:
        return ProjectConfig()
    if len(argv) > 1 and argv[0] == "plan" and argv[1] == "validate":
        return ProjectConfig()
    return load_project_config(_workspace_from_argv(argv))


def _execution_store(workspace: Path) -> ExecutionReportStore:
    return ExecutionReportStore(workspace.resolve() / ".orchestrator" / "executions.jsonl")


def _write_report(path: Path, content: str, force: bool) -> None:
    path = path.expanduser().resolve()
    if path.exists() and not force:
        raise FileExistsError(f"Report already exists: {path} (use --force to replace it)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _deliver_notifications(record: object, config: ProjectConfig) -> None:
    if not config.notify_terminal_bell and not config.notify_desktop:
        return
    payload = asdict(record) if not isinstance(record, dict) else record
    for result in notify_execution(
        payload,
        terminal_bell=config.notify_terminal_bell,
        desktop=config.notify_desktop,
    ):
        if not result.delivered:
            print(f"Notification warning ({result.channel}): {result.detail}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    try:
        config = _config_for_argv(raw_argv)
    except ProjectConfigError as exc:
        print(f"Invalid project config: {exc}", file=sys.stderr)
        return 2
    parser = build_parser(config)
    args = parser.parse_args(raw_argv)

    if args.command == "init":
        try:
            path, commands = initialize_project_config(args.workspace, args.force)
        except ProjectConfigError as exc:
            print(f"Init failed: {exc}", file=sys.stderr)
            return 1
        print(f"Project config written to {path}")
        if commands:
            print(f"Detected verification command(s): {', '.join(commands)}")
        else:
            print("No verification command detected; edit the verification.commands list before relying on verification.")
        return 0

    if args.command == "doctor":
        checks = diagnose_project(args.workspace)
        for check in checks:
            print(f"[{check.status}] {check.name}: {check.detail}")
        return 0 if diagnostics_succeeded(checks) else 1

    if args.command in {"show", "report"}:
        try:
            bundle = _execution_store(args.workspace).find(args.identifier)
            if args.command == "show":
                print(render_text_summary(bundle))
                return 0
            content = render_markdown_report(bundle, include_diff=args.include_diff)
            if args.output is None:
                print(content, end="")
            else:
                _write_report(args.output, content, args.force)
                print(f"Report written to {args.output.expanduser().resolve()}")
            return 0
        except (ExecutionLookupError, OSError, FileExistsError) as exc:
            print(f"{args.command.capitalize()} failed: {exc}", file=sys.stderr)
            return 1

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

    if args.command == "paired":
        return _run_paired_command(args)

    workspace = args.workspace.resolve()

    if args.command == "retry":
        try:
            bundle = _execution_store(workspace).find(args.identifier)
            task = _task_from_spec(task_spec_for_retry(bundle))
        except (ExecutionLookupError, KeyError, TypeError, ValueError) as exc:
            print(f"Retry failed: {exc}", file=sys.stderr)
            return 1
        requested_agent = bundle.primary.get("agent_id") if args.agent == "same" else args.agent
        if not isinstance(requested_agent, str):
            print("Retry failed: the original agent is not recorded; use --agent auto", file=sys.stderr)
            return 1
        workflow = _build_workflow(args, workspace)
        try:
            plan, record = workflow.run(task, requested_agent)
        except (KeyError, ValueError) as exc:
            print(f"Retry failed: {exc}; use --agent auto or configure the original model variant", file=sys.stderr)
            return 1
        print(json.dumps({"plan": asdict(plan), "execution": asdict(record)}, default=str, indent=2))
        _deliver_notifications(record, config)
        return 0 if execution_succeeded(record) else 1

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

    if args.command == "replay":
        try:
            control_dir = resolve_control_state_directory(workspace, args.control_state_dir)
            event_path = control_dir / "events.jsonl"
            if args.reconcile_incomplete:
                before_events = JsonlEventStore(event_path).read()
                recorder = LifecycleRecorder(JsonlEventStore(event_path))
                state = recorder.rebuild_state()
                after_events = JsonlEventStore(event_path).read()
                reconciled_count = sum(
                    event.event_type.value == "execution_reconciled" for event in after_events
                ) - sum(event.event_type.value == "execution_reconciled" for event in before_events)
            else:
                state = replay_event_log(event_path)
                reconciled_count = 0
                if args.rebuild_state:
                    RoutingStateStore(control_dir / "routing-state.json").write(state)
        except (EventLogError, ReplayError, OSError, ValueError) as exc:
            print(f"Replay failed: {exc}", file=sys.stderr)
            return 1
        summary = summarize_attempts(state)
        legacy_report = validate_legacy_execution_log(workspace / ".orchestrator" / "executions.jsonl")
        print(json.dumps({
            "event_count": len(state.applied_event_ids),
            "execution_count": len(state.executions),
            "attempt_count": summary.attempt_count,
            "finalized_attempt_count": summary.finalized_attempt_count,
            "incomplete_attempt_count": summary.incomplete_attempt_count,
            "attempt_status_counts": summary.attempt_status_counts,
            "reconciled_count": reconciled_count,
            "replay_digest": replay_digest(state),
            "state_rebuilt": bool(args.rebuild_state or args.reconcile_incomplete),
            "legacy_execution_log": legacy_report.as_dict(),
        }, indent=2))
        return 0

    if args.command == "run-plan":
        workflow = _build_workflow_for_cli(args, workspace)
        if workflow is None:
            return 2
        tasks = _load_plan(args.plan_file)
        result = workflow.run_plan(tasks, args.agent, stop_on_failure=not args.continue_on_failure)
        print(json.dumps({"steps": [{"plan": asdict(step.plan), "execution": asdict(step.record)} for step in result.steps], "stopped_early": result.stopped_early}, default=str, indent=2))
        if result.steps:
            _deliver_notifications(result.steps[-1].record, config)
        return 0 if result.succeeded else 1

    if args.command == "plan":
        output = args.output or Path("plan.json")
        resolved_output = (workspace / output).resolve()
        validate_command = [sys.executable, "-m", "adaptive_orchestrator.cli", "plan", "validate", str(resolved_output)]
        args.verify_command = [shlex.join(validate_command), *args.verify_command]
        task = _build_plan_generation_task(args.request, workspace, resolved_output)
        workflow = _build_workflow_for_cli(args, workspace)
        if workflow is None:
            return 2
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
        _deliver_notifications(record, config)
        return 0

    run_parser = getattr(args, "_parser", None)
    workflow = _build_workflow_for_cli(args, workspace)
    if workflow is None:
        return 2
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
    _deliver_notifications(record, config)
    return 0 if execution_succeeded(record) else 1


def _run_paired_command(args: argparse.Namespace) -> int:
    try:
        manifest_path = args.manifest.expanduser().resolve(strict=True)
        manifest = load_paired_manifest(manifest_path)
        if args.paired_command == "plan":
            report = plan_paired_workspaces(manifest, args.workspace_root)
            print(json.dumps(report, sort_keys=True, separators=(",", ":")))
            return 0
        if args.paired_command == "validate":
            environment = validate_paired_environment(manifest, manifest_path, args.source_repository)
            print(json.dumps({
                "valid": True,
                "schema_version": manifest.schema_version,
                "experiment_id": manifest.experiment_id,
                "task_count": len(manifest.tasks),
                "execution_count": manifest.maximum_executions,
                "environment": environment,
                "assignments": [assignment.as_dict() for assignment in assign_pairs(manifest)],
            }, indent=2))
            return 0
        if args.paired_command == "dry-run":
            report = prepare_paired_workspaces(
                manifest,
                manifest_path,
                args.source_repository,
                args.workspace_root,
            )
            print(json.dumps(report, indent=2))
            return 0
        if args.paired_command == "analyze":
            state = replay_event_log(args.control_state_dir.expanduser().resolve() / "events.jsonl")
            observations = observations_from_routing_state(manifest, state)
            print(json.dumps(analyze_paired_observations(manifest, observations), indent=2))
            return 0
        if args.paired_command == "run":
            report = PairedSmokeRunner(
                manifest,
                manifest_path,
                args.source_repository,
                args.workspace_root,
                args.control_state_dir,
            ).run(confirm_agent_execution=args.confirm_agent_execution)
            print(json.dumps(report, indent=2))
            return 0
        raise PairedExperimentError(f"Unsupported paired command: {args.paired_command}")
    except (EventLogError, OSError, PairedExperimentError, ReplayError, ValueError) as exc:
        print(f"Paired experiment failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
