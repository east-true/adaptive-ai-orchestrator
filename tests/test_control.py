from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.control import JobJournal, JobManager, JobStatus, build_job_command


class JobManagerTests(unittest.TestCase):
    def test_runs_queued_job_and_persists_terminal_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            manager = JobManager(workspace, popen=_fake_popen_success)
            try:
                submitted = manager.submit("Run tests", "codex")
                terminal = _wait_for_terminal(manager, submitted.job_id)
            finally:
                manager.close()
            latest = JobJournal(workspace / ".orchestrator" / "jobs.jsonl").latest()[submitted.job_id]
        self.assertEqual(terminal.status, JobStatus.COMPLETED)
        self.assertEqual(latest.status, JobStatus.COMPLETED)
        self.assertEqual(latest.output_tail, ["working", "done"])

    def test_replays_nonterminal_job_as_interrupted_instead_of_executing_redacted_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            journal = JobJournal(workspace / ".orchestrator" / "jobs.jsonl")
            path = journal.path
            path.parent.mkdir()
            path.write_text(json.dumps({
                "job_id": "job-1", "request": "task", "agent": "auto", "status": "running",
                "submitted_at": "then", "started_at": "then", "pid": 999999, "output_tail": [],
            }) + "\n", encoding="utf-8")
            manager = JobManager(workspace, journal=journal, popen=_fake_popen_success)
            try:
                job = manager.get("job-1")
            finally:
                manager.close()
        self.assertIsNotNone(job)
        self.assertEqual(job.status, JobStatus.INTERRUPTED)

    def test_rejects_empty_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = JobManager(Path(directory), popen=_fake_popen_success)
            try:
                with self.assertRaises(ValueError):
                    manager.submit(" ")
            finally:
                manager.close()

    def test_command_is_shell_free_and_workspace_bounded(self) -> None:
        command = build_job_command(Path("/workspace"), "Fix it", "auto")
        self.assertIsInstance(command, tuple)
        self.assertIn("/workspace", command)
        self.assertEqual(command.count("Fix it"), 2)


def _wait_for_terminal(manager: JobManager, job_id: str):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        job = manager.get(job_id)
        if job is not None and job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def _fake_popen_success(*args, **kwargs):
    del args, kwargs
    return _FakeProcess()


class _FakeProcess:
    pid = 12345
    stdout = iter(("working\n", "done\n"))

    def poll(self):
        return 0

    def wait(self):
        return 0


if __name__ == "__main__":
    unittest.main()
