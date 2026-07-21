from __future__ import annotations

import hashlib
import os
from pathlib import Path


def resolve_control_state_directory(workspace: Path, configured: Path | None = None) -> Path:
    resolved_workspace = workspace.resolve()
    if configured is not None:
        control_dir = configured.expanduser().resolve()
    else:
        xdg_state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")).expanduser()
        workspace_key = hashlib.sha256(str(resolved_workspace).encode("utf-8")).hexdigest()[:20]
        control_dir = (xdg_state_home / "adaptive-ai-orchestrator" / "workspaces" / workspace_key).resolve()
    if control_dir == resolved_workspace or control_dir.is_relative_to(resolved_workspace):
        raise ValueError(f"Control state directory must be outside the agent workspace: {control_dir}")
    return control_dir
