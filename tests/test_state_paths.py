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

    def test_blank_xdg_state_home_falls_back_to_the_specified_default(self) -> None:
        # The XDG specification treats an empty value as unset. Honoring "" would
        # resolve Path("") to the current directory, so protected lifecycle state
        # would land somewhere that depends on where the command was run from.
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            expected_root = Path.home() / ".local" / "state"
            for blank in ("", "   "):
                with self.subTest(value=repr(blank)):
                    with patch.dict(os.environ, {"XDG_STATE_HOME": blank}):
                        resolved = resolve_control_state_directory(workspace)
                    self.assertTrue(
                        resolved.is_relative_to(expected_root.resolve()),
                        msg=f"{resolved} is not under {expected_root}",
                    )

    def test_unset_xdg_state_home_matches_blank_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            environment = dict(os.environ)
            environment.pop("XDG_STATE_HOME", None)
            with patch.dict(os.environ, environment, clear=True):
                unset = resolve_control_state_directory(workspace)
            with patch.dict(os.environ, {"XDG_STATE_HOME": ""}):
                blank = resolve_control_state_directory(workspace)

        self.assertEqual(unset, blank)

    def test_rejects_configured_directory_inside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            with self.assertRaisesRegex(ValueError, "outside"):
                resolve_control_state_directory(workspace, workspace / ".state")


if __name__ == "__main__":
    unittest.main()
