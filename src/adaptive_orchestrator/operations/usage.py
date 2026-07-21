from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CodexUsage:
    plan_type: str | None
    used_percent: float | None
    window_minutes: int | None
    resets_at: int | None


def read_codex_usage(codex_home: Path | None = None) -> CodexUsage | None:
    home = codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    sessions = home / "sessions"
    try:
        files = sorted(sessions.rglob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)[:3]
    except OSError:
        return None

    # Recent files are enough for a fresh reading and keep large histories fast.
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        for line in reversed(lines):
            try:
                item = json.loads(line)
                payload = item.get("payload") or {}
                if item.get("type") != "event_msg" or payload.get("type") != "token_count":
                    continue
                rate_limits = payload.get("rate_limits")
                if not isinstance(rate_limits, dict):
                    continue
                window = rate_limits.get("primary") or rate_limits.get("secondary") or {}
                usage = CodexUsage(
                    plan_type=_string_or_none(rate_limits.get("plan_type")),
                    used_percent=_float_or_none(window.get("used_percent")),
                    window_minutes=_int_or_none(window.get("window_minutes")),
                    resets_at=_int_or_none(window.get("resets_at")),
                )
                if any(value is not None for value in (
                    usage.plan_type,
                    usage.used_percent,
                    usage.window_minutes,
                    usage.resets_at,
                )):
                    return usage
            except (AttributeError, json.JSONDecodeError, TypeError, ValueError):
                continue
    return None


def read_claude_subscription(timeout_seconds: float = 5.0) -> str | None:
    try:
        result = subprocess.run(
            ["claude", "auth", "status"],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
        if result.returncode != 0:
            return None
        subscription_type = json.loads(result.stdout).get("subscriptionType")
        return subscription_type if isinstance(subscription_type, str) else None
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired, json.JSONDecodeError, AttributeError):
        return None


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _float_or_none(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _int_or_none(value: object) -> int | None:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
