from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


CONFIG_VERSION = 1
CONFIG_RELATIVE_PATH = Path(".orchestrator") / "config.json"


class ProjectConfigError(ValueError):
    """Raised when a project configuration cannot be parsed or validated."""


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    agent: str = "auto"
    claude_model: str | None = None
    codex_model: str | None = None
    codex_reasoning_effort: str | None = None
    time_limit_seconds: float | None = None
    verbose: bool = False
    include_git_diff: bool = False
    verify_commands: tuple[str, ...] = ()
    verify_time_limit_seconds: float | None = None
    escalation_enabled: bool = True
    escalation_risk_threshold: int = 3
    escalation_uncertainty_threshold: int = 3
    escalation_difficulty_threshold: int = 4


def config_path(workspace: Path) -> Path:
    return workspace.resolve() / CONFIG_RELATIVE_PATH


def load_project_config(workspace: Path) -> ProjectConfig:
    path = config_path(workspace)
    if not path.exists():
        return ProjectConfig()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProjectConfigError(f"Cannot read project config {path}: {exc}") from exc
    return project_config_from_mapping(payload, path)


def project_config_from_mapping(payload: object, path: Path | None = None) -> ProjectConfig:
    label = str(path) if path is not None else "project config"
    root = _mapping(payload, label)
    _reject_unknown(root, {"version", "agent", "models", "execution", "verification", "escalation"}, label)
    version = root.get("version")
    if version != CONFIG_VERSION:
        raise ProjectConfigError(f"{label}: version must be {CONFIG_VERSION}")

    models = _section(root, "models", label)
    execution = _section(root, "execution", label)
    verification = _section(root, "verification", label)
    escalation = _section(root, "escalation", label)
    _reject_unknown(models, {"claude", "codex", "codex_reasoning_effort"}, f"{label}.models")
    _reject_unknown(execution, {"time_limit_seconds", "verbose", "include_git_diff"}, f"{label}.execution")
    _reject_unknown(verification, {"commands", "time_limit_seconds"}, f"{label}.verification")
    _reject_unknown(escalation, {"enabled", "risk_threshold", "uncertainty_threshold", "difficulty_threshold"}, f"{label}.escalation")

    agent = _string(root.get("agent", "auto"), f"{label}.agent")
    if agent != "auto" and agent.split(":", 1)[0] not in {"claude-code", "codex"}:
        raise ProjectConfigError(f"{label}.agent: expected auto, claude-code, codex, or a configured model variant")

    config = ProjectConfig(
        agent=agent,
        claude_model=_optional_string(models.get("claude"), f"{label}.models.claude"),
        codex_model=_optional_string(models.get("codex"), f"{label}.models.codex"),
        codex_reasoning_effort=_optional_string(
            models.get("codex_reasoning_effort"), f"{label}.models.codex_reasoning_effort"
        ),
        time_limit_seconds=_optional_positive_number(
            execution.get("time_limit_seconds"), f"{label}.execution.time_limit_seconds"
        ),
        verbose=_boolean(execution.get("verbose", False), f"{label}.execution.verbose"),
        include_git_diff=_boolean(
            execution.get("include_git_diff", False), f"{label}.execution.include_git_diff"
        ),
        verify_commands=_string_sequence(verification.get("commands", []), f"{label}.verification.commands"),
        verify_time_limit_seconds=_optional_positive_number(
            verification.get("time_limit_seconds"), f"{label}.verification.time_limit_seconds"
        ),
        escalation_enabled=_boolean(escalation.get("enabled", True), f"{label}.escalation.enabled"),
        escalation_risk_threshold=_integer_in_range(
            escalation.get("risk_threshold", 3), 0, 5, f"{label}.escalation.risk_threshold"
        ),
        escalation_uncertainty_threshold=_integer_in_range(
            escalation.get("uncertainty_threshold", 3), 0, 5, f"{label}.escalation.uncertainty_threshold"
        ),
        escalation_difficulty_threshold=_integer_in_range(
            escalation.get("difficulty_threshold", 4), 1, 5, f"{label}.escalation.difficulty_threshold"
        ),
    )
    available_ids = {
        "auto",
        _variant_id("claude-code", config.claude_model),
        _variant_id("codex", config.codex_model, config.codex_reasoning_effort),
    }
    if config.agent not in available_ids:
        raise ProjectConfigError(
            f"{label}.agent: {config.agent!r} does not match the configured model variants; "
            f"expected one of {', '.join(sorted(available_ids))}"
        )
    return config


def initialize_project_config(workspace: Path, force: bool = False) -> tuple[Path, tuple[str, ...]]:
    workspace = workspace.resolve()
    if not workspace.exists() or not workspace.is_dir():
        raise ProjectConfigError(f"Workspace is not a directory: {workspace}")
    path = config_path(workspace)
    if path.exists() and not force:
        raise ProjectConfigError(f"Project config already exists: {path} (use --force to replace it)")

    commands = detect_verification_commands(workspace)
    payload = default_config_payload(commands)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise ProjectConfigError(f"Cannot write project config {path}: {exc}") from exc
    return path, commands


def default_config_payload(verify_commands: Sequence[str] = ()) -> dict[str, Any]:
    return {
        "version": CONFIG_VERSION,
        "agent": "auto",
        "models": {
            "claude": None,
            "codex": None,
            "codex_reasoning_effort": None,
        },
        "execution": {
            "time_limit_seconds": None,
            "verbose": False,
            "include_git_diff": False,
        },
        "verification": {
            "commands": list(verify_commands),
            "time_limit_seconds": None,
        },
        "escalation": {
            "enabled": True,
            "risk_threshold": 3,
            "uncertainty_threshold": 3,
            "difficulty_threshold": 4,
        },
    }


def detect_verification_commands(workspace: Path) -> tuple[str, ...]:
    commands: list[str] = []
    package_json = workspace / "package.json"
    if package_json.is_file():
        try:
            payload = json.loads(package_json.read_text(encoding="utf-8"))
            scripts = payload.get("scripts", {}) if isinstance(payload, dict) else {}
            if isinstance(scripts, dict) and isinstance(scripts.get("test"), str):
                commands.append("npm test")
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
    if (workspace / "Cargo.toml").is_file():
        commands.append("cargo test")
    if (workspace / "go.mod").is_file():
        commands.append("go test ./...")
    if (workspace / "pytest.ini").is_file() or (workspace / "conftest.py").is_file():
        commands.append("python3 -m pytest")
    elif (workspace / "tests").is_dir() and any((workspace / "tests").glob("test*.py")):
        commands.append("python3 -m unittest discover -s tests -v")
    return tuple(commands)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ProjectConfigError(f"{label}: expected a JSON object")
    return value


def _section(root: Mapping[str, object], name: str, label: str) -> Mapping[str, object]:
    return _mapping(root.get(name, {}), f"{label}.{name}")


def _reject_unknown(mapping: Mapping[str, object], allowed: set[str], label: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise ProjectConfigError(f"{label}: unknown field(s): {', '.join(unknown)}")


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProjectConfigError(f"{label}: expected a non-empty string")
    return value


def _optional_string(value: object, label: str) -> str | None:
    return None if value is None else _string(value, label)


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ProjectConfigError(f"{label}: expected true or false")
    return value


def _optional_positive_number(value: object, label: str) -> float | None:
    if value is None:
        return None
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ProjectConfigError(f"{label}: expected a positive number or null")
    return float(value)


def _integer_in_range(value: object, minimum: int, maximum: int, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise ProjectConfigError(f"{label}: expected an integer from {minimum} to {maximum}")
    return value


def _string_sequence(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ProjectConfigError(f"{label}: expected an array of non-empty strings")
    return tuple(value)


def _variant_id(base_id: str, *axes: str | None) -> str:
    values = tuple(value for value in axes if value is not None)
    return ":".join((base_id, *values)) if values else base_id
