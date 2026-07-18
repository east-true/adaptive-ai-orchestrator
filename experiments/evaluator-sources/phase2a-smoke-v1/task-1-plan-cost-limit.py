from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

workspace = Path.cwd()
sys.path.insert(0, str(workspace / "src"))

from adaptive_orchestrator import cli


task = cli._task_from_spec({
    "description": "Constrain cost",
    "objective": "Preserve the limit",
    "cost_limit_usd": 1.25,
})
assert task.cost_limit_usd == 1.25

try:
    cli._task_from_spec({
        "description": "Invalid cost",
        "objective": "Reject it",
        "cost_limit_usd": -0.01,
    })
except ValueError:
    pass
else:
    raise AssertionError("negative cost_limit_usd must be rejected through Task validation")

with tempfile.TemporaryDirectory() as directory:
    plan_path = Path(directory) / "plan.json"
    plan_path.write_text(json.dumps([{
        "description": "Constrain cost",
        "objective": "Preserve the limit",
        "cost_limit_usd": 2.5,
    }]))
    valid, error = cli._validate_plan_file(plan_path)
    assert valid, error
    assert cli._load_plan(plan_path)[0].cost_limit_usd == 2.5

generation_task = cli._build_plan_generation_task("plan within cost", workspace, workspace / "plan.json")
assert "cost_limit_usd" in generation_task.description
