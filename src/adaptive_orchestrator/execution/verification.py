from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from adaptive_orchestrator.core.domain import (
    EvaluatorResult,
    EvaluatorRole,
    EvaluatorSpec,
    EvaluatorStatus,
    ExecutionStatus,
    Task,
    VerificationResult,
    VerificationStatus,
)
from adaptive_orchestrator.execution.process_runner import ProcessRunner

_STATUS_FOR_EXECUTION = {
    ExecutionStatus.COMPLETED: EvaluatorStatus.PASSED,
    ExecutionStatus.FAILED: EvaluatorStatus.FAILED,
    ExecutionStatus.TIMED_OUT: EvaluatorStatus.TIMED_OUT,
    ExecutionStatus.SPAWN_ERROR: EvaluatorStatus.ERROR,
}
_VERIFICATION_STATUS = {
    EvaluatorStatus.PASSED: VerificationStatus.PASSED,
    EvaluatorStatus.FAILED: VerificationStatus.FAILED,
    EvaluatorStatus.TIMED_OUT: VerificationStatus.TIMED_OUT,
    EvaluatorStatus.ERROR: VerificationStatus.FAILED,
    EvaluatorStatus.SKIPPED: VerificationStatus.SKIPPED,
}
_STATUS_SEVERITY = {VerificationStatus.PASSED: 0, VerificationStatus.TIMED_OUT: 1, VerificationStatus.FAILED: 2}
_ROLE_NAMES = tuple(role.value for role in EvaluatorRole)
_WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH


def evaluator_content_version(command: Sequence[str], artifact_paths: Sequence[str] = ()) -> str:
    """A deterministic version for CLI-created evaluators.

    Artifact content is included when it is available before agent execution,
    so changing either the command contract or protected fixture changes the
    evaluator version.
    """

    payload = {"command": list(command), "artifact_hash": hash_evaluator_artifacts(artifact_paths) if artifact_paths else None}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def hash_evaluator_artifacts(paths: Sequence[str]) -> str:
    """Hash files, directories, and symlinks without following symlinked trees."""

    if not paths:
        raise ValueError("At least one evaluator artifact path is required.")
    digest = hashlib.sha256()
    for root_index, raw_path in enumerate(paths):
        root = Path(raw_path).resolve(strict=True)
        digest.update(f"root:{root_index}:{root.name}\0".encode("utf-8"))
        _hash_path(digest, root, Path(root.name))
    return digest.hexdigest()


def validate_evaluator_artifacts(paths: Sequence[str], workspace: Path) -> None:
    """Require protected evaluator material outside the agent workspace and mode-read-only."""

    if not paths:
        raise ValueError("Quality evaluators require at least one protected artifact path.")
    resolved_workspace = workspace.resolve()
    for raw_path in paths:
        unresolved = Path(raw_path).expanduser().absolute()
        if unresolved == resolved_workspace or unresolved.is_relative_to(resolved_workspace):
            raise ValueError(f"Evaluator artifact must be outside the agent-writeable workspace: {unresolved}")
        root = unresolved.resolve(strict=True)
        if root == resolved_workspace or root.is_relative_to(resolved_workspace):
            raise ValueError(f"Evaluator artifact must be outside the agent-writeable workspace: {root}")
        for item in _artifact_entries(root):
            if stat.S_IMODE(item.lstat().st_mode) & _WRITE_BITS:
                raise ValueError(f"Evaluator artifact must be read-only before agent execution: {item}")


def evaluation_projection(results: Sequence[EvaluatorResult]) -> dict[str, dict[str, object]]:
    """Keep role observations separate; never synthesize task quality from another role."""

    projection: dict[str, dict[str, object]] = {
        role: {
            "result_count": 0,
            "observed": False,
            "observed_count": 0,
            "passed_count": 0,
            "failed_count": 0,
            "error_count": 0,
            "scores": [],
        }
        for role in _ROLE_NAMES
    }
    for result in results:
        role_projection = projection[result.role.value]
        role_projection["result_count"] = int(role_projection["result_count"]) + 1
        if result.observed:
            role_projection["observed"] = True
            role_projection["observed_count"] = int(role_projection["observed_count"]) + 1
            if result.status is EvaluatorStatus.PASSED:
                role_projection["passed_count"] = int(role_projection["passed_count"]) + 1
            elif result.status in {EvaluatorStatus.FAILED, EvaluatorStatus.TIMED_OUT}:
                role_projection["failed_count"] = int(role_projection["failed_count"]) + 1
        if result.status is EvaluatorStatus.ERROR:
            role_projection["error_count"] = int(role_projection["error_count"]) + 1
        if result.score is not None:
            scores = role_projection["scores"]
            assert isinstance(scores, list)
            scores.append(result.score)
    return projection


@dataclass(frozen=True, slots=True)
class CommandVerifier:
    """Backward-compatible verification plus typed per-evaluator evidence.

    `command` and `additional_commands` retain their original aggregate
    behavior, but are conservatively typed as constraints. Explicit evaluator
    specs may add quality, safety, reliability, or resource observations.
    """

    command: Sequence[str] = ()
    timeout_seconds: float | None = None
    additional_commands: Sequence[Sequence[str]] = field(default_factory=tuple)
    evaluator_specs: Sequence[EvaluatorSpec] = field(default_factory=tuple)
    _artifact_hashes: Mapping[str, str] = field(default_factory=dict, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        evaluator_ids = [spec.evaluator_id for spec in self.evaluator_specs]
        if len(evaluator_ids) != len(set(evaluator_ids)):
            raise ValueError("EvaluatorSpec evaluator_id values must be unique.")
        baselines = {
            spec.evaluator_id: hash_evaluator_artifacts(spec.artifact_paths)
            for spec in self.evaluator_specs
            if spec.artifact_paths
        }
        object.__setattr__(self, "_artifact_hashes", baselines)

    def policy_config(self) -> dict[str, object]:
        return {
            "legacy_constraint_commands": [list(command) for command in self._legacy_commands()],
            "timeout_seconds": self.timeout_seconds,
            "evaluators": [asdict(spec) for spec in self.evaluator_specs],
        }

    def verify(self, task: Task, execution_status: ExecutionStatus, workspace: Path, runner: ProcessRunner) -> VerificationResult:
        """Preserve the original API for programmatic callers."""

        verification, _ = self.verify_with_evaluations(task, execution_status, workspace, runner)
        return verification

    def verify_with_evaluations(
        self,
        task: Task,
        execution_status: ExecutionStatus,
        workspace: Path,
        runner: ProcessRunner,
    ) -> tuple[VerificationResult, tuple[EvaluatorResult, ...]]:
        specs = (*self._legacy_specs(), *self.evaluator_specs)
        reliability = _reliability_result(execution_status)
        results = [reliability]
        for spec in specs:
            results.append(self._evaluate_spec(spec, task, execution_status, workspace, runner))
        return self._aggregate(specs, tuple(results[1:])), tuple(results)

    def _legacy_commands(self) -> tuple[tuple[str, ...], ...]:
        commands = ([tuple(self.command)] if self.command else []) + [tuple(item) for item in self.additional_commands]
        return tuple(command for command in commands if command)

    def _legacy_specs(self) -> tuple[EvaluatorSpec, ...]:
        specs: list[EvaluatorSpec] = []
        for index, command in enumerate(self._legacy_commands(), start=1):
            version = evaluator_content_version(command)
            specs.append(EvaluatorSpec(
                evaluator_id=f"legacy-constraint-{index}",
                version=version,
                role=EvaluatorRole.CONSTRAINT,
                subject="legacy --verify-command",
                command=command,
                timeout_seconds=self.timeout_seconds,
                evidence_scope="Command exit status only; not task-specific quality.",
            ))
        return tuple(specs)

    def _evaluate_spec(
        self,
        spec: EvaluatorSpec,
        task: Task,
        execution_status: ExecutionStatus,
        workspace: Path,
        runner: ProcessRunner,
    ) -> EvaluatorResult:
        expected_hash = self._artifact_hashes.get(spec.evaluator_id)
        if execution_status is not ExecutionStatus.COMPLETED:
            return _result_for_spec(spec, EvaluatorStatus.SKIPPED, observed=False, artifact_hash_expected=expected_hash)

        if spec.role is EvaluatorRole.QUALITY:
            try:
                validate_evaluator_artifacts(spec.artifact_paths, workspace)
            except (OSError, ValueError) as exc:
                return _result_for_spec(
                    spec,
                    EvaluatorStatus.ERROR,
                    observed=False,
                    stderr=str(exc),
                    artifact_hash_expected=expected_hash,
                    artifact_integrity_verified=False,
                )

        before_hash = None
        if spec.artifact_paths:
            try:
                before_hash = hash_evaluator_artifacts(spec.artifact_paths)
            except (OSError, ValueError) as exc:
                return _result_for_spec(
                    spec,
                    EvaluatorStatus.ERROR,
                    observed=False,
                    stderr=f"Unable to hash evaluator artifacts before execution: {exc}",
                    artifact_hash_expected=expected_hash,
                    artifact_integrity_verified=False,
                )
            if before_hash != expected_hash:
                return _result_for_spec(
                    spec,
                    EvaluatorStatus.ERROR,
                    observed=False,
                    stderr="Evaluator artifact changed after the protected baseline was captured.",
                    artifact_hash_expected=expected_hash,
                    artifact_hash_before=before_hash,
                    artifact_integrity_verified=False,
                )

        process = runner.run(spec.command, workspace, spec.timeout_seconds or self.timeout_seconds or task.time_limit_seconds)
        status = _STATUS_FOR_EXECUTION[process.status]
        after_hash = None
        integrity = None
        if spec.artifact_paths:
            try:
                after_hash = hash_evaluator_artifacts(spec.artifact_paths)
                integrity = after_hash == before_hash == expected_hash
            except (OSError, ValueError):
                integrity = False
            if not integrity:
                status = EvaluatorStatus.ERROR

        score = None
        if spec.role is EvaluatorRole.QUALITY and status in {EvaluatorStatus.PASSED, EvaluatorStatus.FAILED} and integrity is not False:
            score = 1.0 if status is EvaluatorStatus.PASSED else 0.0
        stderr = process.stderr or None
        if integrity is False:
            integrity_error = "Evaluator artifact changed during evaluation."
            stderr = f"{stderr}\n{integrity_error}" if stderr else integrity_error
        return _result_for_spec(
            spec,
            status,
            observed=True,
            score=score,
            exit_code=process.exit_code,
            duration_ms=process.duration_ms,
            stdout=process.stdout or None,
            stderr=stderr,
            artifact_hash_expected=expected_hash,
            artifact_hash_before=before_hash,
            artifact_hash_after=after_hash,
            artifact_integrity_verified=integrity,
        )

    def _aggregate(self, specs: Sequence[EvaluatorSpec], results: Sequence[EvaluatorResult]) -> VerificationResult:
        commands = tuple(tuple(spec.command) for spec in specs)
        if not commands or all(result.status is EvaluatorStatus.SKIPPED for result in results):
            return VerificationResult(VerificationStatus.SKIPPED)

        required_results = [result for result in results if result.required and result.status is not EvaluatorStatus.SKIPPED]
        worst_status = VerificationStatus.PASSED
        for result in required_results:
            candidate = _VERIFICATION_STATUS[result.status]
            if candidate is not VerificationStatus.SKIPPED and _STATUS_SEVERITY[candidate] > _STATUS_SEVERITY[worst_status]:
                worst_status = candidate

        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        total_duration_ms = 0.0
        last_exit_code: int | None = None
        for result in results:
            header = " ".join(result.command)
            if result.stdout:
                stdout_parts.append(f"$ {header}\n{result.stdout}")
            if result.stderr:
                stderr_parts.append(f"$ {header}\n{result.stderr}")
            total_duration_ms += result.duration_ms
            if result.exit_code is not None:
                last_exit_code = result.exit_code

        return VerificationResult(
            worst_status,
            commands,
            "\n\n".join(stdout_parts) or None,
            "\n\n".join(stderr_parts) or None,
            last_exit_code,
            total_duration_ms,
        )


def _result_for_spec(
    spec: EvaluatorSpec,
    status: EvaluatorStatus,
    observed: bool,
    **kwargs: object,
) -> EvaluatorResult:
    return EvaluatorResult(
        evaluator_id=spec.evaluator_id,
        version=spec.version,
        role=spec.role,
        status=status,
        observed=observed,
        required=spec.required,
        command=tuple(spec.command),
        evidence_scope=spec.evidence_scope,
        **kwargs,
    )


def _reliability_result(status: ExecutionStatus) -> EvaluatorResult:
    evaluator_status = _STATUS_FOR_EXECUTION[status]
    return EvaluatorResult(
        evaluator_id="execution-reliability",
        version="1",
        role=EvaluatorRole.RELIABILITY,
        status=evaluator_status,
        observed=True,
        required=True,
        evidence_scope="Agent process terminal status only.",
    )


def _artifact_entries(root: Path) -> tuple[Path, ...]:
    if not root.is_dir() or root.is_symlink():
        return (root,)
    entries = [root]
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        directories.sort()
        files.sort()
        entries.extend(current_path / name for name in directories)
        entries.extend(current_path / name for name in files)
    return tuple(entries)


def _hash_path(digest: "hashlib._Hash", path: Path, relative_path: Path) -> None:
    metadata = path.lstat()
    mode = stat.S_IMODE(metadata.st_mode)
    if path.is_symlink():
        digest.update(f"symlink:{relative_path}:{mode}:{os.readlink(path)}\0".encode("utf-8"))
        return
    if path.is_file():
        digest.update(f"file:{relative_path}:{mode}:{metadata.st_size}\0".encode("utf-8"))
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return
    if path.is_dir():
        digest.update(f"directory:{relative_path}:{mode}\0".encode("utf-8"))
        children = sorted(path.iterdir(), key=lambda child: child.name)
        for child in children:
            _hash_path(digest, child, relative_path / child.name)
        return
    digest.update(f"other:{relative_path}:{mode}:{metadata.st_size}\0".encode("utf-8"))
