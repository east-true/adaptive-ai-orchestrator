from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.infrastructure.state_paths import resolve_control_state_directory


class ResolveControlStateDirectoryTests(unittest.TestCase):
    def test_default_is_stable_and_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            state_home = root / "state"
            with patch.dict(os.environ, {"XDG_STATE_HOME": str(state_home)}):
                first = resolve_control_state_directory(workspace)
                second = resolve_control_state_directory(workspace)
        self.assertEqual(first, second)
        self.assertTrue(first.is_relative_to(state_home))

    def test_rejects_configured_directory_inside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            with self.assertRaisesRegex(ValueError, "outside"):
                resolve_control_state_directory(workspace, workspace / ".state")


if __name__ == "__main__":
    unittest.main()
