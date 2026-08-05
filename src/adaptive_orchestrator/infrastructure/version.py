from __future__ import annotations

from importlib import metadata
from pathlib import Path

DISTRIBUTION_NAME = "adaptive-ai-orchestrator"


def source_tree_version() -> str | None:
    """Return this checkout's project version when the module lives in a source tree."""
    pyproject = Path(__file__).parents[3] / "pyproject.toml"
    try:
        lines = pyproject.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return None

    project_values: dict[str, str] = {}
    in_project = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_project = stripped == "[project]"
            continue
        key, separator, raw_value = stripped.partition("=")
        value = raw_value.strip()
        if (
            in_project
            and separator
            and len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            project_values[key.strip()] = value[1:-1]

    if project_values.get("name") != DISTRIBUTION_NAME:
        return None
    return project_values.get("version")


def package_version() -> str:
    """Return the active source release, then installed distribution metadata."""
    # Prefer a verified checkout over possibly stale installed metadata when
    # the documented ``PYTHONPATH=src`` development entry point is in use.
    version = source_tree_version()
    if version:
        return version
    try:
        return metadata.version(DISTRIBUTION_NAME)
    except metadata.PackageNotFoundError:
        return "dev"
