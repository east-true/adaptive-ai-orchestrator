from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from adaptive_orchestrator.infrastructure.configuration import ProjectConfigError, config_path, load_project_config

# A login check only needs to say whether the CLI is usable. Account identifiers
# are not part of that answer, and `doctor` output is routinely pasted into bug
# reports and screenshots, so only these keys are echoed from a JSON status.
_STATUS_SUMMARY_KEYS = ("loggedIn", "subscriptionType", "authMethod", "apiProvider", "plan", "planType")


@dataclass(frozen=True, slots=True)
class DiagnosticCheck:
    name: str
    status: str
    detail: str


def diagnose_project(workspace: Path, timeout_seconds: float = 5.0) -> tuple[DiagnosticCheck, ...]:
    workspace = workspace.resolve()
    checks: list[DiagnosticCheck] = []
    if not workspace.exists() or not workspace.is_dir():
        return (DiagnosticCheck("workspace", "FAIL", f"not a directory: {workspace}"),)
    checks.append(DiagnosticCheck("workspace", "PASS", str(workspace)))

    path = config_path(workspace)
    try:
        config = load_project_config(workspace)
    except ProjectConfigError as exc:
        checks.append(DiagnosticCheck("config", "FAIL", str(exc)))
        config = None
    else:
        status = "PASS" if path.exists() else "WARN"
        detail = str(path) if path.exists() else f"not initialized; run init --workspace {workspace}"
        checks.append(DiagnosticCheck("config", status, detail))

    agent_statuses: dict[str, bool] = {}
    for agent_id, command in (("claude-code", ("claude", "auth", "status")), ("codex", ("codex", "login", "status"))):
        executable = shutil.which(command[0])
        if executable is None:
            checks.append(DiagnosticCheck(agent_id, "WARN", f"executable not found: {command[0]}"))
            agent_statuses[agent_id] = False
            continue
        ok, detail = _run_status_command((executable, *command[1:]), timeout_seconds)
        checks.append(DiagnosticCheck(agent_id, "PASS" if ok else "WARN", detail))
        agent_statuses[agent_id] = ok

    if config is not None:
        base_agent = config.agent.split(":", 1)[0]
        if base_agent == "auto":
            usable = any(agent_statuses.values())
            checks.append(DiagnosticCheck("selected-agent", "PASS" if usable else "FAIL", "auto" if usable else "no authenticated agent available"))
        elif base_agent in agent_statuses:
            usable = agent_statuses[base_agent]
            checks.append(DiagnosticCheck("selected-agent", "PASS" if usable else "FAIL", config.agent))
        else:
            checks.append(DiagnosticCheck("selected-agent", "FAIL", f"unknown configured agent: {config.agent}"))

    python_ok = sys.version_info >= (3, 10)
    checks.append(DiagnosticCheck("python", "PASS" if python_ok else "FAIL", sys.version.split()[0]))
    return tuple(checks)


def diagnostics_succeeded(checks: Sequence[DiagnosticCheck]) -> bool:
    return all(check.status != "FAIL" for check in checks)


def _run_status_command(command: Sequence[str], timeout_seconds: float) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    output = (result.stdout or result.stderr).strip()
    detail = _summarize_status_output(output) or f"exit code {result.returncode}"
    return result.returncode == 0, detail


def _summarize_status_output(output: str) -> str:
    """Condense a status command's output, dropping account identifiers.

    Claude Code answers `auth status` with a JSON object that includes the
    account email, organization ID, and organization name. Echoing it raw both
    reads badly—one status line becomes a wall of JSON cut off mid-object—and
    puts identifying details into output people paste into issues. Only the keys
    that describe whether the CLI is usable are kept; any other shape falls back
    to the previous flattened, truncated text.
    """

    if not output:
        return ""
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return output.replace("\n", " ")[:240]
    if not isinstance(payload, dict):
        return output.replace("\n", " ")[:240]

    clauses = [
        f"{key}={payload[key]}"
        for key in _STATUS_SUMMARY_KEYS
        if key in payload and not isinstance(payload[key], (dict, list))
    ]
    if not clauses:
        # A JSON status with nothing recognizable is still a successful call;
        # say so without echoing fields that were deliberately not allowlisted.
        return "status reported (no recognized fields)"
    return ", ".join(clauses)
