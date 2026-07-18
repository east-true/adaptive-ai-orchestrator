from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

workspace = Path.cwd()
sys.path.insert(0, str(workspace / "src"))

from adaptive_orchestrator import cli
from adaptive_orchestrator.events import JsonlEventStore, LifecycleEventType


def selection_payload(agent_id: str) -> dict[str, object]:
    return {
        "selected_agent": agent_id,
        "eligible_candidates": [agent_id],
        "ineligible_reasons": {},
        "candidate_probabilities": {agent_id: 1.0},
        "selected_probability": 1.0,
    }


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    agent_workspace = root / "workspace"
    agent_workspace.mkdir()
    control = root / "control"
    store = JsonlEventStore(control / "events.jsonl")
    first = {"execution_id": "execution", "task_id": "task", "attempt_id": "attempt-final"}
    store.append(LifecycleEventType.SELECTION_MADE, payload=selection_payload("codex"), **first)
    store.append(LifecycleEventType.EXECUTION_STARTED, **first)
    store.append(LifecycleEventType.EXECUTION_TERMINAL, payload={"status": "completed"}, **first)
    store.append(LifecycleEventType.OUTCOME_FINALIZED, payload={"execution_status": "completed"}, **first)

    second = {"execution_id": "execution", "task_id": "task", "attempt_id": "attempt-started"}
    store.append(LifecycleEventType.SELECTION_MADE, payload=selection_payload("claude-code"), **second)
    store.append(LifecycleEventType.EXECUTION_STARTED, **second)

    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        exit_code = cli.main([
            "replay",
            "--workspace", str(agent_workspace),
            "--control-state-dir", str(control),
        ])
    assert exit_code == 0
    report = json.loads(stdout.getvalue())
    assert report["attempt_count"] == 2
    assert report["finalized_attempt_count"] == 1
    assert report["incomplete_attempt_count"] == 1
    assert report["attempt_status_counts"] == {"finalized": 1, "started": 1}
