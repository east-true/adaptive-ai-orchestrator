from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class ExecutionLookupError(LookupError):
    """Raised when a requested execution cannot be found unambiguously."""


@dataclass(frozen=True, slots=True)
class ExecutionBundle:
    execution_id: str
    attempts: tuple[dict, ...]

    @property
    def primary(self) -> dict:
        for attempt in self.attempts:
            if not attempt.get("parent_attempt_id"):
                return attempt
        return self.attempts[0]


class ExecutionReportStore:
    """Read-only lookup and rendering over append-only terminal execution records."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def records(self) -> tuple[dict, ...]:
        if not self.path.exists():
            return ()
        records: list[dict] = []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            raise ExecutionLookupError(f"Cannot read execution history {self.path}: {exc}") from exc
        for line in lines:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                records.append(item)
        return tuple(records)

    def find(self, identifier: str) -> ExecutionBundle:
        records = self.records()
        if not records:
            raise ExecutionLookupError(f"No executions are recorded in {self.path}")

        attempt_matches = [item for item in records if item.get("attempt_id") == identifier]
        if attempt_matches:
            execution_id = _identifier(attempt_matches[-1].get("execution_id"), identifier)
            grouped = tuple(item for item in records if item.get("execution_id") == execution_id)
            return ExecutionBundle(execution_id, grouped or (attempt_matches[-1],))

        execution_matches = [item for item in records if item.get("execution_id") == identifier]
        if execution_matches:
            return ExecutionBundle(identifier, tuple(execution_matches))

        if identifier.startswith("#") and identifier[1:].isdigit():
            index = int(identifier[1:])
            if 1 <= index <= len(records):
                record = records[index - 1]
                execution_id = _identifier(record.get("execution_id"), f"legacy-{index}")
                grouped = tuple(item for item in records if item.get("execution_id") == execution_id)
                return ExecutionBundle(execution_id, grouped or (record,))
        raise ExecutionLookupError(f"Execution not found: {identifier}")


def render_text_summary(bundle: ExecutionBundle) -> str:
    primary = bundle.primary
    task = _mapping(primary.get("task"))
    verification = _mapping(primary.get("verification"))
    lines = [
        f"Execution: {bundle.execution_id}",
        f"Task: {_one_line(task.get('description')) or '(missing description)'}",
        f"Status: {_text(primary.get('status'), 'unknown')}",
        f"Agent: {_text(primary.get('agent_id'), 'unknown')}",
        f"Verification: {_text(verification.get('status'), 'not-run')}",
        f"Attempts: {len(bundle.attempts)}",
        f"Duration: {_duration(primary.get('duration_ms'))}",
    ]
    modified = _string_items(primary.get("workspace_modified_files"))
    if modified:
        lines.append(f"Modified: {', '.join(modified)}")
    return "\n".join(lines)


def render_markdown_report(bundle: ExecutionBundle, include_diff: bool = False) -> str:
    primary = bundle.primary
    task = _mapping(primary.get("task"))
    analysis = _mapping(primary.get("task_analysis"))
    decision = _mapping(primary.get("routing_decision"))
    modified = _string_items(primary.get("workspace_modified_files"))
    lines = [
        f"# Execution {bundle.execution_id}",
        "",
        "## Outcome",
        "",
        f"- Status: `{_text(primary.get('status'), 'unknown')}`",
        f"- Agent: `{_text(primary.get('agent_id'), 'unknown')}`",
        f"- Verification: `{_verification_status(primary)}`",
        f"- Duration: {_duration(primary.get('duration_ms'))}",
        f"- Attempts: {len(bundle.attempts)}",
    ]
    occurred_at = primary.get("occurred_at")
    if isinstance(occurred_at, str) and occurred_at:
        lines.append(f"- Recorded at: `{occurred_at}`")

    lines.extend(["", "## Task", "", _text(task.get("description"), "(missing description)")])
    objective = task.get("objective")
    if isinstance(objective, str) and objective.strip():
        lines.extend(["", f"Objective: {objective.strip()}"])

    lines.extend(["", "## Routing", ""])
    lines.append(f"Selected agent: `{_text(decision.get('selected_agent') or primary.get('agent_id'), 'unknown')}`")
    for label, value in (("Difficulty", analysis.get("difficulty")), ("Risk", analysis.get("risk")), ("Uncertainty", analysis.get("uncertainty"))):
        if value is not None:
            lines.append(f"- {label}: `{value}`")
    reasons = _string_items(primary.get("escalation_reasons"))
    if reasons:
        lines.append(f"- Escalation reasons: {', '.join(reasons)}")

    lines.extend(["", "## Attempts", ""])
    for number, attempt in enumerate(bundle.attempts, start=1):
        lines.append(
            f"{number}. `{_text(attempt.get('agent_id'), 'unknown')}` — "
            f"`{_text(attempt.get('status'), 'unknown')}`, verification "
            f"`{_verification_status(attempt)}`, {_duration(attempt.get('duration_ms'))}"
        )

    lines.extend(["", "## Changed files", ""])
    lines.extend(f"- `{item}`" for item in modified)
    if not modified:
        lines.append("No modified files were recorded.")

    result = primary.get("result")
    error = primary.get("error")
    if isinstance(result, str) and result.strip():
        lines.extend(["", "## Agent result", "", result.strip()])
    if isinstance(error, str) and error.strip():
        lines.extend(["", "## Error", "", "```text", error.strip(), "```"])

    diff = primary.get("workspace_git_diff")
    if include_diff and isinstance(diff, str) and diff.strip():
        lines.extend(["", "## Recorded workspace diff", "", "```diff", diff.rstrip(), "```"])
    return "\n".join(lines).rstrip() + "\n"


def task_spec_for_retry(bundle: ExecutionBundle) -> dict:
    task = _mapping(bundle.primary.get("task"))
    description = task.get("description")
    objective = task.get("objective")
    if not isinstance(description, str) or not description.strip() or not isinstance(objective, str) or not objective.strip():
        raise ExecutionLookupError(f"Execution {bundle.execution_id} does not contain a retryable task")
    spec = {
        "description": description,
        "objective": objective,
        "constraints": list(_string_items(task.get("constraints"))),
        "capabilities": list(_string_items(task.get("required_capabilities"))),
        "priority": _text(task.get("priority"), "normal"),
        "time_limit_seconds": task.get("time_limit_seconds"),
    }
    task_id = task.get("task_id") or bundle.primary.get("task_id")
    if isinstance(task_id, str) and task_id:
        spec["task_id"] = task_id
    return spec


def _verification_status(record: dict) -> str:
    return _text(_mapping(record.get("verification")).get("status"), "not-run")


def _duration(value: object) -> str:
    try:
        milliseconds = float(value)
    except (TypeError, ValueError):
        return "unknown"
    return f"{milliseconds / 1000:.1f}s"


def _mapping(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _text(value: object, default: str) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else default


def _one_line(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _string_items(value: object) -> tuple[str, ...]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, dict)):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _identifier(value: object, fallback: str) -> str:
    return value if isinstance(value, str) and value else fallback
