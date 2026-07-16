import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.tools import ToolPermission, ToolRuntime


class ToolRuntimeTests(unittest.TestCase):
    def test_file_access_is_workspace_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = ToolRuntime(Path(directory), {ToolPermission.FILE_WRITE, ToolPermission.FILE_READ})
            runtime.write_file("notes/plan.txt", "safe")
            self.assertEqual(runtime.read_file("notes/plan.txt"), "safe")
            with self.assertRaises(PermissionError):
                runtime.read_file("../outside.txt")

    def test_permission_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = ToolRuntime(Path(directory), set())
            with self.assertRaises(PermissionError):
                runtime.read_file("anything.txt")


if __name__ == "__main__":
    unittest.main()
