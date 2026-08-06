from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from adaptive_orchestrator.interfaces import cli


class ModuleEntryPointExitCodeTests(unittest.TestCase):
    """`python3 -m adaptive_orchestrator.cli` is the documented invocation.

    The compatibility shim used to call ``main()`` and discard its return value,
    so every failure exited 0 there while the installed console script—which
    setuptools wraps in ``sys.exit(main())``—reported it correctly. Scripted use
    such as `doctor && run ...` could not detect a failure at all.
    """

    def _run(self, *arguments: str, cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            (sys.executable, "-m", cli.MODULE_ENTRY_POINT, *arguments),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=120,
            env={"PYTHONPATH": str(REPO_ROOT / "src"), "PATH": "/usr/bin:/bin"},
        )

    def test_failures_exit_non_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "bad.json").write_text('{"not": "a list"}', encoding="utf-8")
            cases = (
                ("doctor", "--workspace", "/no/such/directory"),
                ("plan", "validate", "bad.json"),
                ("show", "#1", "--workspace", "."),
                ("run-plan", "bad.json", "--workspace", "."),
            )
            for arguments in cases:
                with self.subTest(command=arguments):
                    completed = self._run(*arguments, cwd=workspace)
                    self.assertEqual(completed.returncode, 1, msg=completed.stderr)

    def test_success_still_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            for arguments in (("--version",), ("memory", "search", "--workspace", ".")):
                with self.subTest(command=arguments):
                    completed = self._run(*arguments, cwd=workspace)
                    self.assertEqual(completed.returncode, 0, msg=completed.stderr)

    def test_shims_propagate_status_like_the_real_entry_points(self) -> None:
        # interfaces/cli.py and interfaces/tui.py already did this; the root
        # shims are what the documentation tells people to run.
        for module in ("cli.py", "tui.py"):
            with self.subTest(module=module):
                source = (REPO_ROOT / "src" / "adaptive_orchestrator" / module).read_text(encoding="utf-8")
                self.assertIn("raise SystemExit(main())", source)


if __name__ == "__main__":
    unittest.main()
