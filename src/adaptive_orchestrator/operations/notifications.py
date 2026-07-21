from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import TextIO


@dataclass(frozen=True, slots=True)
class NotificationResult:
    channel: str
    delivered: bool
    detail: str


def notify_execution(
    record: dict,
    *,
    terminal_bell: bool = False,
    desktop: bool = False,
    stream: TextIO | None = None,
    timeout_seconds: float = 3.0,
) -> tuple[NotificationResult, ...]:
    """Deliver opt-in local notifications without including task or result content."""
    status = record.get("status") if isinstance(record.get("status"), str) else "unknown"
    verification = record.get("verification")
    verify_status = verification.get("status") if isinstance(verification, dict) else "not-run"
    execution_id = record.get("execution_id") if isinstance(record.get("execution_id"), str) else "unknown"
    agent = record.get("agent_id") if isinstance(record.get("agent_id"), str) else "unknown"
    successful = status == "completed" and verify_status not in {"failed", "timed_out"}
    title = "Orchestrator run completed" if successful else "Orchestrator run needs attention"
    body = f"status={status}; verification={verify_status}; agent={agent}; execution={execution_id}"

    results: list[NotificationResult] = []
    if terminal_bell:
        target = stream or sys.stderr
        try:
            target.write("\a")
            target.flush()
        except OSError as exc:
            results.append(NotificationResult("terminal-bell", False, str(exc)))
        else:
            results.append(NotificationResult("terminal-bell", True, "delivered"))

    if desktop:
        executable = shutil.which("notify-send")
        if executable is None:
            results.append(NotificationResult("desktop", False, "notify-send executable not found"))
        else:
            urgency = "normal" if successful else "critical"
            try:
                completed = subprocess.run(
                    (executable, "--app-name", "Adaptive Orchestrator", "--urgency", urgency, title, body),
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=timeout_seconds,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                results.append(NotificationResult("desktop", False, str(exc)))
            else:
                detail = (completed.stderr or completed.stdout).strip() or f"exit code {completed.returncode}"
                results.append(NotificationResult("desktop", completed.returncode == 0, detail))
    return tuple(results)
