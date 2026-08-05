from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


class ExecutionLookupError(LookupError):
    """Raised when a requested execution cannot be found unambiguously."""


@dataclass(frozen=True, slots=True)
class ExecutionBundle:
    execution_id: str
    attempts: tuple[dict, ...]

    @property
    def primary(self) -> dict:
        # Pre-telemetry escalation rows have no attempt/parent IDs at all. The
        # row carrying the nested escalation projection is their only reliable
        # primary marker.
        for attempt in self.attempts:
            if _mapping(_mapping(attempt.get("escalation")).get("record")):
                return attempt
        for attempt in self.attempts:
            if not attempt.get("parent_attempt_id"):
                return attempt
        return self.attempts[0]

    @property
    def terminal_attempt(self) -> dict:
        """Return the last escalation attempt without relying on JSONL order."""
        primary = self.primary
        nested = _mapping(_mapping(primary.get("escalation")).get("record"))
        if nested:
            # The primary row is written after the standalone child row and is
            # the object used by workflow success evaluation. Its nested copy is
            # therefore authoritative if a partial/stale child row disagrees.
            return nested

        # Older or partially normalized logs may have a separate child attempt
        # without the primary record's nested escalation projection. Follow the
        # parent chain rather than JSONL order: current workflow logs the child
        # first and the primary (with its nested child) second.
        outcome = primary
        visited: set[str] = set()
        while True:
            attempt_id = outcome.get("attempt_id")
            if not isinstance(attempt_id, str) or not attempt_id or attempt_id in visited:
                return outcome
            visited.add(attempt_id)
            children = [
                attempt
                for attempt in self.attempts
                if attempt.get("parent_attempt_id") == attempt_id
                and attempt.get("attempt_id") not in visited
            ]
            if not children:
                return outcome
            outcome = children[-1]

    @property
    def outcome(self) -> dict:
        """Return the attempt that determines the execution's effective outcome."""
        primary = self.primary
        terminal = self.terminal_attempt
        # Workflow success is an OR across the primary and escalation. Prefer a
        # successful recovery (or the final failure when neither succeeded), but
        # do not report a failed advisory escalation as if it erased a verified
        # successful primary attempt.
        if _attempt_succeeded(terminal) or not _attempt_succeeded(primary):
            return terminal
        return primary

    @property
    def attempt_count(self) -> int:
        """Count logical attempts, including a nested-only escalation record."""
        return len(_display_attempts(self))


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

    def bundles(self) -> tuple[ExecutionBundle, ...]:
        """Return canonical logical executions in first-record order."""
        return tuple(bundle for _, bundle in self.indexed_bundles())

    def indexed_bundles(self) -> tuple[tuple[int, ExecutionBundle], ...]:
        """Return each logical execution with its last one-based physical row."""
        return tuple(
            (group.record_indexes[-1] + 1, group.bundle)
            for group in _group_records(self.records())
        )

    def find(self, identifier: str) -> ExecutionBundle:
        records = self.records()
        if not records:
            raise ExecutionLookupError(f"No executions are recorded in {self.path}")

        groups = _group_records(records)

        attempt_matches = [index for index, item in enumerate(records) if item.get("attempt_id") == identifier]
        if attempt_matches:
            return _bundle_for_record(groups, attempt_matches[-1])

        for group in groups:
            if group.bundle.execution_id == identifier:
                return group.bundle

        # isdecimal, not isdigit: isdigit also accepts superscripts such as "²",
        # which int() then rejects, leaking a ValueError from a lookup whose
        # contract is ExecutionLookupError.
        if identifier.startswith("#") and identifier[1:].isdecimal():
            index = int(identifier[1:])
            if 1 <= index <= len(records):
                return _bundle_for_record(groups, index - 1)

        prefixed = self._by_unique_prefix(records, groups, identifier)
        if prefixed is not None:
            return prefixed
        raise ExecutionLookupError(f"Execution not found: {identifier}")

    _MINIMUM_PREFIX_LENGTH = 4

    def _by_unique_prefix(
        self,
        records: Sequence[dict],
        groups: tuple["_ExecutionGroup", ...],
        identifier: str,
    ) -> ExecutionBundle | None:
        """Resolve an unambiguous leading fragment of an execution or attempt id.

        Execution ids are UUIDs: the tools print all thirty-six characters and
        used to require every one of them back. Only exact matches are tried
        first, so a prefix can never shadow a real id, and an ambiguous fragment
        is reported rather than silently resolved to one of its candidates.
        """

        if len(identifier) < self._MINIMUM_PREFIX_LENGTH:
            return None

        execution_matches = [
            group for group in groups if group.bundle.execution_id.startswith(identifier)
        ]
        attempt_matches = [
            index
            for index, item in enumerate(records)
            if isinstance(item.get("attempt_id"), str) and item["attempt_id"].startswith(identifier)
        ]
        # An attempt inside an already-matched execution is the same answer.
        matched_execution_ids = {group.bundle.execution_id for group in execution_matches}
        extra_attempts = [
            index
            for index in attempt_matches
            if _bundle_for_record(groups, index).execution_id not in matched_execution_ids
        ]

        if len(execution_matches) == 1 and not extra_attempts:
            return execution_matches[0].bundle
        if not execution_matches and extra_attempts:
            resolved = {_bundle_for_record(groups, index).execution_id for index in extra_attempts}
            if len(resolved) == 1:
                return _bundle_for_record(groups, extra_attempts[-1])

        candidates = sorted(matched_execution_ids | {
            _bundle_for_record(groups, index).execution_id for index in extra_attempts
        })
        if len(candidates) > 1:
            shown = ", ".join(candidates[:5])
            suffix = ", ..." if len(candidates) > 5 else ""
            raise ExecutionLookupError(
                f"Ambiguous execution prefix {identifier!r} matches {len(candidates)} executions: {shown}{suffix}"
            )
        return None


def render_text_summary(bundle: ExecutionBundle) -> str:
    primary = bundle.primary
    outcome = bundle.outcome
    terminal = bundle.terminal_attempt
    attempts = _display_attempts(bundle)
    task = _mapping(primary.get("task"))
    verification = _mapping(outcome.get("verification"))
    lines = [
        f"Execution: {bundle.execution_id}",
        f"Task: {_one_line(task.get('description')) or '(missing description)'}",
        f"Status: {_text(outcome.get('status'), 'unknown')}",
        f"Agent: {_text(outcome.get('agent_id'), 'unknown')}",
    ]
    model = _model_text(outcome)
    if model:
        lines.append(f"Model: {model}")
    lines.extend([
        f"Verification: {_text(verification.get('status'), 'not-run')}",
        f"Attempts: {len(attempts)}",
        f"Duration: {_duration(outcome.get('duration_ms'))}",
    ])
    if not _same_attempt(outcome, terminal):
        lines.append(
            "Terminal attempt: "
            f"{_text(terminal.get('status'), 'unknown')} by "
            f"{_text(terminal.get('agent_id'), 'unknown')} "
            f"(verification: {_verification_status(terminal)})"
        )
    modified = _string_items(terminal.get("workspace_modified_files"))
    if modified:
        lines.append(f"Modified: {', '.join(modified)}")
    return "\n".join(lines)


def render_markdown_report(bundle: ExecutionBundle, include_diff: bool = False) -> str:
    primary = bundle.primary
    outcome = bundle.outcome
    terminal = bundle.terminal_attempt
    attempts = _display_attempts(bundle)
    task = _mapping(primary.get("task"))
    analysis = _mapping(primary.get("task_analysis"))
    decision = _mapping(primary.get("routing_decision"))
    modified = _string_items(terminal.get("workspace_modified_files"))
    lines = [
        f"# Execution {bundle.execution_id}",
        "",
        "## Outcome",
        "",
        f"- Status: `{_text(outcome.get('status'), 'unknown')}`",
        f"- Agent: `{_text(outcome.get('agent_id'), 'unknown')}`",
    ]
    model = _model_text(outcome)
    if model:
        lines.append(f"- Model: `{model}`")
    lines.extend([
        f"- Verification: `{_verification_status(outcome)}`",
        f"- Duration: {_duration(outcome.get('duration_ms'))}",
        f"- Attempts: {len(attempts)}",
    ])
    occurred_at = outcome.get("occurred_at")
    if isinstance(occurred_at, str) and occurred_at:
        lines.append(f"- Recorded at: `{occurred_at}`")
    if not _same_attempt(outcome, terminal):
        lines.append(
            "- Terminal escalation: "
            f"`{_text(terminal.get('status'), 'unknown')}` by "
            f"`{_text(terminal.get('agent_id'), 'unknown')}` "
            f"(verification `{_verification_status(terminal)}`)"
        )

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
    for number, attempt in enumerate(attempts, start=1):
        attempt_model = _model_text(attempt)
        model_suffix = f" ({attempt_model})" if attempt_model else ""
        lines.append(
            f"{number}. `{_text(attempt.get('agent_id'), 'unknown')}`{model_suffix} — "
            f"`{_text(attempt.get('status'), 'unknown')}`, verification "
            f"`{_verification_status(attempt)}`, {_duration(attempt.get('duration_ms'))}"
        )

    lines.extend(["", "## Changed files", ""])
    lines.extend(f"- `{item}`" for item in modified)
    if not modified:
        lines.append("No modified files were recorded.")

    result = outcome.get("result")
    error = outcome.get("error")
    if isinstance(result, str) and result.strip():
        lines.extend(["", "## Agent result", "", result.strip()])
    if isinstance(error, str) and error.strip():
        lines.extend(["", "## Error", "", "```text", error.strip(), "```"])

    if not _same_attempt(outcome, terminal):
        terminal_result = terminal.get("result")
        terminal_error = terminal.get("error")
        if isinstance(terminal_result, str) and terminal_result.strip():
            lines.extend(["", "## Terminal escalation result", "", terminal_result.strip()])
        if isinstance(terminal_error, str) and terminal_error.strip():
            lines.extend([
                "",
                "## Terminal escalation error",
                "",
                "```text",
                terminal_error.strip(),
                "```",
            ])

    diff = terminal.get("workspace_git_diff")
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
        "cost_limit_usd": task.get("cost_limit_usd"),
    }
    task_id = task.get("task_id") or bundle.primary.get("task_id")
    if isinstance(task_id, str) and task_id:
        spec["task_id"] = task_id
    return spec


def _display_attempts(bundle: ExecutionBundle) -> tuple[dict, ...]:
    """Put the primary first and include a nested-only terminal attempt once."""
    primary = bundle.primary
    terminal = bundle.terminal_attempt
    if _same_attempt(primary, terminal):
        return bundle.attempts

    middle = tuple(
        attempt
        for attempt in bundle.attempts
        if not _same_attempt(attempt, primary) and not _same_attempt(attempt, terminal)
    )
    return (primary, *middle, terminal)


def _attempt_succeeded(record: dict) -> bool:
    return (
        record.get("status") == "completed"
        and _verification_status(record) in {"passed", "skipped"}
    )


def _same_attempt(left: dict, right: dict) -> bool:
    if left is right:
        return True
    left_id = left.get("attempt_id")
    right_id = right.get("attempt_id")
    if (
        isinstance(left_id, str)
        and bool(left_id)
        and isinstance(right_id, str)
    ):
        return left_id == right_id
    # Old escalation logs had no attempt IDs, but the standalone child and
    # nested projection were byte-for-byte equivalent after JSON decoding.
    return not left_id and not right_id and left == right


@dataclass(frozen=True, slots=True)
class _ExecutionGroup:
    bundle: ExecutionBundle
    record_indexes: tuple[int, ...]


def _group_records(records: tuple[dict, ...]) -> tuple[_ExecutionGroup, ...]:
    child_to_primary: dict[int, int] = {}
    primary_indexes: set[int] = set()
    for index in range(len(records) - 1):
        child = records[index]
        primary = records[index + 1]
        nested = _mapping(_mapping(primary.get("escalation")).get("record"))
        if (
            _record_execution_id(child) is None
            and index not in primary_indexes
            and nested
            and child == nested
        ):
            child_to_primary[index] = index + 1
            primary_indexes.add(index + 1)

    grouped_indexes: dict[tuple[str, str | int], list[int]] = {}
    for index, record in enumerate(records):
        execution_id = _record_execution_id(record)
        if execution_id is not None:
            key: tuple[str, str | int] = ("execution", execution_id)
        elif index in child_to_primary:
            primary_index = child_to_primary[index]
            primary_execution_id = _record_execution_id(records[primary_index])
            key = (
                ("execution", primary_execution_id)
                if primary_execution_id is not None
                else ("legacy", primary_index)
            )
        elif index in primary_indexes:
            key = ("legacy", index)
        else:
            key = ("legacy", index)
        grouped_indexes.setdefault(key, []).append(index)

    groups = []
    for key, indexes in grouped_indexes.items():
        execution_id = str(key[1]) if key[0] == "execution" else f"legacy-{int(key[1]) + 1}"
        groups.append(_ExecutionGroup(
            ExecutionBundle(execution_id, tuple(records[index] for index in indexes)),
            tuple(indexes),
        ))
    return tuple(groups)


def _record_execution_id(record: dict) -> str | None:
    value = record.get("execution_id")
    return value if isinstance(value, str) and value else None


def _bundle_for_record(groups: tuple[_ExecutionGroup, ...], record_index: int) -> ExecutionBundle:
    for group in groups:
        if record_index in group.record_indexes:
            return group.bundle
    raise ExecutionLookupError(f"Execution record is not grouped: #{record_index + 1}")


def _verification_status(record: dict) -> str:
    return _text(_mapping(record.get("verification")).get("status"), "not-run")


def _model_text(record: dict) -> str:
    model = _mapping(record.get("metadata")).get("model")
    return model if isinstance(model, str) and model else ""


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
