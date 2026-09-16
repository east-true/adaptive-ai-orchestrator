from __future__ import annotations

import hashlib
import json
import errno
import fcntl
import os
import platform
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from time import monotonic
from typing import Callable, Mapping, Sequence

from adaptive_orchestrator.core.domain import ExecutionStatus, EvaluatorRole, EvaluatorSpec
from adaptive_orchestrator.execution.process_runner import (
    ProcessResult,
    ProcessRunner,
    SubprocessRunner,
)
from adaptive_orchestrator.execution.agents import (
    PROVIDER_TRANSMISSION_CONTEXT_KEY,
)
from adaptive_orchestrator.execution.resource_supervisor import (
    PHASE2B_AGENT_RESOURCE_POLICY,
    PHASE2B_EVALUATOR_RESOURCE_POLICY,
    PHASE2B_RESOURCE_INVOCATION_POLICIES,
    RESOURCE_SUPERVISOR_SCHEMA,
    ResourceInvocationPolicy,
    SupervisedProcessRunner,
    _close_owned_descriptors_report,
    probe_resource_capabilities,
    resource_policy_descriptor,
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
    BUBBLEWRAP_EXECUTABLE,
    ISOLATED_AGENT_CREDENTIAL_PATHS,
    PHASE2B_AGENT_EXECUTION_ISOLATION_POLICY_SHA256,
    PHASE2B_AGENT_EXECUTION_ISOLATION_SCHEMA,
    PHASE2B_AGENT_EXECUTION_ISOLATION_STRATEGY,
    Phase2bPilotManifest,
    audit_committed_manifest,
    load_run_authorization,
    mark_phase2b_analysis_non_promotional,
    _validate_provider_transmission_notice_tree,
    validate_phase2b_agent_execution_isolation,
    validate_phase2b_dry_run_record,
    validate_phase2b_environment,
    validate_phase2b_execution_workspaces,
)
from adaptive_orchestrator.infrastructure.events import JsonlEventStore
from adaptive_orchestrator.routing.state import LifecycleRecorder


PHASE2B_RUN_SCHEMA = "phase2b-pilot-run-v1"


def _close_owned_or_raise(
    descriptors: Sequence[int],
    label: str,
) -> None:
    """Visit every FD; raise on successful paths, preserve an active error."""

    closed, close_error = _close_owned_descriptors_report(
        tuple(descriptor for descriptor in descriptors if descriptor >= 0)
    )
    if sys.exc_info()[0] is None:
        if close_error is not None:
            raise close_error
        if not closed:
            raise OSError(f"{label} descriptor cleanup could not be verified")


def _phase2b_resource_supervisor_descriptor() -> dict[str, object]:
    attestation = probe_resource_capabilities(
        PHASE2B_AGENT_RESOURCE_POLICY.caps,
        (),
    )
    return resource_policy_descriptor(
        PHASE2B_RESOURCE_INVOCATION_POLICIES,
        attestation,
    )


def _default_resource_supervisor_factory(
    policies: Sequence[ResourceInvocationPolicy],
    watched_roots: Mapping[str, Path],
) -> ProcessRunner:
    return SupervisedProcessRunner(policies, watched_roots)


@dataclass(frozen=True, slots=True)
class _RuntimeMount:
    source: Path
    target: str


@dataclass(frozen=True, slots=True)
class _AgentRuntime:
    command_prefix: tuple[str, ...]
    mounts: tuple[_RuntimeMount, ...]


@dataclass(frozen=True, slots=True)
class _RuntimeClosure:
    agent_runtimes: Mapping[str, _AgentRuntime]
    toolchain_mounts: tuple[_RuntimeMount, ...]
    observed_evidence: Mapping[str, object]
    metadata_mounts: tuple[_RuntimeMount, ...]
    attested_metadata_sha256: str


@dataclass(slots=True)
class _CredentialLease:
    """Exclusive, compare-and-swap lease for one private credential cache."""

    source: Path
    target: Path
    source_name: str
    provider_directory_name: str
    cache_home_fd: int
    source_directory_fd: int
    source_fd: int
    lock_fd: int
    cache_home_device: int
    cache_home_inode: int
    source_directory_device: int
    source_directory_inode: int
    source_device: int
    source_inode: int
    preimage_sha256: str


_NAMESPACE_WORKSPACE = "/workspace"
_NAMESPACE_HOME = "/agent-home"
_NAMESPACE_BIN = "/phase2b-bin"
_NAMESPACE_HELPER_BIN = "/phase2b-helper-bin"
_NAMESPACE_NATIVE_HELPER = "/phase2b-native-helper"
_NAMESPACE_RUNTIME = "/phase2b-runtime"
_NAMESPACE_EVALUATOR = "/phase2b-evaluator"
_NAMESPACE_EVALUATOR_HOME = "/evaluator-home"
_NAMESPACE_EVALUATOR_HELPER = "/phase2b-evaluator-helper/codex-linux-sandbox"
_CODEX_PERMISSION_PROFILE = "phase2b-isolated"
_MAX_CREDENTIAL_BYTES = 1024 * 1024
_CODEX_SANDBOX_WRAPPER = Path(__file__).with_name(
    "_phase2b_codex_sandbox_wrapper.py"
)
_CODEX_SANDBOX_WRAPPER_SHA256 = (
    "af2a8545a4f2711d9a4f10313858f811f82022e4983717bf19b90a5498578c6d"
)
_CLAUDE_BWRAP_WRAPPER = Path(__file__).with_name(
    "_phase2b_claude_bwrap_wrapper.py"
)
_CLAUDE_BWRAP_WRAPPER_SHA256 = (
    "be704f229cb1dc59254287762b4544f0ae5089cbf4cd577a686916649b37d413"
)
_SYSTEM_READ_ONLY_DIRECTORIES = ("/usr", "/bin", "/sbin", "/lib", "/lib64")
_SYSTEM_READ_ONLY_ETC_PATHS = (
    "/etc/alternatives",
    "/etc/ca-certificates",
    "/etc/ld.so.cache",
    "/etc/ld.so.conf",
    "/etc/ld.so.conf.d",
    "/etc/localtime",
    "/etc/nsswitch.conf",
    "/etc/os-release",
    "/etc/protocols",
    "/etc/resolv.conf",
    "/etc/services",
    "/etc/ssl",
)
_MODEL_TOOL_PATH = (
    f"{_NAMESPACE_RUNTIME}/node/bin:"
    f"{_NAMESPACE_RUNTIME}/go/bin:"
    f"{_NAMESPACE_RUNTIME}/rust-toolchain/bin:"
    f"{_NAMESPACE_RUNTIME}/cargo/bin:"
    "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
)
_NAMESPACE_ENVIRONMENT = {
    "CARGO_HOME": f"{_NAMESPACE_RUNTIME}/cargo",
    "CI": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "CLAUDE_CONFIG_DIR": f"{_NAMESPACE_HOME}/.claude",
    "CODEX_HOME": f"{_NAMESPACE_HOME}/.codex",
    "GOENV": "off",
    "GOROOT": f"{_NAMESPACE_RUNTIME}/go",
    "HOME": _NAMESPACE_HOME,
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "LD_LIBRARY_PATH": f"{_NAMESPACE_RUNTIME}/rust-toolchain/lib",
    "LOGNAME": "phase2b",
    "NO_COLOR": "1",
    "PATH": f"{_NAMESPACE_HELPER_BIN}:{_MODEL_TOOL_PATH}",
    "RUSTUP_HOME": f"{_NAMESPACE_RUNTIME}/rustup",
    "SHELL": "/bin/sh",
    "TMPDIR": "/tmp",
    "USER": "phase2b",
    "XDG_CACHE_HOME": f"{_NAMESPACE_HOME}/.cache",
    "XDG_CONFIG_HOME": f"{_NAMESPACE_HOME}/.config",
    "XDG_DATA_HOME": f"{_NAMESPACE_HOME}/.local/share",
}
_EVALUATOR_ENVIRONMENT = {
    "CI": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GOCACHE": "/tmp/go-cache",
    "GOENV": "off",
    "GOROOT": f"{_NAMESPACE_RUNTIME}/go",
    "HOME": _NAMESPACE_EVALUATOR_HOME,
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "LD_LIBRARY_PATH": f"{_NAMESPACE_RUNTIME}/rust-toolchain/lib",
    "LOGNAME": "phase2b-evaluator",
    "NO_COLOR": "1",
    "NPM_CONFIG_CACHE": "/tmp/npm-cache",
    "PATH": _MODEL_TOOL_PATH,
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONNOUSERSITE": "1",
    "RUSTUP_HOME": f"{_NAMESPACE_RUNTIME}/rustup",
    "SHELL": "/bin/sh",
    "TMPDIR": "/tmp",
    "USER": "phase2b-evaluator",
}


class _BubblewrapIsolatedAgentProcessRunner:
    """Run the agent and evaluator in distinct per-attempt mount namespaces."""

    def __init__(
        self,
        delegate: ProcessRunner,
        home: Path,
        workspace: Path,
        *,
        agent_spec: PairedAgentSpec,
        credential_home: Path | None,
        toolchain_home: Path,
        evaluator_root: Path,
        evaluator_native_helper: Path,
        expected_bubblewrap_sha256: str,
        runtime_resolver: Callable[[str, str], _AgentRuntime],
        toolchain_mounts: tuple[_RuntimeMount, ...] | None = None,
        evaluator_delegate: ProcessRunner | None = None,
        agent_resource_policy: ResourceInvocationPolicy = (
            PHASE2B_AGENT_RESOURCE_POLICY
        ),
        evaluator_resource_policy: ResourceInvocationPolicy = (
            PHASE2B_EVALUATOR_RESOURCE_POLICY
        ),
        require_resource_observation: bool = False,
    ) -> None:
        self._delegate = delegate
        self._evaluator_delegate = evaluator_delegate or delegate
        self._home = home
        self._workspace = workspace
        self._agent_spec = agent_spec
        self._agent_base_id = agent_spec.base_id
        self._credential_home = credential_home
        self._toolchain_home = toolchain_home
        self._evaluator_root = evaluator_root
        self._evaluator_native_helper = evaluator_native_helper
        self._expected_bubblewrap_sha256 = expected_bubblewrap_sha256
        self._runtime_resolver = runtime_resolver
        self._toolchain_mounts = (
            toolchain_mounts
            if toolchain_mounts is not None
            else _optional_toolchain_mounts(toolchain_home)
        )
        self._agent_invocation_consumed = False
        self._evaluator_invocation_consumed = False
        self._home_owned = False
        self._resource_policies = {
            "agent": agent_resource_policy,
            "evaluator": evaluator_resource_policy,
        }
        self._require_resource_observation = require_resource_observation
        if agent_resource_policy.name != "agent":
            raise ValueError("agent resource policy has the wrong role name")
        if evaluator_resource_policy.name != "evaluator":
            raise ValueError("evaluator resource policy has the wrong role name")
        self._resource_observations: dict[str, dict[str, object]] = {}
        self._terminal_missing_resource_reason = (
            "not-invoked-before-terminal-finalization"
        )
        self._credential_lease: _CredentialLease | None = None
        self._credential_refresh_status = (
            "not-configured" if credential_home is None else "not-invoked"
        )

    def run(
        self,
        command: Sequence[str],
        cwd: Path,
        timeout_seconds: float | None,
    ) -> ProcessResult:
        if self._agent_invocation_consumed:
            return self._run_evaluator(command, cwd, timeout_seconds)
        self._agent_invocation_consumed = True
        original = tuple(command)
        credential_source: Path | None = None
        credential_target: Path | None = None
        try:
            if cwd.resolve(strict=True) != self._workspace.resolve(strict=True):
                raise ValueError("agent invocation cwd differs from the attempt workspace")
            self._validate_bubblewrap()
            credential_source, credential_target = self._prepare_home()
            expected_executable = (
                "claude" if self._agent_base_id == "claude-code" else "codex"
            )
            runtime = self._runtime_resolver(
                self._agent_base_id,
                expected_executable,
            )
            isolated_agent_command = self._isolated_agent_command(original, runtime)
            isolated_command = self._bubblewrap_command(
                isolated_agent_command,
                runtime,
                credential_source=credential_source,
                credential_target=credential_target,
            )
        except (IndexError, OSError, ValueError) as exc:
            credential_was_leased = self._credential_lease is not None
            preflight_cleanup_failed = False
            try:
                self._release_credential_lease()
            except BaseException:
                preflight_cleanup_failed = True
            if self._credential_home is not None:
                self._credential_refresh_status = (
                    "not-invoked"
                    if credential_was_leased
                    else self._credential_refresh_status
                )
            try:
                if self._clear_home() is not None:
                    preflight_cleanup_failed = True
            except BaseException:
                preflight_cleanup_failed = True
            try:
                self._record_resource_not_invoked(
                    "agent", "not-invoked-preflight-rejected"
                )
            except BaseException:
                preflight_cleanup_failed = True
            return self._sanitized_spawn_error(
                original,
                "unable to create bubblewrap-isolated agent invocation: "
                f"isolation preflight rejected it ({type(exc).__name__})"
                + (
                    " and terminal cleanup was incomplete"
                    if preflight_cleanup_failed
                    else ""
                ),
            )
        except BaseException:
            # The original host interruption remains authoritative, but all
            # cleanup/evidence stages are still visited.
            try:
                self._release_credential_lease()
            except BaseException:
                pass
            try:
                self._clear_home()
            except BaseException:
                pass
            try:
                self._record_resource_not_invoked(
                    "agent", "not-invoked-preflight-interrupted"
                )
            except BaseException:
                pass
            raise

        try:
            raw_result = self._delegate.run(
                isolated_command,
                cwd,
                timeout_seconds,
            )
        except BaseException:
            # Visit every terminal action while Python still retains the
            # delegate's original exception.  No cleanup error may replace it.
            self._finish_agent_invocation_cleanup()
            raise
        (
            observation_error,
            credential_error,
            cleanup_error,
            cleanup_exception,
        ) = self._finish_agent_invocation_cleanup()
        if cleanup_exception is not None:
            return self._sanitized_spawn_error(
                original,
                "agent invocation terminal cleanup failed",
            )
        if observation_error is not None and self._require_resource_observation:
            return self._sanitized_spawn_error(original, observation_error)
        if self._require_resource_observation and (
            self._resource_observations["agent"].get("outcome_status")
            != raw_result.status.value
        ):
            return self._sanitized_spawn_error(
                original,
                "resource supervisor result disagreed with the agent process result",
            )
        if cleanup_error is not None:
            return self._sanitized_spawn_error(original, cleanup_error)
        if credential_error is not None:
            return self._sanitized_spawn_error(original, credential_error)
        return self._sanitize_result(
            raw_result,
            isolated_agent_command,
            self._agent_path_replacements(
                runtime,
                credential_source=credential_source,
                credential_target=credential_target,
            ),
        )

    def _run_evaluator(
        self,
        command: Sequence[str],
        cwd: Path,
        timeout_seconds: float | None,
    ) -> ProcessResult:
        original = tuple(command)
        if self._evaluator_invocation_consumed:
            return self._sanitized_spawn_error(
                original,
                "Phase 2b permits exactly one evaluator invocation per attempt",
                evaluator=True,
            )
        self._evaluator_invocation_consumed = True
        try:
            if cwd.resolve(strict=True) != self._workspace.resolve(strict=True):
                raise ValueError("evaluator cwd differs from the attempt workspace")
            self._validate_bubblewrap()
            isolated = self._isolated_evaluator_command(original)
            bubblewrap_command = self._evaluator_bubblewrap_command(isolated)
        except (IndexError, OSError, ValueError) as exc:
            cleanup_failed = False
            try:
                self._record_resource_not_invoked(
                    "evaluator", "not-invoked-preflight-rejected"
                )
            except BaseException:
                cleanup_failed = True
            try:
                if self._clear_home() is not None:
                    cleanup_failed = True
            except BaseException:
                cleanup_failed = True
            return self._sanitized_spawn_error(
                original,
                "unable to create bubblewrap-isolated evaluator invocation: "
                f"isolation preflight rejected it ({type(exc).__name__})"
                + (
                    " and terminal cleanup was incomplete"
                    if cleanup_failed
                    else ""
                ),
                evaluator=True,
            )
        except BaseException:
            try:
                self._record_resource_not_invoked(
                    "evaluator", "not-invoked-preflight-interrupted"
                )
            except BaseException:
                pass
            try:
                self._clear_home()
            except BaseException:
                pass
            raise
        try:
            raw_result = self._evaluator_delegate.run(
                bubblewrap_command,
                cwd,
                timeout_seconds,
            )
        except BaseException:
            self._finish_evaluator_invocation_cleanup()
            raise
        (
            observation_error,
            cleanup_error,
            cleanup_exception,
        ) = self._finish_evaluator_invocation_cleanup()
        if cleanup_exception is not None:
            return self._sanitized_spawn_error(
                original,
                "evaluator invocation terminal cleanup failed",
                evaluator=True,
            )
        if observation_error is not None and self._require_resource_observation:
            return self._sanitized_spawn_error(
                original,
                observation_error,
                evaluator=True,
            )
        if self._require_resource_observation and (
            self._resource_observations["evaluator"].get("outcome_status")
            != raw_result.status.value
        ):
            return self._sanitized_spawn_error(
                original,
                "resource supervisor result disagreed with the evaluator process result",
                evaluator=True,
            )
        if cleanup_error is not None:
            return self._sanitized_spawn_error(
                original,
                cleanup_error,
                evaluator=True,
            )
        return self._sanitize_result(
            raw_result,
            isolated,
            self._evaluator_path_replacements(),
        )

    def _finish_agent_invocation_cleanup(
        self,
    ) -> tuple[str | None, str | None, str | None, BaseException | None]:
        """Visit observation, credential finalization, and home clearing."""

        first_exception: BaseException | None = None
        observation_error: str | None = None
        credential_error: str | None = None
        cleanup_error: str | None = None
        try:
            observation_error = self._capture_resource_observation(
                "agent", self._delegate
            )
        except BaseException as exc:
            first_exception = exc
            try:
                self._resource_observations["agent"] = self._resource_placeholder(
                    "agent",
                    outcome_status="observation-unavailable",
                    reason="invoked-resource-observation-cleanup-failed",
                    cleanup_status="not-observed",
                    final_usage_scan_status="not-observed",
                )
            except BaseException:
                pass
        try:
            credential_error = self._finalize_credential_lease()
        except BaseException as exc:
            if first_exception is None:
                first_exception = exc
        try:
            cleanup_error = self._clear_home()
        except BaseException as exc:
            if first_exception is None:
                first_exception = exc
        return (
            observation_error,
            credential_error,
            cleanup_error,
            first_exception,
        )

    def _finish_evaluator_invocation_cleanup(
        self,
    ) -> tuple[str | None, str | None, BaseException | None]:
        """Visit evaluator observation and home clearing exactly once each."""

        first_exception: BaseException | None = None
        observation_error: str | None = None
        cleanup_error: str | None = None
        try:
            observation_error = self._capture_resource_observation(
                "evaluator", self._evaluator_delegate
            )
        except BaseException as exc:
            first_exception = exc
            try:
                self._resource_observations["evaluator"] = (
                    self._resource_placeholder(
                        "evaluator",
                        outcome_status="observation-unavailable",
                        reason="invoked-resource-observation-cleanup-failed",
                        cleanup_status="not-observed",
                        final_usage_scan_status="not-observed",
                    )
                )
            except BaseException:
                pass
        try:
            cleanup_error = self._clear_home()
        except BaseException as exc:
            if first_exception is None:
                first_exception = exc
        return observation_error, cleanup_error, first_exception

    def _capture_resource_observation(
        self,
        role: str,
        delegate: ProcessRunner,
    ) -> str | None:
        observation = getattr(delegate, "last_observation", None)
        renderer = getattr(observation, "as_dict", None)
        if callable(renderer):
            try:
                rendered = renderer()
            except BaseException:
                rendered = None
            if isinstance(rendered, dict):
                expected_policy = self._resource_policies[role]
                expected_sha256 = _canonical_sha256(expected_policy.as_dict())
                if rendered.get("invocation_name") != role:
                    self._resource_observations[role] = self._resource_placeholder(
                        role,
                        outcome_status="observation-invalid",
                        reason="invoked-resource-observation-role-mismatch",
                        cleanup_status="not-observed",
                        final_usage_scan_status="not-observed",
                    )
                    return "resource supervisor reported the wrong invocation role"
                if rendered.get("invocation_policy_sha256") != expected_sha256:
                    self._resource_observations[role] = self._resource_placeholder(
                        role,
                        outcome_status="observation-invalid",
                        reason="invoked-resource-observation-policy-mismatch",
                        cleanup_status="not-observed",
                        final_usage_scan_status="not-observed",
                    )
                    return "resource supervisor reported the wrong invocation policy hash"
                self._resource_observations[role] = dict(rendered)
                return None
        self._resource_observations[role] = self._resource_placeholder(
            role,
            outcome_status="observation-unavailable",
            reason="invoked-resource-observation-unavailable",
            cleanup_status="not-observed",
            final_usage_scan_status="not-observed",
        )
        return "resource supervisor did not report its invocation observation"

    def _resource_placeholder(
        self,
        role: str,
        *,
        outcome_status: str,
        reason: str,
        cleanup_status: str,
        final_usage_scan_status: str,
    ) -> dict[str, object]:
        policy = self._resource_policies[role]
        return {
            "schema_version": RESOURCE_SUPERVISOR_SCHEMA,
            "invocation_name": role,
            "invocation_policy_sha256": _canonical_sha256(policy.as_dict()),
            "outcome_status": outcome_status,
            "reason": reason,
            "cleanup_succeeded": None,
            "cleanup_status": cleanup_status,
            "final_usage_scan_completed": False,
            "final_usage_scan_status": final_usage_scan_status,
            "namespace_tmp_pinned_before_exec": False,
            "peak_processes": 0,
            "peak_aggregate_rss_bytes": 0,
            "observed_aggregate_cpu_seconds": 0.0,
            "observed_aggregate_write_bytes": 0,
            "stdout_bytes_seen": 0,
            "stderr_bytes_seen": 0,
            "stdout_truncated": False,
            "stderr_truncated": False,
        }

    def _record_resource_not_invoked(self, role: str, reason: str) -> None:
        self._resource_observations[role] = self._resource_placeholder(
            role,
            outcome_status="not-invoked",
            reason=reason,
            cleanup_status="not-required",
            final_usage_scan_status="not-applicable",
        )

    def finalize_resource_observations(self, missing_reason: str) -> None:
        """Bind the terminal reason used for either role never invoked."""

        if not missing_reason.startswith("not-invoked-"):
            raise ValueError("terminal resource reason must describe a non-invocation")
        self._terminal_missing_resource_reason = missing_reason

    def resource_observations(self) -> tuple[dict[str, object], ...]:
        """Return exactly one path-free terminal record for each required role."""

        records: list[dict[str, object]] = []
        for role in ("agent", "evaluator"):
            record = dict(
                self._resource_observations.get(role)
                or self._resource_placeholder(
                    role,
                    outcome_status="not-invoked",
                    reason=self._terminal_missing_resource_reason,
                    cleanup_status="not-required",
                    final_usage_scan_status="not-applicable",
                )
            )
            if role == "agent":
                record["credential_refresh_status"] = (
                    self._credential_refresh_status
                )
            records.append(record)
        return tuple(records)

    def resource_observation_fallback_placeholders(
        self,
        reason: str,
    ) -> tuple[dict[str, object], ...]:
        """Return deterministic two-role evidence if normal rendering fails."""

        records: list[dict[str, object]] = []
        for role in ("agent", "evaluator"):
            record = self._resource_placeholder(
                role,
                outcome_status="observation-unavailable",
                reason=reason,
                cleanup_status="not-observed",
                final_usage_scan_status="not-observed",
            )
            if role == "agent":
                record["credential_refresh_status"] = (
                    self._credential_refresh_status
                )
            records.append(record)
        return tuple(records)

    def _validate_bubblewrap(self) -> None:
        if BUBBLEWRAP_EXECUTABLE.is_symlink():
            raise OSError("bubblewrap executable is a symlink")
        executable = BUBBLEWRAP_EXECUTABLE.resolve(strict=True)
        executable_stat = executable.stat(follow_symlinks=False)
        if not stat.S_ISREG(executable_stat.st_mode) or not os.access(executable, os.X_OK):
            raise OSError("bubblewrap executable is not a regular executable")
        if _sha256(executable.read_bytes()) != self._expected_bubblewrap_sha256:
            raise OSError("bubblewrap binary hash changed")

    def _prepare_home(self) -> tuple[Path | None, Path | None]:
        self._home.parent.mkdir(parents=True, exist_ok=True)
        if self._home.parent.is_symlink():
            raise OSError("isolated agent-home parent is a symlink")
        self._home.mkdir(mode=0o700, exist_ok=False)
        self._home_owned = True
        config_directory_by_agent = {
            "claude-code": ".claude",
            "codex": ".codex",
        }
        config_directory_name = config_directory_by_agent.get(self._agent_base_id)
        if config_directory_name is None:
            raise OSError("unsupported isolated agent base")
        config_directory = self._home / config_directory_name
        config_directory.mkdir(mode=0o700)
        if self._credential_home is None:
            return None, None
        self._credential_refresh_status = "invalid"
        relative_credential = ISOLATED_AGENT_CREDENTIAL_PATHS.get(self._agent_base_id)
        if relative_credential is None:
            raise OSError("unsupported authenticated isolated agent base")
        cache_stat = self._credential_home.stat(follow_symlinks=False)
        if (
            self._credential_home.is_symlink()
            or not stat.S_ISDIR(cache_stat.st_mode)
            or cache_stat.st_uid != os.geteuid()
            or stat.S_IMODE(cache_stat.st_mode) != 0o700
        ):
            raise OSError("credential cache home is not a private owned directory")
        source = self._credential_home / relative_credential
        source_parent = source.parent
        parent_stat = source_parent.stat(follow_symlinks=False)
        if (
            source_parent.is_symlink()
            or not stat.S_ISDIR(parent_stat.st_mode)
            or parent_stat.st_uid != os.geteuid()
            or stat.S_IMODE(parent_stat.st_mode) != 0o700
        ):
            raise OSError("credential cache provider directory is not private")
        target = self._home / relative_credential
        target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        lease = self._lease_and_copy_credential(
            source,
            target,
            cache_stat=cache_stat,
            source_parent_stat=parent_stat,
        )
        self._credential_lease = lease
        self._credential_refresh_status = "pending"
        if sum(1 for path in self._home.rglob("*") if not path.is_dir()) != 1:
            raise OSError("isolated agent home credential inventory drifted")
        return source, target

    def _lease_and_copy_credential(
        self,
        source: Path,
        target: Path,
        *,
        cache_stat: os.stat_result,
        source_parent_stat: os.stat_result,
    ) -> _CredentialLease:
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            directory_flags |= os.O_NOFOLLOW
        cache_home_fd = os.open(self._credential_home, directory_flags)
        opened_cache = os.fstat(cache_home_fd)
        if (
            (opened_cache.st_dev, opened_cache.st_ino)
            != (cache_stat.st_dev, cache_stat.st_ino)
            or opened_cache.st_uid != os.geteuid()
            or stat.S_IMODE(opened_cache.st_mode) != 0o700
        ):
            _close_owned_or_raise(
                (cache_home_fd,), "credential cache home validation"
            )
            raise OSError("credential cache home changed while it was opened")
        provider_directory_name = source.parent.name
        try:
            source_directory_fd = os.open(
                provider_directory_name,
                directory_flags,
                dir_fd=cache_home_fd,
            )
        except BaseException:
            _close_owned_or_raise(
                (cache_home_fd,), "credential provider open failure"
            )
            raise
        opened_parent = os.fstat(source_directory_fd)
        if (
            (opened_parent.st_dev, opened_parent.st_ino)
            != (source_parent_stat.st_dev, source_parent_stat.st_ino)
            or opened_parent.st_uid != os.geteuid()
            or stat.S_IMODE(opened_parent.st_mode) != 0o700
        ):
            _close_owned_or_raise(
                (source_directory_fd, cache_home_fd),
                "credential provider validation",
            )
            raise OSError(
                "credential cache provider directory changed while it was opened"
            )
        source_fd = -1
        lock_fd = -1
        try:
            lock_flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC
            source_flags = os.O_RDWR | os.O_CLOEXEC
            target_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
            if hasattr(os, "O_NOFOLLOW"):
                lock_flags |= os.O_NOFOLLOW
                source_flags |= os.O_NOFOLLOW
                target_flags |= os.O_NOFOLLOW
            lock_fd = os.open(
                ".phase2b-credential.lock",
                lock_flags,
                0o600,
                dir_fd=source_directory_fd,
            )
            lock_stat = os.fstat(lock_fd)
            self._validate_private_file_stat(lock_stat, "credential cache lock")
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            source_fd = os.open(
                source.name,
                source_flags,
                dir_fd=source_directory_fd,
            )
            source_stat = os.fstat(source_fd)
            self._validate_private_file_stat(source_stat, "configured credential")
            payload = self._read_validated_credential(source_fd, source_stat)
            target_fd = os.open(target, target_flags, 0o600)
            try:
                self._write_all(target_fd, payload)
                os.fsync(target_fd)
            finally:
                _close_owned_or_raise(
                    (target_fd,), "isolated credential copy"
                )
            return _CredentialLease(
                source=source,
                target=target,
                source_name=source.name,
                provider_directory_name=provider_directory_name,
                cache_home_fd=cache_home_fd,
                source_directory_fd=source_directory_fd,
                source_fd=source_fd,
                lock_fd=lock_fd,
                cache_home_device=cache_stat.st_dev,
                cache_home_inode=cache_stat.st_ino,
                source_directory_device=source_parent_stat.st_dev,
                source_directory_inode=source_parent_stat.st_ino,
                source_device=source_stat.st_dev,
                source_inode=source_stat.st_ino,
                preimage_sha256=hashlib.sha256(payload).hexdigest(),
            )
        except BaseException:
            _close_owned_or_raise(
                (
                    source_fd,
                    lock_fd,
                    source_directory_fd,
                    cache_home_fd,
                ),
                "credential lease construction failure",
            )
            raise

    @staticmethod
    def _validate_private_file_stat(observed: os.stat_result, label: str) -> None:
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_nlink != 1
            or observed.st_uid != os.geteuid()
            or stat.S_IMODE(observed.st_mode) != 0o600
            or observed.st_size > _MAX_CREDENTIAL_BYTES
        ):
            raise OSError(f"{label} failed private-file validation")

    def _read_validated_credential(
        self,
        descriptor: int,
        before: os.stat_result,
    ) -> bytes:
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        remaining = _MAX_CREDENTIAL_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        after = os.fstat(descriptor)
        self._validate_private_file_stat(after, "configured credential")
        if (
            len(payload) > _MAX_CREDENTIAL_BYTES
            or (before.st_dev, before.st_ino, before.st_size)
            != (after.st_dev, after.st_ino, after.st_size)
            or len(payload) != after.st_size
        ):
            raise OSError("configured credential changed while it was read")
        try:
            parsed = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OSError("configured credential is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise OSError("configured credential JSON is not an object")
        return payload

    @staticmethod
    def _write_all(descriptor: int, payload: bytes) -> None:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("credential write made no progress")
            view = view[written:]

    def _validate_canonical_credential_chain(
        self,
        lease: _CredentialLease,
        *,
        expected_sha256: str | None = None,
        expected_file_identity: tuple[int, int] | None = None,
    ) -> None:
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
        file_flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            directory_flags |= os.O_NOFOLLOW
            file_flags |= os.O_NOFOLLOW
        cache_fd = os.open(self._credential_home, directory_flags)
        provider_fd = -1
        credential_fd = -1
        try:
            cache_now = os.fstat(cache_fd)
            if (
                (cache_now.st_dev, cache_now.st_ino)
                != (lease.cache_home_device, lease.cache_home_inode)
                or cache_now.st_uid != os.geteuid()
                or stat.S_IMODE(cache_now.st_mode) != 0o700
            ):
                raise OSError("credential cache home identity changed")
            provider_fd = os.open(
                lease.provider_directory_name,
                directory_flags,
                dir_fd=cache_fd,
            )
            provider_now = os.fstat(provider_fd)
            if (
                (provider_now.st_dev, provider_now.st_ino)
                != (
                    lease.source_directory_device,
                    lease.source_directory_inode,
                )
                or provider_now.st_uid != os.geteuid()
                or stat.S_IMODE(provider_now.st_mode) != 0o700
            ):
                raise OSError("credential cache provider identity changed")
            if expected_sha256 is None and expected_file_identity is None:
                return
            credential_fd = os.open(
                lease.source_name,
                file_flags,
                dir_fd=provider_fd,
            )
            credential_before = os.fstat(credential_fd)
            self._validate_private_file_stat(
                credential_before, "canonical credential cache file"
            )
            payload = self._read_validated_credential(
                credential_fd, credential_before
            )
            if (
                expected_file_identity is not None
                and (credential_before.st_dev, credential_before.st_ino)
                != expected_file_identity
            ):
                raise OSError("canonical credential cache file identity changed")
            if (
                expected_sha256 is not None
                and hashlib.sha256(payload).hexdigest() != expected_sha256
            ):
                raise OSError("canonical credential cache payload changed")
        finally:
            _close_owned_or_raise(
                (credential_fd, provider_fd, cache_fd),
                "canonical credential validation",
            )

    def _finalize_credential_lease(self) -> str | None:
        lease = self._credential_lease
        if lease is None:
            return None
        self._credential_lease = None
        temporary_name: str | None = None
        try:
            self._validate_canonical_credential_chain(
                lease,
                expected_sha256=lease.preimage_sha256,
                expected_file_identity=(lease.source_device, lease.source_inode),
            )
            read_flags = os.O_RDONLY | os.O_CLOEXEC
            if hasattr(os, "O_NOFOLLOW"):
                read_flags |= os.O_NOFOLLOW
            target_fd = os.open(lease.target, read_flags)
            try:
                target_before = os.fstat(target_fd)
                self._validate_private_file_stat(
                    target_before, "refreshed credential"
                )
                payload = self._read_validated_credential(
                    target_fd, target_before
                )
            finally:
                _close_owned_or_raise(
                    (target_fd,), "refreshed credential read"
                )

            current_fd = os.open(
                lease.source_name,
                read_flags,
                dir_fd=lease.source_directory_fd,
            )
            try:
                current_before = os.fstat(current_fd)
                self._validate_private_file_stat(
                    current_before, "credential cache compare-and-swap source"
                )
                current_payload = self._read_validated_credential(
                    current_fd, current_before
                )
            finally:
                _close_owned_or_raise(
                    (current_fd,), "credential compare-and-swap read"
                )
            if (
                (current_before.st_dev, current_before.st_ino)
                != (lease.source_device, lease.source_inode)
                or hashlib.sha256(current_payload).hexdigest()
                != lease.preimage_sha256
            ):
                raise OSError("credential cache changed outside its exclusive lease")

            refreshed_sha256 = hashlib.sha256(payload).hexdigest()
            if refreshed_sha256 == lease.preimage_sha256:
                self._validate_canonical_credential_chain(
                    lease,
                    expected_sha256=lease.preimage_sha256,
                    expected_file_identity=(
                        lease.source_device,
                        lease.source_inode,
                    ),
                )
                self._credential_refresh_status = "unchanged"
                return None

            temporary_name = (
                f".phase2b-next-credential-{os.getpid()}-"
                f"{secrets.token_hex(8)}"
            )
            create_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
            if hasattr(os, "O_NOFOLLOW"):
                create_flags |= os.O_NOFOLLOW
            temporary_fd = os.open(
                temporary_name,
                create_flags,
                0o600,
                dir_fd=lease.source_directory_fd,
            )
            try:
                self._write_all(temporary_fd, payload)
                os.fsync(temporary_fd)
                temporary_stat = os.fstat(temporary_fd)
            finally:
                _close_owned_or_raise(
                    (temporary_fd,), "credential replacement staging"
                )
            os.replace(
                temporary_name,
                lease.source_name,
                src_dir_fd=lease.source_directory_fd,
                dst_dir_fd=lease.source_directory_fd,
            )
            temporary_name = None
            os.fsync(lease.source_directory_fd)
            self._validate_canonical_credential_chain(
                lease,
                expected_sha256=refreshed_sha256,
                expected_file_identity=(temporary_stat.st_dev, temporary_stat.st_ino),
            )
            self._credential_refresh_status = "refreshed"
            return None
        except (OSError, ValueError):
            self._credential_refresh_status = "invalid"
            return "credential refresh validation or persistence failed"
        finally:
            active_exception = sys.exc_info()[1]
            terminal_cleanup_error: BaseException | None = None
            if temporary_name is not None:
                try:
                    os.unlink(
                        temporary_name,
                        dir_fd=lease.source_directory_fd,
                    )
                except BaseException as exc:
                    terminal_cleanup_error = exc
            try:
                _close_owned_or_raise(
                    (
                        lease.source_fd,
                        lease.lock_fd,
                        lease.source_directory_fd,
                        lease.cache_home_fd,
                    ),
                    "credential lease finalization",
                )
            except BaseException as exc:
                if terminal_cleanup_error is None:
                    terminal_cleanup_error = exc
            if terminal_cleanup_error is not None and active_exception is None:
                raise terminal_cleanup_error

    def _release_credential_lease(self) -> None:
        lease = self._credential_lease
        self._credential_lease = None
        if lease is None:
            return
        _close_owned_or_raise(
            (
                lease.source_fd,
                lease.lock_fd,
                lease.source_directory_fd,
                lease.cache_home_fd,
            ),
            "credential lease release",
        )

    def _isolated_agent_command(
        self,
        command: tuple[str, ...],
        runtime: _AgentRuntime,
    ) -> tuple[str, ...]:
        if self._agent_base_id == "claude-code":
            expected_prefix = (
                "claude",
                "--print",
                "--output-format",
                "json",
                "--permission-mode",
                self._agent_spec.permission_mode,
                *(
                    ("--model", self._agent_spec.model)
                    if self._agent_spec.model is not None
                    else ()
                ),
            )
            if (
                len(command) != len(expected_prefix) + 1
                or command[0] != expected_prefix[0]
                or command[1:-1] != expected_prefix[1:]
            ):
                raise ValueError("Claude adapter command shape drifted")
            prompt = command[-1]
            if not prompt or prompt.startswith("-") or "\x00" in prompt:
                raise ValueError("Claude prompt cannot be parsed as a safe positional value")
            return (
                *runtime.command_prefix,
                "--safe-mode",
                "--restricted",
                "--no-session-persistence",
                "--permission-prompts",
                "none",
                "--disable-slash-commands",
                "--no-chrome",
                "--strict-mcp-config",
                "--mcp-config",
                '{"mcpServers":{}}',
                "--settings",
                _claude_isolation_settings(),
                "--tools",
                "Bash,Edit,Read,Write,Glob,Grep",
                "--disallowedTools",
                "WebFetch,WebSearch,Agent",
                *expected_prefix[1:],
                prompt,
            )
        if self._agent_base_id != "codex":
            raise ValueError("unsupported isolated agent base")
        expected_prefix = (
            "codex",
            "exec",
            "--sandbox",
            self._agent_spec.permission_mode,
            "--cd",
            str(self._workspace),
            "--json",
            *(("-m", self._agent_spec.model) if self._agent_spec.model else ()),
            *(
                ("-c", f"model_reasoning_effort={self._agent_spec.reasoning_tier}")
                if self._agent_spec.reasoning_tier
                else ()
            ),
        )
        if (
            len(command) != len(expected_prefix) + 1
            or command[0] != expected_prefix[0]
            or command[1:-1] != expected_prefix[1:]
        ):
            raise ValueError("Codex adapter command shape drifted")
        prompt = command[-1]
        if not prompt or prompt.startswith("-") or "\x00" in prompt:
            raise ValueError("Codex prompt cannot be parsed as a safe positional value")
        remaining = (
            "--json",
            *(("-m", self._agent_spec.model) if self._agent_spec.model else ()),
            *(
                ("-c", f"model_reasoning_effort={self._agent_spec.reasoning_tier}")
                if self._agent_spec.reasoning_tier
                else ()
            ),
            prompt,
        )
        return (
            *runtime.command_prefix,
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "--strict-config",
            "--cd",
            _NAMESPACE_WORKSPACE,
            *_codex_isolation_config_arguments(),
            *remaining,
        )

    def _bubblewrap_command(
        self,
        agent_command: tuple[str, ...],
        runtime: _AgentRuntime,
        *,
        credential_source: Path | None,
        credential_target: Path | None,
    ) -> tuple[str, ...]:
        git_metadata = self._workspace / ".git"
        if git_metadata.is_symlink() or not git_metadata.is_dir():
            raise OSError("attempt workspace Git metadata is not an isolated directory")
        arguments: list[str] = [
            str(BUBBLEWRAP_EXECUTABLE),
            "--die-with-parent",
            "--new-session",
            "--unshare-all",
            "--share-net",
            "--hostname",
            "phase2b",
            "--clearenv",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--dir",
            "/run",
            "--dir",
            "/etc",
            "--dir",
            _NAMESPACE_BIN,
            "--dir",
            _NAMESPACE_HELPER_BIN,
            "--dir",
            _NAMESPACE_NATIVE_HELPER,
            "--dir",
            _NAMESPACE_RUNTIME,
            "--dir",
            f"{_NAMESPACE_RUNTIME}/node",
            "--dir",
            f"{_NAMESPACE_RUNTIME}/node/bin",
            "--dir",
            f"{_NAMESPACE_RUNTIME}/node/lib",
            "--dir",
            f"{_NAMESPACE_RUNTIME}/node/lib/node_modules",
        ]
        for path in _SYSTEM_READ_ONLY_DIRECTORIES:
            if Path(path).exists():
                arguments.extend(("--ro-bind", path, path))
        for path in _SYSTEM_READ_ONLY_ETC_PATHS:
            if Path(path).exists():
                arguments.extend(("--ro-bind", path, path))
        arguments.extend((
            "--dir",
            _NAMESPACE_WORKSPACE,
            "--bind",
            str(self._workspace),
            _NAMESPACE_WORKSPACE,
            "--ro-bind",
            str(git_metadata),
            f"{_NAMESPACE_WORKSPACE}/.git",
            "--dir",
            _NAMESPACE_HOME,
            "--bind",
            str(self._home),
            _NAMESPACE_HOME,
        ))
        if credential_source is not None and credential_target is not None:
            # The validated credential copy already lives inside this fresh,
            # watched home. The trusted CLI core may rotate it in place. The
            # nested model shell gets a separate empty read-only home.
            credential_target.relative_to(self._home)
            if (
                self._credential_lease is None
                or credential_source != self._credential_lease.source
                or credential_target != self._credential_lease.target
            ):
                raise OSError("credential lease changed before namespace creation")
        mounts = (*runtime.mounts, *self._toolchain_mounts)
        targets: set[str] = set()
        for mount in mounts:
            if mount.target in targets:
                continue
            targets.add(mount.target)
            arguments.extend(("--ro-bind", str(mount.source), mount.target))
        if f"{_NAMESPACE_RUNTIME}/node/lib/node_modules/npm" in targets:
            arguments.extend((
                "--symlink",
                "../lib/node_modules/npm/bin/npm-cli.js",
                f"{_NAMESPACE_RUNTIME}/node/bin/npm",
                "--symlink",
                "../lib/node_modules/npm/bin/npx-cli.js",
                f"{_NAMESPACE_RUNTIME}/node/bin/npx",
            ))
        for key, value in sorted(_NAMESPACE_ENVIRONMENT.items()):
            arguments.extend(("--setenv", key, value))
        # The shared ProcessRunner API intentionally does not expose stdin. Use
        # positional shell arguments (never interpolation) to give only the
        # agent invocation deterministic EOF instead of inheriting the
        # orchestrator's terminal or pipe.
        arguments.extend((
            "--remount-ro",
            "/",
            "--remount-ro",
            "/dev",
            "--chdir",
            _NAMESPACE_WORKSPACE,
            "--",
            "/bin/sh",
            "-c",
            'exec "$@" </dev/null',
            "phase2b-agent",
            *agent_command,
        ))
        return tuple(arguments)

    def _isolated_evaluator_command(
        self,
        command: tuple[str, ...],
    ) -> tuple[str, ...]:
        if not command:
            raise ValueError("evaluator command is empty")
        result: list[str] = []
        allowed_absolute_roots = tuple(
            Path(path) for path in _SYSTEM_READ_ONLY_DIRECTORIES
        )
        for token in command:
            configured = Path(token).expanduser()
            if not configured.is_absolute():
                result.append(token)
                continue
            resolved = configured.resolve(strict=True)
            if resolved == self._evaluator_root or resolved.is_relative_to(
                self._evaluator_root
            ):
                relative = resolved.relative_to(self._evaluator_root).as_posix()
                result.append(
                    _NAMESPACE_EVALUATOR
                    if not relative
                    else f"{_NAMESPACE_EVALUATOR}/{relative}"
                )
            elif resolved == self._workspace or resolved.is_relative_to(
                self._workspace
            ):
                relative = resolved.relative_to(self._workspace).as_posix()
                result.append(
                    _NAMESPACE_WORKSPACE
                    if not relative
                    else f"{_NAMESPACE_WORKSPACE}/{relative}"
                )
            elif any(
                resolved == root or resolved.is_relative_to(root)
                for root in allowed_absolute_roots
            ):
                result.append(str(resolved))
            else:
                raise ValueError(
                    "evaluator command contains an absolute path outside its namespace"
                )
        return tuple(result)

    def _evaluator_bubblewrap_command(
        self,
        evaluator_command: tuple[str, ...],
    ) -> tuple[str, ...]:
        git_metadata = self._workspace / ".git"
        if git_metadata.is_symlink() or not git_metadata.is_dir():
            raise OSError("attempt workspace Git metadata is not an isolated directory")
        arguments: list[str] = [
            str(BUBBLEWRAP_EXECUTABLE),
            "--die-with-parent",
            "--new-session",
            "--unshare-all",
            "--hostname",
            "phase2b-evaluator",
            "--clearenv",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--dir",
            "/proc",
            "--dir",
            "/run",
            "--dir",
            "/etc",
            "--dir",
            _NAMESPACE_EVALUATOR_HOME,
            "--dir",
            str(PurePosixPath(_NAMESPACE_EVALUATOR_HELPER).parent),
            "--dir",
            _NAMESPACE_RUNTIME,
            "--dir",
            f"{_NAMESPACE_RUNTIME}/node",
            "--dir",
            f"{_NAMESPACE_RUNTIME}/node/bin",
            "--dir",
            f"{_NAMESPACE_RUNTIME}/node/lib",
            "--dir",
            f"{_NAMESPACE_RUNTIME}/node/lib/node_modules",
        ]
        for path in _SYSTEM_READ_ONLY_DIRECTORIES:
            if Path(path).exists():
                arguments.extend(("--ro-bind", path, path))
        for path in _SYSTEM_READ_ONLY_ETC_PATHS:
            if path == "/etc/resolv.conf":
                continue
            if Path(path).exists():
                arguments.extend(("--ro-bind", path, path))
        arguments.extend((
            "--dir",
            _NAMESPACE_WORKSPACE,
            "--bind",
            str(self._workspace),
            _NAMESPACE_WORKSPACE,
            "--ro-bind",
            str(git_metadata),
            f"{_NAMESPACE_WORKSPACE}/.git",
            "--ro-bind",
            str(self._evaluator_root),
            _NAMESPACE_EVALUATOR,
            "--bind",
            str(self._home),
            _NAMESPACE_EVALUATOR_HOME,
            "--ro-bind",
            str(self._evaluator_native_helper),
            _NAMESPACE_EVALUATOR_HELPER,
        ))
        toolchain_mounts = self._toolchain_mounts
        targets: set[str] = set()
        for mount in toolchain_mounts:
            if mount.target in targets:
                continue
            targets.add(mount.target)
            arguments.extend(("--ro-bind", str(mount.source), mount.target))
        if f"{_NAMESPACE_RUNTIME}/node/lib/node_modules/npm" in targets:
            arguments.extend((
                "--symlink",
                "../lib/node_modules/npm/bin/npm-cli.js",
                f"{_NAMESPACE_RUNTIME}/node/bin/npm",
                "--symlink",
                "../lib/node_modules/npm/bin/npx-cli.js",
                f"{_NAMESPACE_RUNTIME}/node/bin/npx",
            ))
        for key, value in sorted(_EVALUATOR_ENVIRONMENT.items()):
            arguments.extend(("--setenv", key, value))
        arguments.extend((
            "--remount-ro",
            "/",
            "--remount-ro",
            "/dev",
            "--chdir",
            _NAMESPACE_WORKSPACE,
            "--",
            "/bin/sh",
            "-c",
            'exec "$@" </dev/null',
            "phase2b-evaluator",
            _NAMESPACE_EVALUATOR_HELPER,
            "--sandbox-policy-cwd",
            _NAMESPACE_WORKSPACE,
            "--command-cwd",
            _NAMESPACE_WORKSPACE,
            "--permission-profile",
            _evaluator_native_permission_profile(),
            "--apply-seccomp-then-exec",
            "--",
            *evaluator_command,
        ))
        return tuple(arguments)

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

    def _agent_path_replacements(
        self,
        runtime: _AgentRuntime,
        *,
        credential_source: Path | None,
        credential_target: Path | None,
    ) -> tuple[tuple[str, str], ...]:
        mappings: list[tuple[Path, str]] = [
            (self._workspace / ".git", f"{_NAMESPACE_WORKSPACE}/.git"),
            (self._workspace, _NAMESPACE_WORKSPACE),
            (self._home, _NAMESPACE_HOME),
            (self._toolchain_home, "<redacted-host-home>"),
        ]
        mappings.extend((mount.source, mount.target) for mount in runtime.mounts)
        mappings.extend(
            (mount.source, mount.target)
            for mount in self._toolchain_mounts
        )
        if credential_source is not None and credential_target is not None:
            relative = credential_target.relative_to(self._home).as_posix()
            mappings.append((
                credential_source,
                f"{_NAMESPACE_HOME}/{relative}",
            ))
        return _normalized_path_replacements(mappings)

    def _evaluator_path_replacements(self) -> tuple[tuple[str, str], ...]:
        mappings: list[tuple[Path, str]] = [
            (self._workspace / ".git", f"{_NAMESPACE_WORKSPACE}/.git"),
            (self._workspace, _NAMESPACE_WORKSPACE),
            (self._evaluator_root, _NAMESPACE_EVALUATOR),
            (self._home, _NAMESPACE_EVALUATOR_HOME),
            (self._evaluator_native_helper, _NAMESPACE_EVALUATOR_HELPER),
            (self._toolchain_home, "<redacted-host-home>"),
        ]
        mappings.extend(
            (mount.source, mount.target)
            for mount in self._toolchain_mounts
        )
        return _normalized_path_replacements(mappings)

    @staticmethod
    def _sanitize_result(
        result: ProcessResult,
        stable_command: Sequence[str],
        replacements: Sequence[tuple[str, str]],
    ) -> ProcessResult:
        return ProcessResult(
            tuple(stable_command),
            result.status,
            _replace_host_paths(result.stdout, replacements),
            _replace_host_paths(result.stderr, replacements),
            result.exit_code,
            result.duration_ms,
        )

    def _sanitized_spawn_error(
        self,
        command: Sequence[str],
        message: str,
        *,
        evaluator: bool = False,
    ) -> ProcessResult:
        replacements = (
            self._evaluator_path_replacements()
            if evaluator
            else _normalized_path_replacements((
                (self._workspace / ".git", f"{_NAMESPACE_WORKSPACE}/.git"),
                (self._workspace, _NAMESPACE_WORKSPACE),
                (self._home, _NAMESPACE_HOME),
                (self._evaluator_root, _NAMESPACE_EVALUATOR),
                (self._toolchain_home, "<redacted-host-home>"),
            ))
        )
        return ProcessResult(
            (
                "phase2b-evaluator" if evaluator else "phase2b-agent",
                "<rejected>",
            ),
            ExecutionStatus.SPAWN_ERROR,
            "",
            _replace_host_paths(message, replacements),
            None,
            0.0,
        )


def _normalized_path_replacements(
    mappings: Sequence[tuple[Path, str]],
) -> tuple[tuple[str, str], ...]:
    replacements: dict[str, str] = {}
    for source, target in mappings:
        configured = source.expanduser().absolute()
        replacements[str(configured)] = target
        try:
            replacements[str(configured.resolve(strict=True))] = target
        except OSError:
            pass
    return tuple(sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True))


def _replace_host_paths(
    value: str,
    replacements: Sequence[tuple[str, str]],
) -> str:
    for source, target in replacements:
        value = value.replace(source, target)
    return value


def _resolve_agent_runtime(agent_base_id: str, executable: str) -> _AgentRuntime:
    located = shutil.which(executable)
    if located is None:
        raise OSError(f"unable to resolve {executable} executable")
    configured = Path(located).expanduser().absolute()
    resolved = configured.resolve(strict=True)
    if resolved.is_symlink() or not resolved.is_file():
        raise OSError(f"{executable} executable is not a regular file")
    if agent_base_id == "claude-code":
        wrapper = _CLAUDE_BWRAP_WRAPPER.resolve(strict=True)
        if (
            wrapper.is_symlink()
            or not wrapper.is_file()
            or not os.access(wrapper, os.X_OK)
            or _sha256(wrapper.read_bytes()) != _CLAUDE_BWRAP_WRAPPER_SHA256
        ):
            raise OSError("Claude proc-free bubblewrap wrapper integrity changed")
        return _AgentRuntime(
            command_prefix=(f"{_NAMESPACE_BIN}/claude",),
            mounts=(
                _RuntimeMount(resolved, f"{_NAMESPACE_BIN}/claude"),
                _RuntimeMount(
                    wrapper,
                    f"{_NAMESPACE_HELPER_BIN}/phase2b-claude-bwrap",
                ),
            ),
        )
    if agent_base_id != "codex":
        raise ValueError("unsupported isolated agent base")
    with resolved.open("rb") as stream:
        header = stream.read(4)
    if header == b"\x7fELF":
        return _AgentRuntime(
            command_prefix=(f"{_NAMESPACE_BIN}/codex",),
            mounts=(_RuntimeMount(resolved, f"{_NAMESPACE_BIN}/codex"),),
        )
    package_root = resolved.parent.parent
    if not (package_root / "package.json").is_file():
        raise OSError("unable to resolve the Codex CLI package root")
    node = shutil.which("node")
    if node is None:
        raise OSError("unable to resolve the Node.js runtime for Codex")
    node_path = Path(node).resolve(strict=True)
    native_candidates = tuple(
        package_root.glob("node_modules/@openai/codex-*/vendor/*/bin/codex")
    )
    if len(native_candidates) != 1 or not native_candidates[0].is_file():
        raise OSError("unable to resolve the Codex native sandbox helper")
    wrapper = _CODEX_SANDBOX_WRAPPER.resolve(strict=True)
    if (
        wrapper.is_symlink()
        or not wrapper.is_file()
        or not os.access(wrapper, os.X_OK)
        or _sha256(wrapper.read_bytes()) != _CODEX_SANDBOX_WRAPPER_SHA256
    ):
        raise OSError("Codex proc-free sandbox wrapper integrity changed")
    return _AgentRuntime(
        command_prefix=(
            f"{_NAMESPACE_BIN}/node",
            f"{_NAMESPACE_RUNTIME}/codex/{resolved.relative_to(package_root).as_posix()}",
        ),
        mounts=(
            _RuntimeMount(node_path, f"{_NAMESPACE_BIN}/node"),
            _RuntimeMount(package_root, f"{_NAMESPACE_RUNTIME}/codex"),
            _RuntimeMount(
                wrapper,
                f"{_NAMESPACE_HELPER_BIN}/codex-linux-sandbox",
            ),
            _RuntimeMount(
                native_candidates[0].resolve(strict=True),
                f"{_NAMESPACE_NATIVE_HELPER}/codex-linux-sandbox",
            ),
        ),
    )


def _resolve_evaluator_native_helper() -> Path:
    runtime = _resolve_agent_runtime("codex", "codex")
    matches = tuple(
        mount.source
        for mount in runtime.mounts
        if mount.target == f"{_NAMESPACE_NATIVE_HELPER}/codex-linux-sandbox"
    )
    if len(matches) != 1:
        raise OSError("unable to resolve evaluator native sandbox helper")
    return matches[0]


def _optional_toolchain_mounts(home: Path | None) -> tuple[_RuntimeMount, ...]:
    candidates: list[tuple[Path, str]] = []
    node = shutil.which("node")
    if node is not None:
        configured_node = Path(node).expanduser().absolute()
        if configured_node.parent.name == "bin":
            node_root = configured_node.parent.parent.resolve(strict=True)
            candidates.append((
                configured_node.resolve(strict=True),
                f"{_NAMESPACE_RUNTIME}/node/bin/node",
            ))
            npm_package = node_root / "lib" / "node_modules" / "npm"
            candidates.append((
                npm_package,
                f"{_NAMESPACE_RUNTIME}/node/lib/node_modules/npm",
            ))
    if home is not None:
        candidates.extend((
            (home / ".local" / "go", f"{_NAMESPACE_RUNTIME}/go"),
            (home / ".cargo" / "bin", f"{_NAMESPACE_RUNTIME}/cargo/bin"),
            (home / ".rustup", f"{_NAMESPACE_RUNTIME}/rustup"),
        ))
        rustup_settings = home / ".rustup" / "settings.toml"
        if rustup_settings.is_file() and not rustup_settings.is_symlink():
            try:
                settings_text = rustup_settings.read_text(encoding="utf-8")
                match = re.search(
                    r'^default_toolchain\s*=\s*"([^"\\]+)"\s*$',
                    settings_text,
                    flags=re.MULTILINE,
                )
                default_toolchain = match.group(1) if match else None
            except OSError:
                default_toolchain = None
            if (
                isinstance(default_toolchain, str)
                and default_toolchain
                and Path(default_toolchain).name == default_toolchain
            ):
                candidates.append((
                    home / ".rustup" / "toolchains" / default_toolchain,
                    f"{_NAMESPACE_RUNTIME}/rust-toolchain",
                ))
    result = []
    for source, target in candidates:
        if source.is_symlink() or not (source.is_file() or source.is_dir()):
            continue
        result.append(_RuntimeMount(source.resolve(strict=True), target))
    return tuple(result)


def _system_runtime_mounts() -> tuple[_RuntimeMount, ...]:
    result: list[_RuntimeMount] = []
    for configured in (*_SYSTEM_READ_ONLY_DIRECTORIES, *_SYSTEM_READ_ONLY_ETC_PATHS):
        source = Path(configured)
        if source.exists():
            result.append(_RuntimeMount(source.resolve(strict=True), configured))
    return tuple(result)


def _content_tree_sha256(root: Path, logical_target: str) -> str:
    digest = hashlib.sha256()

    def visit(path: Path, relative: PurePosixPath) -> None:
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if stat.S_ISLNK(metadata.st_mode):
            digest.update(
                f"symlink:{relative}:{mode}:{os.readlink(path)}\0".encode("utf-8")
            )
            return
        if stat.S_ISREG(metadata.st_mode):
            digest.update(
                f"file:{relative}:{mode}:{metadata.st_size}\0".encode("utf-8")
            )
            descriptor: int | None = None
            try:
                flags = os.O_RDONLY | os.O_CLOEXEC
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                descriptor = os.open(path, flags)
                opened = os.fstat(descriptor)

                def stable_file_identity(observed: os.stat_result) -> tuple[int, ...]:
                    return (
                        observed.st_dev,
                        observed.st_ino,
                        observed.st_mode,
                        observed.st_size,
                        observed.st_mtime_ns,
                        observed.st_ctime_ns,
                        observed.st_nlink,
                    )

                if stable_file_identity(opened) != stable_file_identity(metadata):
                    raise OSError("runtime file changed while it was opened")
                chunk_bytes = 64 * 1024
                while True:
                    try:
                        chunk = os.read(descriptor, chunk_bytes)
                    except OSError as exc:
                        if exc.errno == errno.ENOMEM and chunk_bytes > 4 * 1024:
                            chunk_bytes //= 2
                            continue
                        raise
                    if not chunk:
                        break
                    digest.update(chunk)
                if stable_file_identity(os.fstat(descriptor)) != stable_file_identity(
                    metadata
                ):
                    raise OSError("runtime file changed while it was hashed")
            except PermissionError as exc:
                # The same uid executes the sandboxed command. Content which
                # cannot be read here cannot be read by that command either;
                # its full metadata remains in the in-run drift snapshot.
                digest.update(f"unreadable:{exc.errno}\0".encode("ascii"))
            except OSError as exc:
                raise OSError(
                    "unable to hash runtime file "
                    f"target={logical_target!r} relative={relative.as_posix()!r} "
                    f"size={metadata.st_size} errno={exc.errno!r}"
                ) from exc
            finally:
                if descriptor is not None:
                    _close_owned_or_raise(
                        (descriptor,), "runtime content hashing"
                    )
            return
        if stat.S_ISDIR(metadata.st_mode):
            digest.update(f"directory:{relative}:{mode}\0".encode("utf-8"))
            try:
                children = sorted(path.iterdir(), key=lambda child: child.name)
            except PermissionError as exc:
                digest.update(f"unreadable:{exc.errno}\0".encode("ascii"))
                return
            for child in children:
                visit(child, relative / child.name)
            return
        digest.update(
            f"other:{relative}:{metadata.st_mode}:{metadata.st_rdev}:"
            f"{metadata.st_size}\0".encode("utf-8")
        )

    visit(root, PurePosixPath("."))
    return digest.hexdigest()


def _target_bound_content_sha256(
    mounts: Sequence[_RuntimeMount],
    cache: dict[Path, str] | None = None,
) -> str:
    content_cache = cache if cache is not None else {}
    digest = hashlib.sha256()
    digest.update(b"phase2b-target-bound-recursive-sha256-v1\0")
    targets: set[str] = set()
    for mount in sorted(mounts, key=lambda item: item.target):
        if mount.target in targets:
            raise OSError(f"duplicate runtime closure target: {mount.target}")
        targets.add(mount.target)
        source = mount.source.resolve(strict=True)
        if source not in content_cache:
            content_cache[source] = _content_tree_sha256(source, mount.target)
        digest.update(
            f"target:{mount.target}\0content:{content_cache[source]}\0".encode(
                "utf-8"
            )
        )
    return digest.hexdigest()


def _runtime_metadata_sha256(mounts: Sequence[_RuntimeMount]) -> str:
    digest = hashlib.sha256()
    digest.update(b"phase2b-complete-lstat-metadata-v1\0")
    targets: set[str] = set()

    def visit(path: Path, target: str, relative: PurePosixPath) -> None:
        metadata = path.lstat()
        fields = (
            metadata.st_mode,
            metadata.st_uid,
            metadata.st_gid,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
            metadata.st_ino,
            metadata.st_dev,
            metadata.st_nlink,
            metadata.st_rdev,
        )
        digest.update(
            f"entry:{target}:{relative}:".encode("utf-8")
            + ":".join(str(value) for value in fields).encode("ascii")
            + b"\0"
        )
        if stat.S_ISLNK(metadata.st_mode):
            digest.update(f"link:{os.readlink(path)}\0".encode("utf-8"))
            return
        if not stat.S_ISDIR(metadata.st_mode):
            return
        try:
            children = sorted(path.iterdir(), key=lambda child: child.name)
        except PermissionError as exc:
            digest.update(f"unreadable:{exc.errno}\0".encode("ascii"))
            return
        for child in children:
            visit(child, target, relative / child.name)

    for mount in sorted(mounts, key=lambda item: item.target):
        if mount.target in targets:
            raise OSError(f"duplicate runtime metadata target: {mount.target}")
        targets.add(mount.target)
        visit(mount.source.resolve(strict=True), mount.target, PurePosixPath("."))
    return digest.hexdigest()


def _read_capability_value(path: str) -> dict[str, object]:
    try:
        return {
            "status": "observed",
            "value": Path(path).read_text(encoding="utf-8").strip(),
        }
    except (OSError, UnicodeError) as exc:
        return {"status": "unavailable", "error_type": type(exc).__name__}


def _landlock_abi() -> dict[str, object]:
    # landlock_create_ruleset is 444 on the Linux architectures supported by
    # the current pinned Phase 2b environment. The VERSION flag with a null
    # ruleset queries the kernel ABI without installing policy.
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        libc.syscall.restype = ctypes.c_long
        result = libc.syscall(444, 0, 0, 1)
        if result >= 0:
            return {"status": "observed", "abi": int(result), "syscall_number": 444}
        return {
            "status": "error",
            "errno": ctypes.get_errno(),
            "syscall_number": 444,
        }
    except (AttributeError, OSError) as exc:
        return {"status": "unavailable", "error_type": type(exc).__name__}


def _bubblewrap_user_namespace_probe() -> dict[str, object]:
    try:
        probe = subprocess.run(
            (
                str(BUBBLEWRAP_EXECUTABLE),
                "--die-with-parent",
                "--new-session",
                "--unshare-all",
                "--ro-bind",
                "/",
                "/",
                "--",
                "/bin/true",
            ),
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={},
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "unavailable", "error_type": type(exc).__name__}
    return {
        "status": "passed" if probe.returncode == 0 else "failed",
        "return_code": probe.returncode,
    }


def _runtime_security_primitives() -> dict[str, object]:
    import ctypes.util

    library = ctypes.util.find_library("seccomp")
    return {
        "memfd_create": hasattr(os, "memfd_create"),
        "pidfd_open": hasattr(os, "pidfd_open"),
        "pidfd_send_signal": hasattr(signal, "pidfd_send_signal"),
        "libseccomp": {
            "status": "observed" if library else "unavailable",
            "soname": library,
        },
    }


def _process_security_status() -> dict[str, object]:
    try:
        payload = Path("/proc/self/status").read_text(
            encoding="ascii", errors="strict"
        )
    except (OSError, UnicodeError) as exc:
        return {"status": "unavailable", "error_type": type(exc).__name__}
    selected: dict[str, str] = {}
    for line in payload.splitlines():
        key, separator, value = line.partition(":")
        if separator and key in {"NoNewPrivs", "Seccomp", "Seccomp_filters"}:
            selected[key] = value.strip()
    return {"status": "observed", "fields": selected}


def _kernel_security_capability_record() -> dict[str, object]:
    uname = platform.uname()
    return {
        "schema": "phase2b-kernel-security-capability-v2",
        "kernel": {
            "system": uname.system,
            "release": uname.release,
            "machine": uname.machine,
        },
        "landlock": _landlock_abi(),
        "bubblewrap_user_namespace_probe": _bubblewrap_user_namespace_probe(),
        "sysctls": {
            "unprivileged_userns_clone": _read_capability_value(
                "/proc/sys/kernel/unprivileged_userns_clone"
            ),
            "max_user_namespaces": _read_capability_value(
                "/proc/sys/user/max_user_namespaces"
            ),
            "apparmor_restrict_unprivileged_userns": _read_capability_value(
                "/proc/sys/kernel/apparmor_restrict_unprivileged_userns"
            ),
        },
        "linux_security_modules": {
            "apparmor_enabled": _read_capability_value(
                "/sys/module/apparmor/parameters/enabled"
            ),
            "active": _read_capability_value("/sys/kernel/security/lsm"),
        },
        "seccomp": {
            "actions_available": _read_capability_value(
                "/proc/sys/kernel/seccomp/actions_avail"
            ),
            "orchestrator_process_status": _process_security_status(),
        },
        "runtime_primitives": _runtime_security_primitives(),
    }


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _isolation_enforcer_mounts() -> tuple[_RuntimeMount, ...]:
    package = Path(__file__).resolve(strict=True).parent.parent
    experiments = package / "experiments"
    execution = package / "execution"
    sources = (
        package / "core" / "domain.py",
        execution / "agents.py",
        execution / "git_snapshot.py",
        execution / "process_runner.py",
        execution / "resource_supervisor.py",
        execution / "verification.py",
        experiments / "paired_experiment.py",
        experiments / "paired_runner.py",
        experiments / "phase2b_pilot.py",
        experiments / "phase2b_runner.py",
        _CLAUDE_BWRAP_WRAPPER,
        _CODEX_SANDBOX_WRAPPER,
        package / "infrastructure" / "events.py",
        package / "infrastructure" / "logging.py",
        package / "interfaces" / "cli.py",
        package / "orchestration" / "kernel.py",
        package / "routing" / "state.py",
    )
    return tuple(
        _RuntimeMount(
            source.resolve(strict=True),
            f"enforcer:{source.relative_to(package).as_posix()}",
        )
        for source in sources
    )


def _resolve_runtime_closure(
    runtime_resolver: Callable[[str, str], _AgentRuntime],
    toolchain_home: Path,
) -> _RuntimeClosure:
    agent_runtimes = {
        "claude-code": runtime_resolver("claude-code", "claude"),
        "codex": runtime_resolver("codex", "codex"),
    }
    toolchain_mounts = _optional_toolchain_mounts(toolchain_home)
    system_mounts = _system_runtime_mounts()
    enforcer_mounts = _isolation_enforcer_mounts()
    agent_mounts = tuple(
        mount
        for base_id in ("claude-code", "codex")
        for mount in agent_runtimes[base_id].mounts
    )
    metadata_mounts = (
        *system_mounts,
        *toolchain_mounts,
        *agent_mounts,
        *enforcer_mounts,
    )
    before = _runtime_metadata_sha256(metadata_mounts)
    content_cache: dict[Path, str] = {}
    agent_hashes = {
        base_id: _target_bound_content_sha256(runtime.mounts, content_cache)
        for base_id, runtime in agent_runtimes.items()
    }
    toolchain_hash = _target_bound_content_sha256(toolchain_mounts, content_cache)
    system_hash = _target_bound_content_sha256(system_mounts, content_cache)
    enforcer_hash = _target_bound_content_sha256(enforcer_mounts, content_cache)
    kernel_security_record = _kernel_security_capability_record()
    after = _runtime_metadata_sha256(metadata_mounts)
    if after != before:
        raise OSError("runtime closure changed while its content was hashed")
    return _RuntimeClosure(
        agent_runtimes=agent_runtimes,
        toolchain_mounts=toolchain_mounts,
        observed_evidence={
            "runtime_closure_schema_version": "phase2b-runtime-closure-v2",
            "agent_runtime_sha256_by_base": agent_hashes,
            "mounted_toolchain_inventory_sha256": toolchain_hash,
            "system_runtime_inventory_sha256": system_hash,
            "isolation_enforcer_inventory_sha256": enforcer_hash,
            "runtime_closure_metadata_sha256": after,
            "kernel_security_capability_record": kernel_security_record,
            "kernel_security_capability_sha256": _canonical_sha256(
                kernel_security_record
            ),
        },
        metadata_mounts=metadata_mounts,
        attested_metadata_sha256=after,
    )


def attest_phase2b_runtime_closure(toolchain_home: Path) -> dict[str, object]:
    """Build the exact manifest isolation field without invoking either model.

    This performs host capability probes and hashes the complete mounted runtime
    closure, including the enforcement sources which implement this helper.
    The returned value contains only JSON-compatible, path-free evidence and can
    be assigned directly to ``environment.agent_execution_isolation``.
    """

    configured_home = toolchain_home.expanduser().resolve(strict=True)
    configured_bubblewrap = BUBBLEWRAP_EXECUTABLE
    if configured_bubblewrap.is_symlink():
        raise OSError("bubblewrap executable is a symlink")
    bubblewrap = configured_bubblewrap.resolve(strict=True)
    observed = bubblewrap.stat(follow_symlinks=False)
    if not stat.S_ISREG(observed.st_mode) or not os.access(bubblewrap, os.X_OK):
        raise OSError("bubblewrap executable is not a regular executable")
    runtime_closure = _resolve_runtime_closure(
        _resolve_agent_runtime,
        configured_home,
    )
    evidence: dict[str, object] = {
        "schema_version": PHASE2B_AGENT_EXECUTION_ISOLATION_SCHEMA,
        "strategy": PHASE2B_AGENT_EXECUTION_ISOLATION_STRATEGY,
        "bubblewrap_binary_sha256": _sha256(bubblewrap.read_bytes()),
        "policy_sha256": PHASE2B_AGENT_EXECUTION_ISOLATION_POLICY_SHA256,
        **dict(runtime_closure.observed_evidence),
        "resource_supervisor": _phase2b_resource_supervisor_descriptor(),
    }
    # Force a detached JSON tree here so callers cannot mutate any mapping
    # retained by the runtime closure and so unsupported values fail locally.
    return json.loads(json.dumps(evidence, sort_keys=True))


def _claude_isolation_settings() -> str:
    deny_read = [
        _NAMESPACE_HOME,
        "/proc",
        _NAMESPACE_BIN,
        _NAMESPACE_HELPER_BIN,
        f"{_NAMESPACE_RUNTIME}/node",
        f"{_NAMESPACE_RUNTIME}/codex",
    ]
    deny_write = [*deny_read, f"{_NAMESPACE_WORKSPACE}/.git"]
    settings = {
        "permissions": {
            "deny": [
                "WebFetch",
                "WebSearch",
                "Agent",
                "Read(//proc/**)",
                "Edit(//proc/**)",
                f"Read(//{_NAMESPACE_HOME.lstrip('/')}/**)",
                f"Edit(//{_NAMESPACE_HOME.lstrip('/')}/**)",
                f"Read(//{_NAMESPACE_BIN.lstrip('/')}/**)",
                f"Read(//{_NAMESPACE_HELPER_BIN.lstrip('/')}/**)",
                f"Read(//{_NAMESPACE_RUNTIME.lstrip('/')}/node/**)",
                f"Read(//{_NAMESPACE_RUNTIME.lstrip('/')}/codex/**)",
            ],
        },
        "sandbox": {
            "enabled": True,
            "bwrapPath": f"{_NAMESPACE_HELPER_BIN}/phase2b-claude-bwrap",
            "autoAllowBashIfSandboxed": True,
            "failIfUnavailable": True,
            "allowUnsandboxedCommands": False,
            "excludedCommands": [],
            "filesystem": {
                "allowRead": [
                    f"{_NAMESPACE_RUNTIME}/node/bin/node",
                    f"{_NAMESPACE_RUNTIME}/node/bin/npm",
                    f"{_NAMESPACE_RUNTIME}/node/bin/npx",
                    f"{_NAMESPACE_RUNTIME}/node/lib/node_modules/npm",
                ],
                "denyRead": deny_read,
                "denyWrite": deny_write,
            },
            "network": {
                "allowedDomains": [],
                "strictAllowlist": True,
                # This disables SRT's proc-dependent built-in seccomp helper.
                # The hash-pinned bwrap wrapper installs a stricter filter at
                # bwrap's final exec boundary instead.
                "allowAllUnixSockets": True,
            },
        },
    }
    return json.dumps(settings, sort_keys=True, separators=(",", ":"))


def _codex_isolation_config_arguments() -> tuple[str, ...]:
    shell_environment_values = {
        key: value
        for key, value in _NAMESPACE_ENVIRONMENT.items()
        if key
        not in {"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "CLAUDE_CONFIG_DIR"}
    }
    shell_environment = "{" + ", ".join(
        f"{key} = {json.dumps(value)}"
        for key, value in sorted(shell_environment_values.items())
    ) + "}"
    permission_profile = (
        'permissions={"phase2b-isolated"={'
        'description="Phase 2b per-attempt isolated tool policy",'
        'filesystem={'
        '":root"="deny",'
        '":minimal"="read",'
        '":workspace_roots"={"."="write"},'
        '"/tmp"="write",'
        '"/agent-home"="deny",'
        '"/phase2b-bin"="deny",'
        '"/phase2b-helper-bin"="read",'
        '"/phase2b-native-helper"="read",'
        '"/phase2b-runtime/node"="read",'
        '"/phase2b-runtime/node/bin"="read",'
        '"/phase2b-runtime/node/bin/node"="read",'
        '"/phase2b-runtime/node/bin/npm"="read",'
        '"/phase2b-runtime/node/bin/npx"="read",'
        '"/phase2b-runtime/node/lib/node_modules/npm"="read",'
        '"/phase2b-runtime/go"="read",'
        '"/phase2b-runtime/cargo"="read",'
        '"/phase2b-runtime/rustup"="read",'
        '"/phase2b-runtime/rust-toolchain"="read",'
        '"/phase2b-runtime/codex"="deny"},'
        'network={enabled=false}}}'
    )
    values = (
        permission_profile,
        f'default_permissions="{_CODEX_PERMISSION_PROFILE}"',
        'shell_environment_policy.inherit="none"',
        "shell_environment_policy.ignore_default_excludes=true",
        f"shell_environment_policy.set={shell_environment}",
        'approval_policy="never"',
        'web_search="disabled"',
        "tools.web_search=false",
        "features.apps=false",
        "features.multi_agent=false",
        "features.hooks=false",
        "features.memories=false",
        "features.skill_mcp_dependency_install=false",
        "feedback.enabled=false",
        "check_for_update_on_startup=false",
        'history.persistence="none"',
        'cli_auth_credentials_store="file"',
        "project_doc_max_bytes=0",
        "project_doc_fallback_filenames=[]",
        f'projects."{_NAMESPACE_WORKSPACE}".trust_level="untrusted"',
    )
    return tuple(item for value in values for item in ("-c", value))


def _evaluator_native_permission_profile() -> str:
    profile = {
        "type": "managed",
        "file_system": {
            "type": "restricted",
            "entries": [
                {
                    "path": {"type": "special", "value": {"kind": "root"}},
                    "access": "deny",
                },
                {
                    "path": {"type": "special", "value": {"kind": "minimal"}},
                    "access": "read",
                },
                {
                    "path": {"type": "path", "path": _NAMESPACE_WORKSPACE},
                    "access": "write",
                },
                {
                    "path": {
                        "type": "path",
                        "path": f"{_NAMESPACE_WORKSPACE}/.git",
                    },
                    "access": "read",
                },
                {
                    "path": {"type": "path", "path": _NAMESPACE_EVALUATOR},
                    "access": "read",
                },
                {
                    "path": {
                        "type": "path",
                        "path": _NAMESPACE_EVALUATOR_HOME,
                    },
                    "access": "write",
                },
                {
                    "path": {"type": "path", "path": _NAMESPACE_RUNTIME},
                    "access": "read",
                },
                {
                    "path": {"type": "path", "path": "/tmp"},
                    "access": "write",
                },
            ],
        },
        "network": "restricted",
    }
    return json.dumps(profile, sort_keys=True, separators=(",", ":"))


class Phase2bExecutionError(PairedExecutionError):
    """A separately authorized Phase 2b execution cannot proceed safely."""


class Phase2bPilotRunner(PairedSmokeRunner):
    """Execute only a committed, dry-run-complete, separately authorized pilot.

    ``credential_home`` is a run-private 0700 persistent cache, not the active
    interactive user home. Seed it once immediately before a run, serialize all
    run/resume access to it, reuse refreshed credentials across attempts, and
    remove it after the authorized run. ``toolchain_home`` separately locates
    attested language/tool runtimes and defaults to the current user home.
    """

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
        toolchain_home: Path | None = None,
        runtime_resolver: Callable[[str, str], _AgentRuntime] = _resolve_agent_runtime,
        runtime_closure_resolver: Callable[
            [Callable[[str, str], _AgentRuntime], Path], _RuntimeClosure
        ] = _resolve_runtime_closure,
        resource_supervisor_factory: Callable[
            [Sequence[ResourceInvocationPolicy], Mapping[str, Path]], ProcessRunner
        ] = _default_resource_supervisor_factory,
        resource_descriptor_resolver: Callable[
            [], Mapping[str, object]
        ] = _phase2b_resource_supervisor_descriptor,
        evaluator_native_helper_resolver: Callable[[], Path] = (
            _resolve_evaluator_native_helper
        ),
        _test_only_allow_enforcement_injection: bool = False,
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
        configured_credential_home = (
            credential_home.expanduser().absolute()
            if credential_home is not None
            else None
        )
        if (
            configured_credential_home is not None
            and configured_credential_home.is_symlink()
        ):
            raise Phase2bExecutionError(
                "Phase 2b credential cache home must not be a symlink."
            )
        self.credential_home = (
            configured_credential_home.resolve(strict=True)
            if configured_credential_home is not None
            else None
        )
        self.toolchain_home = (
            toolchain_home or Path.home()
        ).expanduser().resolve(strict=True)
        self.runtime_resolver = runtime_resolver
        self.runtime_closure_resolver = runtime_closure_resolver
        self.resource_supervisor_factory = resource_supervisor_factory
        self.resource_descriptor_resolver = resource_descriptor_resolver
        self.evaluator_native_helper_resolver = evaluator_native_helper_resolver
        self._enforcement_injected = any((
            process_runner_factory is not SubprocessRunner,
            version_resolver is not None,
            runtime_resolver is not _resolve_agent_runtime,
            runtime_closure_resolver is not _resolve_runtime_closure,
            resource_supervisor_factory is not _default_resource_supervisor_factory,
            resource_descriptor_resolver is not _phase2b_resource_supervisor_descriptor,
            evaluator_native_helper_resolver is not _resolve_evaluator_native_helper,
        ))
        self._test_only_allow_enforcement_injection = (
            _test_only_allow_enforcement_injection
        )
        if self._test_only_allow_enforcement_injection and (
            self.phase2b_manifest.experiment_id != "phase2b-test-v1"
        ):
            raise Phase2bExecutionError(
                "Test-only Phase 2b enforcement injection is restricted to the synthetic test experiment."
            )
        self._evaluator_native_helper: Path | None = None
        self._runtime_closure: _RuntimeClosure | None = None
        self._resource_descriptor: Mapping[str, object] | None = None

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
        if self._enforcement_injected and not self._test_only_allow_enforcement_injection:
            raise Phase2bExecutionError(
                "Phase 2b production execution requires the canonical runtime, resource, evaluator, and version enforcers."
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
        self._validate_credential_cache_boundaries(
            source_roots=source_roots,
            workspace_root=workspace_root,
            evaluator_root=evaluator_root,
            control=control,
            protected_inputs=protected_inputs,
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
        try:
            resource_descriptor = dict(self.resource_descriptor_resolver())
        except (OSError, RuntimeError, ValueError) as exc:
            raise Phase2bExecutionError(
                "Unable to attest the Phase 2b resource supervisor."
            ) from exc
        if resource_descriptor != self.phase2b_manifest.agent_execution_isolation[
            "resource_supervisor"
        ]:
            raise Phase2bExecutionError(
                "Phase 2b resource supervisor differs from the frozen manifest."
            )
        self._resource_descriptor = resource_descriptor
        try:
            runtime_closure = self.runtime_closure_resolver(
                self.runtime_resolver,
                self.toolchain_home,
            )
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            raise Phase2bExecutionError(
                f"Unable to attest the Phase 2b runtime closure: {exc}"
            ) from exc
        expected_runtime_evidence = {
            key: self.phase2b_manifest.agent_execution_isolation[key]
            for key in (
                "runtime_closure_schema_version",
                "agent_runtime_sha256_by_base",
                "mounted_toolchain_inventory_sha256",
                "system_runtime_inventory_sha256",
                "isolation_enforcer_inventory_sha256",
                "runtime_closure_metadata_sha256",
                "kernel_security_capability_record",
                "kernel_security_capability_sha256",
            )
        }
        if dict(runtime_closure.observed_evidence) != expected_runtime_evidence:
            raise Phase2bExecutionError(
                "Phase 2b mounted runtime closure differs from the frozen manifest."
            )
        try:
            evaluator_native_helper = (
                self.evaluator_native_helper_resolver().resolve(strict=True)
            )
        except OSError as exc:
            raise Phase2bExecutionError(
                f"Unable to resolve the frozen evaluator sandbox helper: {exc}"
            ) from exc
        codex_runtime = runtime_closure.agent_runtimes.get("codex")
        if codex_runtime is not None:
            pinned_helpers = {
                mount.source.resolve(strict=True)
                for mount in codex_runtime.mounts
                if mount.target
                == f"{_NAMESPACE_NATIVE_HELPER}/codex-linux-sandbox"
            }
            if pinned_helpers != {evaluator_native_helper}:
                raise Phase2bExecutionError(
                    "Evaluator sandbox helper differs from the pinned Codex runtime."
                )
        self._evaluator_native_helper = evaluator_native_helper
        self._runtime_closure = runtime_closure
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
            forbidden_host_paths=(control, control.parent),
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
                try:
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
                finally:
                    # A terminal agent/evaluator error must not bypass the
                    # immediate post-attempt closure and frozen-input check.
                    self._assert_input_snapshot(snapshot)
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

    def _validate_credential_cache_boundaries(
        self,
        *,
        source_roots: Mapping[str, Path],
        workspace_root: Path,
        evaluator_root: Path,
        control: Path,
        protected_inputs: Sequence[Path],
    ) -> None:
        resolution = self.phase2b_manifest.global_instruction_context["resolution"]
        if resolution != AUTHENTICATED_ISOLATED_AGENT_HOME_RESOLUTION:
            return
        if self.credential_home is None:
            raise Phase2bExecutionError(
                "Authenticated Phase 2b execution requires an explicit private credential cache home."
            )
        credential_cache = self.credential_home
        forbidden_roots = (
            *source_roots.values(),
            workspace_root,
            evaluator_root,
            control,
            *protected_inputs,
        )
        if any(
            credential_cache == root
            or credential_cache.is_relative_to(root)
            or root.is_relative_to(credential_cache)
            for root in forbidden_roots
        ):
            raise Phase2bExecutionError(
                "Phase 2b credential cache must be outside sources, workspaces, evaluators, and control state."
            )
        active_home = Path.home().expanduser().resolve(strict=True)
        live_provider_roots = (
            active_home / ".claude",
            active_home / ".codex",
        )
        if (
            credential_cache == active_home
            or active_home.is_relative_to(credential_cache)
            or self.toolchain_home == credential_cache
            or self.toolchain_home.is_relative_to(credential_cache)
            or any(
                credential_cache == provider
                or credential_cache.is_relative_to(provider)
                or provider.is_relative_to(credential_cache)
                for provider in live_provider_roots
            )
        ):
            raise Phase2bExecutionError(
                "Phase 2b credential cache must not overlap the active home, toolchain home, or live provider homes."
            )

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

    def _task_constraints_for_attempt(
        self,
        task_spec: PairedTaskSpec,
    ) -> tuple[str, ...]:
        return task_spec.constraints

    def _task_context_for_attempt(
        self,
        task_spec: PairedTaskSpec,
        base_context: Mapping[str, object],
    ) -> Mapping[str, object]:
        repository_id = self.phase2b_manifest.task_repository_ids[task_spec.task_id]
        repositories = {
            item.repository_id: item for item in self.phase2b_manifest.repositories
        }
        notice = repositories[repository_id].provider_transmission_notice
        return {
            **base_context,
            PROVIDER_TRANSMISSION_CONTEXT_KEY: str(notice["transmission_text"]),
        }

    def _process_runner_for_attempt(
        self,
        agent_spec: PairedAgentSpec,
        workspace: Path,
    ) -> ProcessRunner:
        resolution = self.phase2b_manifest.global_instruction_context["resolution"]
        if (
            resolution == AUTHENTICATED_ISOLATED_AGENT_HOME_RESOLUTION
            and self.credential_home is None
        ):
            raise Phase2bExecutionError(
                "Authenticated Phase 2b execution requires an explicit private credential cache home."
            )
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
        watched_roots = {"workspace": resolved_workspace, "agent-home": home}
        # Each role owns a one-slot supervisor. An agent isolation preflight can
        # fail before the delegate is invoked; role-specific instances prevent
        # that from shifting the evaluator onto the agent policy.
        delegate = self.resource_supervisor_factory(
            (PHASE2B_AGENT_RESOURCE_POLICY,),
            watched_roots,
        )
        evaluator_delegate = self.resource_supervisor_factory(
            (PHASE2B_EVALUATOR_RESOURCE_POLICY,),
            watched_roots,
        )
        if not self._test_only_allow_enforcement_injection:
            for role, candidate, expected_policy in (
                ("agent", delegate, PHASE2B_AGENT_RESOURCE_POLICY),
                ("evaluator", evaluator_delegate, PHASE2B_EVALUATOR_RESOURCE_POLICY),
            ):
                if type(candidate) is not SupervisedProcessRunner:
                    raise Phase2bExecutionError(
                        f"Phase 2b {role} runner is not the canonical resource supervisor."
                    )
                if getattr(candidate, "_policies", None) != (expected_policy,):
                    raise Phase2bExecutionError(
                        f"Phase 2b {role} resource supervisor policy drifted."
                    )
        if self._evaluator_native_helper is None:
            self._evaluator_native_helper = (
                self.evaluator_native_helper_resolver().resolve(strict=True)
            )
        closure_runtime = (
            self._runtime_closure.agent_runtimes.get(agent_spec.base_id)
            if self._runtime_closure is not None
            else None
        )

        def frozen_runtime_resolver(base_id: str, executable: str) -> _AgentRuntime:
            if base_id == agent_spec.base_id and closure_runtime is not None:
                return closure_runtime
            return self.runtime_resolver(base_id, executable)

        return _BubblewrapIsolatedAgentProcessRunner(
            delegate,
            home,
            resolved_workspace,
            agent_spec=agent_spec,
            credential_home=(
                self.credential_home
                if resolution == AUTHENTICATED_ISOLATED_AGENT_HOME_RESOLUTION
                else None
            ),
            toolchain_home=self.toolchain_home,
            evaluator_root=self.evaluator_root.expanduser().resolve(strict=True),
            evaluator_native_helper=self._evaluator_native_helper,
            expected_bubblewrap_sha256=str(
                self.phase2b_manifest.agent_execution_isolation[
                    "bubblewrap_binary_sha256"
                ]
            ),
            runtime_resolver=frozen_runtime_resolver,
            toolchain_mounts=(
                self._runtime_closure.toolchain_mounts
                if self._runtime_closure is not None
                else None
            ),
            evaluator_delegate=evaluator_delegate,
            require_resource_observation=(
                not self._test_only_allow_enforcement_injection
            ),
        )

    def _input_snapshot(self, environment: Mapping[str, object]) -> Mapping[str, object]:
        if self._runtime_closure is None:
            raise Phase2bExecutionError(
                "Phase 2b runtime closure was not attested before execution."
            )
        if self._resource_descriptor is None:
            raise Phase2bExecutionError(
                "Phase 2b resource supervisor was not attested before execution."
            )
        runtime_metadata_sha256 = self._checked_runtime_metadata_sha256()
        kernel_security_record = _kernel_security_capability_record()
        return {
            "manifest": _sha256(self.manifest_path.read_bytes()),
            "dry_run": _sha256(self.dry_run_record_path.read_bytes()),
            "authorization": _sha256(self.authorization_path.read_bytes()),
            "instruction_inventory": _sha256(self.instruction_inventory_path.read_bytes()),
            "evaluator_artifacts": dict(environment["evaluator_artifact_hashes"]),
            "repositories": dict(environment["repository_evidence"]),
            "agent_execution_isolation": dict(
                environment["agent_execution_isolation"]
            ),
            "agent_versions": {
                spec.agent_id: self.version_resolver(spec).strip()
                for spec in self.manifest.agents
            },
            "runtime_closure_metadata_sha256": runtime_metadata_sha256,
            "kernel_security_capability_record": kernel_security_record,
            "kernel_security_capability_sha256": _canonical_sha256(
                kernel_security_record
            ),
            "resource_supervisor": dict(self._resource_descriptor),
        }

    def _assert_input_snapshot(self, expected: Mapping[str, object]) -> None:
        if self._runtime_closure is None:
            raise Phase2bExecutionError(
                "Phase 2b runtime closure snapshot is unavailable."
            )
        runtime_metadata_sha256 = self._checked_runtime_metadata_sha256()
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
                "provider_transmission_notice_sha256": (
                    _validate_provider_transmission_notice_tree(source, spec)
                ),
            }
        kernel_security_record = _kernel_security_capability_record()
        observed = {
            "manifest": _sha256(self.manifest_path.read_bytes()),
            "dry_run": _sha256(self.dry_run_record_path.read_bytes()),
            "authorization": _sha256(self.authorization_path.read_bytes()),
            "instruction_inventory": _sha256(self.instruction_inventory_path.read_bytes()),
            "evaluator_artifacts": evaluator_hashes,
            "repositories": repository_evidence,
            "agent_execution_isolation": (
                validate_phase2b_agent_execution_isolation(
                    self.phase2b_manifest
                )
            ),
            "agent_versions": {
                spec.agent_id: self.version_resolver(spec).strip()
                for spec in self.manifest.agents
            },
            "runtime_closure_metadata_sha256": runtime_metadata_sha256,
            "kernel_security_capability_record": kernel_security_record,
            "kernel_security_capability_sha256": _canonical_sha256(
                kernel_security_record
            ),
            "resource_supervisor": dict(self.resource_descriptor_resolver()),
        }
        if observed != expected:
            raise Phase2bExecutionError("Phase 2b frozen input changed during execution.")

    def _checked_runtime_metadata_sha256(self) -> str:
        if self._runtime_closure is None:
            raise Phase2bExecutionError(
                "Phase 2b runtime closure snapshot is unavailable."
            )
        observed = _runtime_metadata_sha256(self._runtime_closure.metadata_mounts)
        if observed != self._runtime_closure.attested_metadata_sha256:
            raise Phase2bExecutionError(
                "Phase 2b runtime closure metadata changed after content attestation."
            )
        return observed


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
