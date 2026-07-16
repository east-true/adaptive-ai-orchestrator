import argparse
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator import cli
from adaptive_orchestrator.domain import Capability, MemoryEntryType, Priority


class BuildWorkflowTests(unittest.TestCase):
    def test_verbose_flag_installs_streaming_runner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = type(
                "Args",
                (),
                {
                    "command": "run",
                    "agent": "codex",
                    "include_git_diff": False,
                    "verify_command": [],
                    "verify_time_limit": None,
                    "no_escalation": True,
                    "escalation_risk_threshold": 3,
                    "escalation_uncertainty_threshold": 3,
                    "escalation_difficulty_threshold": 4,
                    "verbose": True,
                },
            )()

            with patch.object(cli, "SubprocessRunner") as runner_ctor:
                runner_instance = runner_ctor.return_value
                workflow = cli._build_workflow(args, Path(directory))

        runner_ctor.assert_called_once()
        self.assertIs(workflow._kernel.runner, runner_instance)
        self.assertTrue(callable(runner_ctor.call_args.args[0]))


class TaskFromSpecTests(unittest.TestCase):
    def test_required_fields_only(self) -> None:
        task = cli._task_from_spec({"description": "Do the thing", "objective": "Get it done"})
        self.assertEqual(task.description, "Do the thing")
        self.assertEqual(task.objective, "Get it done")
        self.assertEqual(task.required_capabilities, ())
        self.assertEqual(task.priority, Priority.NORMAL)

    def test_optional_fields_are_applied(self) -> None:
        task = cli._task_from_spec({
            "description": "Fix it",
            "objective": "No regressions",
            "constraints": ["Read-only"],
            "capabilities": ["debugging"],
            "priority": "high",
            "time_limit_seconds": 120,
        })
        self.assertEqual(task.constraints, ("Read-only",))
        self.assertEqual(task.required_capabilities, (Capability.DEBUGGING,))
        self.assertEqual(task.priority, Priority.HIGH)
        self.assertEqual(task.time_limit_seconds, 120)


class LoadPlanTests(unittest.TestCase):
    def test_loads_ordered_tasks_from_json_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(json.dumps([
                {"description": "Step one", "objective": "First"},
                {"description": "Step two", "objective": "Second"},
            ]))
            tasks = cli._load_plan(path)
            self.assertEqual([t.description for t in tasks], ["Step one", "Step two"])

    def test_rejects_empty_or_non_list_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(json.dumps({"description": "not a list"}))
            with self.assertRaises(ValueError):
                cli._load_plan(path)

            path.write_text(json.dumps([]))
            with self.assertRaises(ValueError):
                cli._load_plan(path)


class MemoryEntryFromArgsTests(unittest.TestCase):
    def test_builds_entry_from_record_arguments(self) -> None:
        args = type("Args", (), {
            "type": "architecture_decision",
            "title": "Use JSONL",
            "summary": "Store explicit engineering memory entries.",
            "rationale": "Append-only and queryable.",
            "alternative": ["sqlite"],
            "tag": ["memory", "architecture"],
            "related_task": "Track architecture decisions",
        })()
        entry = cli._memory_entry_from_args(args)
        self.assertEqual(entry.entry_type, MemoryEntryType.ARCHITECTURE_DECISION)
        self.assertEqual(entry.title, "Use JSONL")
        self.assertEqual(entry.alternatives_considered, ("sqlite",))
        self.assertEqual(entry.tags, ("memory", "architecture"))
        self.assertEqual(entry.related_task_description, "Track architecture decisions")


class MemorySearchFromArgsTests(unittest.TestCase):
    def test_builds_search_filters_from_arguments(self) -> None:
        args = type("Args", (), {"type": "failure_history", "tag": "regression", "keyword": "cache"})()
        self.assertEqual(
            cli._memory_search_filters_from_args(args),
            (MemoryEntryType.FAILURE_HISTORY, "regression", "cache"),
        )

    def test_builds_empty_search_filters_when_optional_arguments_are_missing(self) -> None:
        args = type("Args", (), {})()
        self.assertEqual(cli._memory_search_filters_from_args(args), (None, None, None))


class ResolveDescriptionTests(unittest.TestCase):
    def test_uses_inline_description(self) -> None:
        args = type("Args", (), {"description": "Do the thing", "description_file": None})()
        self.assertEqual(cli._resolve_description(args), "Do the thing")

    def test_uses_description_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "description.txt"
            path.write_text("Line one\n\nLine three\n", encoding="utf-8")
            args = type("Args", (), {"description": None, "description_file": path})()
            self.assertEqual(cli._resolve_description(args), "Line one\n\nLine three")

    def test_errors_when_both_description_sources_are_provided(self) -> None:
        parser = argparse.ArgumentParser(prog="prog")
        args = type("Args", (), {"description": "inline", "description_file": Path("description.txt")})()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                cli._resolve_description(args, parser)
        self.assertIn("exactly one of --description or --description-file must be provided for description", stderr.getvalue())

    def test_errors_when_no_description_source_is_provided(self) -> None:
        parser = argparse.ArgumentParser(prog="prog")
        args = type("Args", (), {"description": None, "description_file": None})()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                cli._resolve_description(args, parser)
        self.assertIn("exactly one of --description or --description-file must be provided for description", stderr.getvalue())


class ResolveObjectiveTests(unittest.TestCase):
    def test_uses_inline_objective(self) -> None:
        args = type("Args", (), {"objective": "Get it done", "objective_file": None})()
        self.assertEqual(cli._resolve_objective(args), "Get it done")

    def test_uses_objective_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "objective.txt"
            path.write_text("Line one\n\nLine three\n", encoding="utf-8")
            args = type("Args", (), {"objective": None, "objective_file": path})()
            self.assertEqual(cli._resolve_objective(args), "Line one\n\nLine three")

    def test_errors_when_both_objective_sources_are_provided(self) -> None:
        parser = argparse.ArgumentParser(prog="prog")
        args = type("Args", (), {"objective": "inline", "objective_file": Path("objective.txt")})()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                cli._resolve_objective(args, parser)
        self.assertIn("exactly one of --objective or --objective-file must be provided for objective", stderr.getvalue())

    def test_errors_when_no_objective_source_is_provided(self) -> None:
        parser = argparse.ArgumentParser(prog="prog")
        args = type("Args", (), {"objective": None, "objective_file": None})()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                cli._resolve_objective(args, parser)
        self.assertIn("exactly one of --objective or --objective-file must be provided for objective", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
