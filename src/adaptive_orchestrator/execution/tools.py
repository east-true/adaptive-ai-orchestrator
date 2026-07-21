from __future__ import annotations

import subprocess
from enum import Enum
from pathlib import Path
from typing import Sequence


class ToolPermission(str, Enum):
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    SHELL_EXECUTE = "shell_execute"
    GIT_OPERATION = "git_operation"


class ToolRuntime:
    """Local development tools constrained to one configured workspace."""

    def __init__(self, workspace: Path, permissions: set[ToolPermission]) -> None:
        self.workspace = workspace.resolve()
        self.permissions = permissions

    def read_file(self, path: str) -> str:
        self._require(ToolPermission.FILE_READ)
        return self._path(path).read_text(encoding="utf-8")

    def write_file(self, path: str, content: str) -> None:
        self._require(ToolPermission.FILE_WRITE)
        target = self._path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def shell_execute(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self._require(ToolPermission.SHELL_EXECUTE)
        return subprocess.run(args, cwd=self.workspace, text=True, capture_output=True, check=False)

    def git(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self._require(ToolPermission.GIT_OPERATION)
        return subprocess.run(["git", *args], cwd=self.workspace, text=True, capture_output=True, check=False)

    def _path(self, value: str) -> Path:
        candidate = (self.workspace / value).resolve()
        if candidate != self.workspace and self.workspace not in candidate.parents:
            raise PermissionError("Path escapes configured workspace.")
        return candidate

    def _require(self, permission: ToolPermission) -> None:
        if permission not in self.permissions:
            raise PermissionError(f"Tool permission denied: {permission.value}")
