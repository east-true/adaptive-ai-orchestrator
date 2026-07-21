from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class WorkspaceChanges:
    modified_files: tuple[str, ...] = ()
    git_diff: str | None = None


class GitSnapshot:
    """Best-effort workspace state collector; a non-git workspace is valid."""

    def collect(self, workspace: Path) -> WorkspaceChanges:
        try:
            status = subprocess.run(["git", "status", "--porcelain"], cwd=workspace, text=True, capture_output=True, check=False)
            if status.returncode != 0:
                return WorkspaceChanges()
            files = tuple(line[3:] for line in status.stdout.splitlines() if len(line) > 3)
            diff = subprocess.run(["git", "diff", "--binary"], cwd=workspace, text=True, capture_output=True, check=False)
            return WorkspaceChanges(files, diff.stdout or None)
        except OSError:
            return WorkspaceChanges()
