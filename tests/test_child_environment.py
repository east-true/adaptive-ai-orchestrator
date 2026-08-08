from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from adaptive_orchestrator.infrastructure.child_environment import (
    PYTHON_PATH_VARIABLE,
    ensure_child_import_path,
    package_root,
    resolved_import_path,
)


class PackageRootTest(unittest.TestCase):
    def test_root_contains_the_package(self) -> None:
        self.assertTrue((package_root() / "adaptive_orchestrator" / "__init__.py").is_file())


class ResolvedImportPathTest(unittest.TestCase):
    def test_relative_entry_becomes_absolute(self) -> None:
        value = resolved_import_path("src", root=Path("/opt/checkout"))
        first = value.split(os.pathsep)[0]
        self.assertEqual(first, os.path.abspath("src"))
        self.assertTrue(os.path.isabs(first))

    def test_empty_entry_keeps_meaning_the_working_directory(self) -> None:
        value = resolved_import_path(os.pathsep.join(("", "src")), root=Path("/opt/checkout"))
        self.assertEqual(value.split(os.pathsep)[0], os.path.abspath(""))

    def test_package_root_is_named_even_without_a_configured_value(self) -> None:
        value = resolved_import_path(None, root=Path("/opt/checkout"))
        self.assertEqual(value, os.path.abspath("/opt/checkout"))

    def test_existing_root_is_not_repeated(self) -> None:
        root = Path("/opt/checkout")
        value = resolved_import_path(str(root), root=root)
        self.assertEqual(value.split(os.pathsep).count(os.path.abspath(str(root))), 1)

    def test_order_is_preserved(self) -> None:
        value = resolved_import_path(os.pathsep.join(("/first", "/second")), root=Path("/first"))
        self.assertEqual(value.split(os.pathsep), [os.path.abspath("/first"), os.path.abspath("/second")])


class EnsureChildImportPathTest(unittest.TestCase):
    def test_environment_is_rewritten_in_place(self) -> None:
        environ: dict[str, str] = {PYTHON_PATH_VARIABLE: "src"}
        returned = ensure_child_import_path(environ)
        self.assertEqual(environ[PYTHON_PATH_VARIABLE], returned)
        self.assertTrue(all(os.path.isabs(item) for item in returned.split(os.pathsep)))

    def test_applying_twice_changes_nothing_further(self) -> None:
        environ: dict[str, str] = {PYTHON_PATH_VARIABLE: "src"}
        first = ensure_child_import_path(environ)
        self.assertEqual(ensure_child_import_path(environ), first)

    def test_child_can_import_the_package_from_another_directory(self) -> None:
        environ = dict(os.environ)
        ensure_child_import_path(environ)
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run(
                [sys.executable, "-c", "import adaptive_orchestrator; print('ok')"],
                cwd=directory,
                env=environ,
                capture_output=True,
                text=True,
                timeout=60,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "ok")


if __name__ == "__main__":
    unittest.main()
