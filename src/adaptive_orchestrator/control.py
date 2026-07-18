from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import sys
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Sequence
from uuid import uuid4

from .logging import redact


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


@dataclass(slots=True)
class ControlJob:
    job_id: str
    request: str
    agent: str
    status: JobStatus = JobStatus.QUEUED
    submitted_at: str = field(default_factory=_utc_now)
    started_at: str | None = None
    finished_at: str | None = None
    return_code: int | None = None
    pid: int | None = None
    output_tail: list[str] = field(default_factory=list)


class JobJournal:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def append(self, job: ControlJob) -> None:
        payload = redact(asdict(job))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, default=str, sort_keys=True, separators=(",", ":"))
        with self._lock, self.path.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def latest(self) -> dict[str, ControlJob]:
        if not self.path.exists():
            return {}
        jobs: dict[str, ControlJob] = {}
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
                job = ControlJob(
                    job_id=item["job_id"],
                    request=item["request"],
                    agent=item.get("agent", "auto"),
                    status=JobStatus(item["status"]),
                    submitted_at=item["submitted_at"],
                    started_at=item.get("started_at"),
                    finished_at=item.get("finished_at"),
                    return_code=item.get("return_code"),
                    pid=item.get("pid"),
                    output_tail=list(item.get("output_tail") or ()),
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            jobs[job.job_id] = job
        return jobs


class JobManager:
    """Single-worker local queue with durable snapshots and bounded output tails."""

    def __init__(
        self,
        workspace: Path,
        *,
        journal: JobJournal | None = None,
        popen: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
    ) -> None:
        self.workspace = workspace.resolve()
        if not self.workspace.is_dir():
            raise ValueError(f"Workspace is not a directory: {self.workspace}")
        self.journal = journal or JobJournal(self.workspace / ".orchestrator" / "jobs.jsonl")
        self._popen = popen
        self._jobs = self.journal.latest()
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._lock = threading.RLock()
        self._current_process: subprocess.Popen[str] | None = None
        self._closed = False
        for job in self._jobs.values():
            # Journal snapshots are redacted before storage, so their request text is
            # observability data, not a trustworthy command source after restart.
            if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                job.status = JobStatus.INTERRUPTED
                job.finished_at = _utc_now()
                job.pid = None
                self.journal.append(job)
        self._worker = threading.Thread(target=self._work, name="orchestrator-job-worker", daemon=True)
        self._worker.start()

    def submit(self, request: str, agent: str = "auto") -> ControlJob:
        if not request.strip():
            raise ValueError("Request cannot be empty.")
        if not agent.strip():
            raise ValueError("Agent cannot be empty.")
        with self._lock:
            if self._closed:
                raise RuntimeError("Job manager is closed.")
            job = ControlJob(str(uuid4()), request.strip(), agent.strip())
            self._jobs[job.job_id] = job
            self.journal.append(job)
            self._queue.put(job.job_id)
            return _copy_job(job)

    def list(self) -> tuple[ControlJob, ...]:
        with self._lock:
            return tuple(_copy_job(job) for job in reversed(tuple(self._jobs.values())))

    def get(self, job_id: str) -> ControlJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return _copy_job(job) if job is not None else None

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
                return False
            job.status = JobStatus.CANCELLED
            job.finished_at = _utc_now()
            process = self._current_process if job.pid and self._current_process and self._current_process.pid == job.pid else None
            self.journal.append(job)
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        return True

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            active = next((job for job in self._jobs.values() if job.status is JobStatus.RUNNING), None)
            queued = [job for job in self._jobs.values() if job.status is JobStatus.QUEUED]
            for job in queued:
                job.status = JobStatus.CANCELLED
                job.finished_at = _utc_now()
                self.journal.append(job)
        if active is not None:
            self.cancel(active.job_id)
        self._queue.put(None)
        self._worker.join(timeout=5)

    def _work(self) -> None:
        while True:
            job_id = self._queue.get()
            if job_id is None:
                return
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None or job.status is not JobStatus.QUEUED:
                    continue
                job.status = JobStatus.RUNNING
                job.started_at = _utc_now()
                command = build_job_command(self.workspace, job.request, job.agent)
                try:
                    process = self._popen(
                        command,
                        cwd=self.workspace,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1,
                        env=os.environ.copy(),
                        start_new_session=True,
                    )
                except OSError as exc:
                    job.status = JobStatus.FAILED
                    job.finished_at = _utc_now()
                    job.output_tail.append(str(exc))
                    self.journal.append(job)
                    continue
                self._current_process = process
                job.pid = process.pid
                self.journal.append(job)

            assert process.stdout is not None
            for line in process.stdout:
                with self._lock:
                    job.output_tail.append(line.rstrip())
                    del job.output_tail[:-200]
            return_code = process.wait()
            with self._lock:
                if job.status is not JobStatus.CANCELLED:
                    job.status = JobStatus.COMPLETED if return_code == 0 else JobStatus.FAILED
                    job.finished_at = _utc_now()
                job.return_code = return_code
                job.pid = None
                self._current_process = None
                self.journal.append(job)


def build_job_command(workspace: Path, request: str, agent: str) -> tuple[str, ...]:
    return (
        sys.executable,
        "-m",
        "adaptive_orchestrator.cli",
        "run",
        "--workspace",
        str(workspace.resolve()),
        "--agent",
        agent,
        "--verbose",
        "--description",
        request,
        "--objective",
        request,
    )


def _copy_job(job: ControlJob) -> ControlJob:
    return ControlJob(
        job_id=job.job_id,
        request=job.request,
        agent=job.agent,
        status=job.status,
        submitted_at=job.submitted_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        return_code=job.return_code,
        pid=job.pid,
        output_tail=list(job.output_tail),
    )
