from __future__ import annotations

import json
import os
import re
from dataclasses import asdict
from pathlib import Path

from adaptive_orchestrator.core.domain import ExecutionRecord


def restrict_to_owner(path: Path) -> None:
    """Best-effort owner-only mode for a local sink holding task content.

    The protected lifecycle log and routing projection are already written
    owner-only. These sinks carry strictly more of the task itself—full prompts,
    agent output, and the workspace diff when it is enabled—so they are held to
    the same mode instead of the process umask's usual world-readable default.
    Failure is ignored: telemetry must not abort a run that already finished, and
    some filesystems do not implement chmod.
    """

    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


class JsonlExecutionLogger:
    """Append-only local telemetry sink with best-effort secret redaction.

    This is not a data-loss-prevention system. Callers must not put credentials
    or other sensitive values in a task prompt, context, or repository diff.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: ExecutionRecord) -> None:
        payload = redact(asdict(record))
        with self.path.open("a", encoding="utf-8") as stream:
            restrict_to_owner(self.path)
            stream.write(json.dumps(payload, default=str) + "\n")


_SENSITIVE_KEY = re.compile(r"(?:api[_-]?key|authorization|credential|password|secret|token)", re.IGNORECASE)
_INLINE_SECRET = re.compile(r"(?i)\b(api[_-]?key|authorization|credential|password|secret|token)\s*[:=]\s*[^\s,;]+")
_TOKEN_LITERAL = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")
_USAGE_COUNT_KEYS = frozenset({
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "cache_read_input_tokens",
    "reasoning_output_tokens",
    "total_tokens",
    "num_tokens",
    "token_count",
})


def _is_sensitive_key(key: str, value: object) -> bool:
    normalized = key.lower().replace("-", "_")
    # Token *counts* are resource telemetry, not credentials. Keep the exception
    # narrow and numeric so a string secret hidden under a misleading key is
    # still redacted.
    if normalized in _USAGE_COUNT_KEYS and (value is None or isinstance(value, (int, float)) and not isinstance(value, bool)):
        return False
    return _SENSITIVE_KEY.search(key) is not None


def redact(value: object, key: str | None = None) -> object:
    if key is not None and _is_sensitive_key(key, value):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): redact(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _TOKEN_LITERAL.sub("[REDACTED]", _INLINE_SECRET.sub(r"\1=[REDACTED]", value))
    return value
