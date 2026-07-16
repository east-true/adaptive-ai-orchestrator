from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path

from .domain import ExecutionRecord


class JsonlExecutionLogger:
    """Append-only local telemetry sink with best-effort secret redaction.

    This is not a data-loss-prevention system. Callers must not put credentials
    or other sensitive values in a task prompt, context, or repository diff.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: ExecutionRecord) -> None:
        payload = _redact(asdict(record))
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, default=str) + "\n")


_SENSITIVE_KEY = re.compile(r"(?:api[_-]?key|authorization|credential|password|secret|token)", re.IGNORECASE)
_INLINE_SECRET = re.compile(r"(?i)\b(api[_-]?key|authorization|credential|password|secret|token)\s*[:=]\s*[^\s,;]+")
_TOKEN_LITERAL = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")


def _redact(value: object, key: str | None = None) -> object:
    if key is not None and _SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): _redact(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _TOKEN_LITERAL.sub("[REDACTED]", _INLINE_SECRET.sub(r"\1=[REDACTED]", value))
    return value
