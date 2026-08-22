from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
from pathlib import Path
from time import monotonic
from typing import Callable, Mapping, Sequence

from adaptive_orchestrator.core.domain import ExecutionStatus, EvaluatorRole, EvaluatorSpec
from adaptive_orchestrator.execution.process_runner import (
    ProcessResult,
    ProcessRunner,
    SubprocessRunner,
)
from adaptive_orchestrator.execution.verification import (
    hash_evaluator_artifacts,
    validate_evaluator_artifacts,
)
from adaptive_orchestrator.experiments.paired_experiment import (
    PairedAgentSpec,
    PairedTaskSpec,
    analyze_paired_observations,
    assign_pairs,
    observations_from_routing_state,
    _git,
)
from adaptive_orchestrator.experiments.paired_runner import (
    PairedExecutionError,
    PairedSmokeRunner,
    _agent_from_spec,
    _installed_cli_version,
)
from adaptive_orchestrator.experiments.phase2b_pilot import (
    AUTHENTICATED_ISOLATED_AGENT_HOME_RESOLUTION,
    ISOLATED_AGENT_CREDENTIAL_PATHS,
    ISOLATED_AGENT_HOME_ENVIRONMENT_VARIABLES,
    Phase2bPilotManifest,
    audit_committed_manifest,
    load_run_authorization,
    mark_phase2b_analysis_non_promotional,
    validate_phase2b_dry_run_record,
    validate_phase2b_environment,
    validate_phase2b_execution_workspaces,
)
from adaptive_orchestrator.infrastructure.events import JsonlEventStore
from adaptive_orchestrator.routing.state import LifecycleRecorder


PHASE2B_RUN_SCHEMA = "phase2b-pilot-run-v1"


class _IsolatedAgentHomeProcessRunner:
    """Bind exactly the agent invocation to a fresh, empty per-attempt home."""

    def __init__(self, delegate: ProcessRunner, home: Path) -> None:
        self._delegate = delegate
        self._home = home
        self._agent_invocation_consumed = False

    def run(
        self,
        command: Sequence[str],
        cwd: Path,
        timeout_seconds: float | None,
    ) -> ProcessResult:
        if self._agent_invocation_consumed:
            return self._delegate.run(command, cwd, timeout_seconds)
        self._agent_invocation_consumed = True
        try:
            self._home.parent.mkdir(parents=True, exist_ok=True)
            if self._home.parent.is_symlink():
                raise OSError("isolated agent-home parent is a symlink")
            self._home.mkdir(mode=0o700, exist_ok=False)
        except OSError as exc:
            return ProcessResult(
                tuple(command),
                ExecutionStatus.SPAWN_ERROR,
                "",
                f"unable to create fresh isolated agent home: {exc}",
                None,
                0.0,
            )

        home = str(self._home)
        environment = {
            "HOME": home,
            "CLAUDE_CONFIG_DIR": str(self._home / ".claude"),
            "CODEX_HOME": str(self._home / ".codex"),
            "XDG_CACHE_HOME": str(self._home / ".cache"),
            "XDG_CONFIG_HOME": str(self._home / ".config"),
            "XDG_DATA_HOME": str(self._home / ".local" / "share"),
        }
        if tuple(sorted(environment)) != tuple(
            sorted(ISOLATED_AGENT_HOME_ENVIRONMENT_VARIABLES)
        ):
            return ProcessResult(
                tuple(command),
                ExecutionStatus.SPAWN_ERROR,
                "",
                "isolated agent-home environment contract drifted",
                None,
                0.0,
            )
        run_with_environment = getattr(self._delegate, "run_with_environment", None)
        if not callable(run_with_environment):
            return ProcessResult(
                tuple(command),
                ExecutionStatus.SPAWN_ERROR,
                "",
                "process runner cannot enforce isolated agent homes",
                None,
                0.0,
            )
        return run_with_environment(
            command,
            cwd,
            timeout_seconds,
            environment=environment,
            unset_environment=ISOLATED_AGENT_HOME_ENVIRONMENT_VARIABLES,
        )


class _AuthenticatedIsolatedAgentHomeProcessRunner:
    """Expose one configured credential and no user/project instruction files."""

    def __init__(
        self,
        delegate: ProcessRunner,
        home: Path,
        *,
        agent_base_id: str,
        credential_home: Path,
    ) -> None:
        self._delegate = delegate
        self._home = home
        self._agent_base_id = agent_base_id
        self._credential_home = credential_home
        self._agent_invocation_consumed = False
        self._home_owned = False

    def run(
        self,
        command: Sequence[str],
        cwd: Path,
        timeout_seconds: float | None,
    ) -> ProcessResult:
        if self._agent_invocation_consumed:
            return self._delegate.run(command, cwd, timeout_seconds)
        self._agent_invocation_consumed = True

        relative_credential = ISOLATED_AGENT_CREDENTIAL_PATHS.get(self._agent_base_id)
        if relative_credential is None:
            return self._spawn_error(command, "unsupported authenticated isolated agent base")
        source = self._credential_home / relative_credential
        try:
            source_stat = source.stat(follow_symlinks=False)
            if not stat.S_ISREG(source_stat.st_mode) or source.is_symlink():
                raise OSError("configured credential is not a regular file")
            if os.name == "posix" and stat.S_IMODE(source_stat.st_mode) & 0o077:
                raise OSError("configured credential permissions are too broad")
            self._home.parent.mkdir(parents=True, exist_ok=True)
            if self._home.parent.is_symlink():
                raise OSError("isolated agent-home parent is a symlink")
            self._home.mkdir(mode=0o700, exist_ok=False)
            self._home_owned = True
            target = self._home / relative_credential
            target.parent.mkdir(parents=True, mode=0o700)
            target.symlink_to(source)
            if sum(1 for path in self._home.rglob("*") if not path.is_dir()) != 1:
                raise OSError("isolated agent home credential inventory drifted")
            isolated_command = self._isolated_command(command)
        except (OSError, ValueError) as exc:
            self._clear_home()
            return self._spawn_error(command, f"unable to create authenticated isolated agent home: {exc}")

        try:
            environment = self._environment()
        except ValueError as exc:  # pragma: no cover - constant-owned invariant
            self._clear_home()
            return self._spawn_error(command, str(exc))
        run_with_environment = getattr(self._delegate, "run_with_environment", None)
        if not callable(run_with_environment):
            self._clear_home()
            return self._spawn_error(command, "process runner cannot enforce isolated agent homes")
        try:
            result = run_with_environment(
                isolated_command,
                cwd,
                timeout_seconds,
                environment=environment,
                unset_environment=ISOLATED_AGENT_HOME_ENVIRONMENT_VARIABLES,
            )
        finally:
            cleanup_error = self._clear_home()
        if cleanup_error is not None:
            return self._spawn_error(command, cleanup_error)
        return result

    def _isolated_command(self, command: Sequence[str]) -> tuple[str, ...]:
        command = tuple(command)
        if self._agent_base_id == "claude-code":
            if not command or Path(command[0]).name != "claude":
                raise ValueError("Claude command identity drifted")
            return (command[0], "--safe-mode", *command[1:])
        if len(command) < 2 or Path(command[0]).name != "codex" or command[1] != "exec":
            raise ValueError("Codex command identity drifted")
        return (
            *command[:2],
            "-c", "project_doc_max_bytes=0",
            "-c", "project_doc_fallback_filenames=[]",
            *command[2:],
        )

    def _environment(self) -> dict[str, str]:
        home = str(self._home)
        environment = {
            "HOME": home,
            "CLAUDE_CONFIG_DIR": str(self._home / ".claude"),
            "CODEX_HOME": str(self._home / ".codex"),
            "XDG_CACHE_HOME": str(self._home / ".cache"),
            "XDG_CONFIG_HOME": str(self._home / ".config"),
            "XDG_DATA_HOME": str(self._home / ".local" / "share"),
        }
        if tuple(sorted(environment)) != tuple(sorted(ISOLATED_AGENT_HOME_ENVIRONMENT_VARIABLES)):
            raise ValueError("isolated agent-home environment contract drifted")
        return environment

    def _clear_home(self) -> str | None:
        if not self._home_owned:
            return None
        if not self._home.exists() or not self._home.is_dir() or self._home.is_symlink():
            return "authenticated isolated agent home changed during execution"
        try:
            for child in self._home.iterdir():
                if child.is_symlink() or not child.is_dir():
                    child.unlink(missing_ok=True)
                else:
                    shutil.rmtree(child)
        except OSError:
            return "unable to remove authenticated isolated agent-home contents"
        return None

    @staticmethod
    def _spawn_error(command: Sequence[str], message: str) -> ProcessResult:
        return ProcessResult(tuple(command), ExecutionStatus.SPAWN_ERROR, "", message, None, 0.0)


class Phase2bExecutionError(PairedExecutionError):
    """A separately authorized Phase 2b execution cannot proceed safely."""


class Phase2bPilotRunner(PairedSmokeRunner):
    """Execute only a committed, dry-run-complete, separately authorized pilot."""

    policy_name = "phase2b-pilot"
    policy_version = "phase2b-pilot-v1"

    def __init__(
        self,
        manifest: Phase2bPilotManifest,
        manifest_path: Path,
        repository_roots: Mapping[str, Path],
        evaluator_root: Path,
        instruction_inventory_path: Path,
        workspace_root: Path,
        control_state_dir: Path,
        dry_run_record_path: Path,
        authorization_path: Path,
        *,
        process_runner_factory: Callable[[], ProcessRunner] = SubprocessRunner,
        version_resolver: Callable[[PairedAgentSpec], str] | None = None,
        clock: Callable[[], float] = monotonic,
        credential_home: Path | None = None,
    ) -> None:
        first_source = next(iter(repository_roots.values()))
        super().__init__(
            manifest.paired,
            manifest_path,
            first_source,
            workspace_root,
            control_state_dir,
            process_runner_factory=process_runner_factory,
            version_resolver=version_resolver or _installed_cli_version,
            clock=clock,
        )
        self.phase2b_manifest = manifest
        self.repository_roots = dict(repository_roots)
        self.evaluator_root = evaluator_root
        self.instruction_inventory_path = instruction_inventory_path
        self.dry_run_record_path = dry_run_record_path
        self.authorization_path = authorization_path
        self.credential_home = (credential_home or Path.home()).expanduser().resolve(strict=True)

    def run(self, *, confirm_agent_execution: bool = False) -> dict[str, object]:
        return self._execute_phase2b(
            confirm_agent_execution=confirm_agent_execution,
            resume=False,
        )

    def resume(self, *, confirm_agent_execution: bool = False) -> dict[str, object]:
        return self._execute_phase2b(
            confirm_agent_execution=confirm_agent_execution,
            resume=True,
        )

    def _execute_phase2b(
        self,
        *,
        confirm_agent_execution: bool,
        resume: bool,
    ) -> dict[str, object]:
        if not confirm_agent_execution:
            raise Phase2bExecutionError(
                "Phase 2b agent execution requires --confirm-agent-execution; "
                "manifest and dry-run records do not authorize 120 attempts."
            )

        source_roots = {
            key: path.expanduser().resolve(strict=True)
            for key, path in self.repository_roots.items()
        }
        workspace_root = self.workspace_root.expanduser().resolve(strict=True)
        configured_control = self.control_state_dir.expanduser().absolute()
        if configured_control.is_symlink():
            raise Phase2bExecutionError(
                "Phase 2b control state root must not be a symlink."
            )
        control = configured_control.resolve()
        evaluator_root = self.evaluator_root.expanduser().resolve(strict=True)
        protected_inputs = (
            self.manifest_path.expanduser().resolve(strict=True),
            self.dry_run_record_path.expanduser().resolve(strict=True),
            self.authorization_path.expanduser().resolve(strict=True),
            self.instruction_inventory_path.expanduser().resolve(strict=True),
        )
        for source in source_roots.values():
            if control == source or control.is_relative_to(source):
                raise Phase2bExecutionError("Phase 2b control state must be outside source repositories.")
        if control == workspace_root or control.is_relative_to(workspace_root):
            raise Phase2bExecutionError("Phase 2b control state must be outside agent workspaces.")
        if control == evaluator_root or control.is_relative_to(evaluator_root):
            raise Phase2bExecutionError("Phase 2b control state must be outside protected evaluators.")
        if workspace_root == evaluator_root or workspace_root.is_relative_to(evaluator_root):
            raise Phase2bExecutionError("Phase 2b workspace root must be outside protected evaluators.")
        if any(path == workspace_root or path.is_relative_to(workspace_root) for path in protected_inputs):
            raise Phase2bExecutionError("Phase 2b authorization inputs must be outside agent workspaces.")

        authorization = load_run_authorization(
            self.authorization_path,
            manifest_path=self.manifest_path,
            manifest=self.phase2b_manifest,
        )
        committed = audit_committed_manifest(
            self.manifest_path,
            str(authorization["manifest_commit"]),
        )
        dry_run = validate_phase2b_dry_run_record(
            self.dry_run_record_path,
            manifest=self.phase2b_manifest,
            manifest_path=self.manifest_path,
            workspace_root=workspace_root,
        )
        if _sha256(self.dry_run_record_path.read_bytes()) != authorization["agent_free_dry_run_sha256"]:
            raise Phase2bExecutionError("Run authorization does not bind the current dry-run record.")

        environment = validate_phase2b_environment(
            self.phase2b_manifest,
            self.manifest_path,
            source_roots,
            evaluator_root,
            self.instruction_inventory_path,
        )
        if dry_run["global_instruction_inventory_sha256"] != environment["global_instruction_inventory_sha256"]:
            raise Phase2bExecutionError("Dry-run global instruction evidence changed.")
        for spec in self.manifest.agents:
            observed = self.version_resolver(spec).strip()
            pattern = rf"(?<![0-9A-Za-z]){re.escape(spec.cli_version)}(?![0-9A-Za-z])"
            if not re.search(pattern, observed):
                raise Phase2bExecutionError(
                    f"CLI version mismatch for {spec.agent_id}: expected {spec.cli_version}, "
                    f"observed {observed or '<empty>'}"
                )

        assignments = assign_pairs(self.manifest)
        materialized_attempt_ids: set[str] = set()
        previous_elapsed_ms = 0.0
        if resume:
            if not control.is_dir():
                raise Phase2bExecutionError("Phase 2b resume requires an existing control directory.")
            state, materialized_attempt_ids = self._validate_resume_state(
                JsonlEventStore(control / "events.jsonl"), assignments
            )
            observations = observations_from_routing_state(self.manifest, state)
            previous_elapsed_ms = max(
                (item.experiment_elapsed_ms or 0.0 for item in observations),
                default=0.0,
            )
        elif control.exists() and (not control.is_dir() or any(control.iterdir())):
            raise Phase2bExecutionError("Phase 2b control directory must be new or empty.")

        prepared = validate_phase2b_execution_workspaces(
            self.phase2b_manifest,
            self.manifest_path,
            source_roots,
            evaluator_root,
            self.instruction_inventory_path,
            workspace_root,
            materialized_attempt_ids=materialized_attempt_ids,
        )
        if resume and not materialized_attempt_ids:
            raise Phase2bExecutionError("Phase 2b resume requires a finalized prefix.")
        if len(materialized_attempt_ids) >= 120:
            raise Phase2bExecutionError("Phase 2b run already materialized all 120 attempts.")

        snapshot = self._input_snapshot(environment)
        recorder = LifecycleRecorder(JsonlEventStore(control / "events.jsonl"))
        agent_specs = {spec.agent_id: spec for spec in self.manifest.agents}
        agents = {key: _agent_from_spec(value) for key, value in agent_specs.items()}
        config_hash = hashlib.sha256(
            json.dumps(
                self.phase2b_manifest.as_dict(),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

        wall_limit = float(self.manifest.maximum_resource_budget["wall_time_seconds"])
        run_started = self.clock()
        remaining_seconds = wall_limit - previous_elapsed_ms / 1000
        if remaining_seconds <= 0:
            raise Phase2bExecutionError("Phase 2b wall-time budget was already exhausted.")
        deadline = run_started + remaining_seconds
        workspace_by_key = {
            (row["task_id"], row["agent_id"]): Path(row["path"])
            for row in prepared["workspaces"]
        }
        task_by_id = {task.task_id: task for task in self.manifest.tasks}
        attempts_started = 0
        for assignment in assignments:
            task = task_by_id[assignment.task_id]
            for agent_id in assignment.agent_order:
                attempt_id = assignment.attempt_ids[agent_id]
                if attempt_id in materialized_attempt_ids:
                    continue
                self._assert_input_snapshot(snapshot)
                if self.clock() >= deadline:
                    raise Phase2bExecutionError(
                        f"Phase 2b wall-time budget exhausted after "
                        f"{len(materialized_attempt_ids) + attempts_started} of 120 attempts."
                    )
                self._run_attempt(
                    recorder,
                    agents[agent_id],
                    agent_specs[agent_id],
                    task,
                    assignment,
                    workspace_by_key[(assignment.task_id, agent_id)],
                    config_hash,
                    run_started,
                    deadline,
                    previous_elapsed_ms,
                )
                attempts_started += 1

        self._assert_input_snapshot(snapshot)
        state = recorder.rebuild_state()
        observations = observations_from_routing_state(self.manifest, state)
        materialized = [item for item in observations if item.attempt_materialized]
        analysis = analyze_paired_observations(self.manifest, observations)
        mark_phase2b_analysis_non_promotional(analysis)
        return {
            "schema_version": PHASE2B_RUN_SCHEMA,
            "manifest_schema_version": self.phase2b_manifest.schema_version,
            "experiment_id": self.phase2b_manifest.experiment_id,
            "manifest_commit": committed["manifest_commit"],
            "manifest_sha256": committed["manifest_sha256"],
            "dry_run_sha256": authorization["agent_free_dry_run_sha256"],
            "agent_execution_started": True,
            "resumed": resume,
            "attempts_started_this_invocation": attempts_started,
            "materialized_attempts": len(materialized),
            "completed_attempts": sum(item.terminal_status == "completed" for item in materialized),
            "prepared": prepared,
            "analysis": analysis,
        }

    def manifest_task_evaluator(
        self,
        task_spec: PairedTaskSpec,
        *,
        timeout_seconds: float | None = None,
    ) -> EvaluatorSpec:
        root = self.evaluator_root.expanduser().resolve(strict=True)
        artifact_paths = tuple(
            str((root / path).resolve(strict=True)) for path in task_spec.evaluator.artifact_paths
        )
        path_map = dict(zip(task_spec.evaluator.artifact_paths, artifact_paths, strict=True))
        command = tuple(path_map.get(token, token) for token in task_spec.evaluator.command)
        return EvaluatorSpec(
            evaluator_id=task_spec.evaluator.evaluator_id,
            version=task_spec.evaluator.version,
            role=EvaluatorRole.QUALITY,
            subject=task_spec.objective,
            command=command,
            timeout_seconds=(
                timeout_seconds
                if timeout_seconds is not None
                else task_spec.evaluator.timeout_seconds
            ),
            evidence_scope="Pre-registered Phase 2b task-specific objective quality.",
            artifact_paths=artifact_paths,
        )

    def _process_runner_for_attempt(
        self,
        agent_spec: PairedAgentSpec,
        workspace: Path,
    ) -> ProcessRunner:
        delegate = super()._process_runner_for_attempt(agent_spec, workspace)
        resolution = self.phase2b_manifest.global_instruction_context["resolution"]
        if resolution not in {
            "isolated-empty-agent-homes",
            AUTHENTICATED_ISOLATED_AGENT_HOME_RESOLUTION,
        }:
            return delegate
        workspace_root = self.workspace_root.expanduser().resolve(strict=True)
        resolved_workspace = workspace.expanduser().resolve(strict=True)
        try:
            relative = resolved_workspace.relative_to(workspace_root)
        except ValueError as exc:  # pragma: no cover - workspace preflight owns this invariant
            raise Phase2bExecutionError(
                "Phase 2b attempt workspace escaped its dedicated root."
            ) from exc
        control = Path(os.path.abspath(self.control_state_dir.expanduser()))
        if control.is_symlink():
            raise Phase2bExecutionError(
                "Phase 2b control state root must not be a symlink."
            )
        home = control / "isolated-agent-homes" / relative
        if resolution == AUTHENTICATED_ISOLATED_AGENT_HOME_RESOLUTION:
            return _AuthenticatedIsolatedAgentHomeProcessRunner(
                delegate,
                home,
                agent_base_id=agent_spec.base_id,
                credential_home=self.credential_home,
            )
        return _IsolatedAgentHomeProcessRunner(delegate, home)

    def _input_snapshot(self, environment: Mapping[str, object]) -> Mapping[str, object]:
        return {
            "manifest": _sha256(self.manifest_path.read_bytes()),
            "dry_run": _sha256(self.dry_run_record_path.read_bytes()),
            "authorization": _sha256(self.authorization_path.read_bytes()),
            "instruction_inventory": _sha256(self.instruction_inventory_path.read_bytes()),
            "evaluator_artifacts": dict(environment["evaluator_artifact_hashes"]),
            "repositories": dict(environment["repository_evidence"]),
            "agent_versions": {
                spec.agent_id: self.version_resolver(spec).strip()
                for spec in self.manifest.agents
            },
        }

    def _assert_input_snapshot(self, expected: Mapping[str, object]) -> None:
        evaluator_root = self.evaluator_root.expanduser().resolve(strict=True)
        source_roots = tuple(
            configured.expanduser().resolve(strict=True)
            for configured in self.repository_roots.values()
        )
        artifact_set_hashes: dict[tuple[str, ...], str] = {}
        evaluator_hashes: dict[str, str] = {}
        for task in self.manifest.tasks:
            artifact_paths = tuple(
                str((evaluator_root / path).resolve(strict=True))
                for path in task.evaluator.artifact_paths
            )
            if artifact_paths not in artifact_set_hashes:
                for source in source_roots:
                    validate_evaluator_artifacts(artifact_paths, source)
                artifact_set_hashes[artifact_paths] = hash_evaluator_artifacts(
                    artifact_paths
                )
            evaluator_hashes[task.task_id] = artifact_set_hashes[artifact_paths]
        repository_specs = {
            item.repository_id: item for item in self.phase2b_manifest.repositories
        }
        repository_evidence = {}
        for repository_id, configured in self.repository_roots.items():
            source = configured.expanduser().resolve(strict=True)
            spec = repository_specs[repository_id]
            if _git(source, "status", "--porcelain", "--untracked-files=all"):
                raise Phase2bExecutionError("Phase 2b source repository changed during execution.")
            commit = _git(source, "rev-parse", f"{spec.base_revision}^{{commit}}")
            repository_evidence[repository_id] = {
                "commit_hash": commit,
                "tree_hash": _git(source, "rev-parse", f"{commit}^{{tree}}"),
            }
        observed = {
            "manifest": _sha256(self.manifest_path.read_bytes()),
            "dry_run": _sha256(self.dry_run_record_path.read_bytes()),
            "authorization": _sha256(self.authorization_path.read_bytes()),
            "instruction_inventory": _sha256(self.instruction_inventory_path.read_bytes()),
            "evaluator_artifacts": evaluator_hashes,
            "repositories": repository_evidence,
            "agent_versions": {
                spec.agent_id: self.version_resolver(spec).strip()
                for spec in self.manifest.agents
            },
        }
        if observed != expected:
            raise Phase2bExecutionError("Phase 2b frozen input changed during execution.")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
