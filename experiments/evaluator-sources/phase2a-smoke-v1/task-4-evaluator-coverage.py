from __future__ import annotations

import sys
from pathlib import Path

workspace = Path.cwd()
sys.path.insert(0, str(workspace / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from adaptive_orchestrator.paired_experiment import (
    PairedAttemptObservation,
    analyze_paired_observations,
    assign_pairs,
    paired_manifest_from_dict,
)
from common import manifest_dict


manifest = paired_manifest_from_dict(manifest_dict())
assignments = assign_pairs(manifest)
agent_by_base = {agent.base_id: agent.agent_id for agent in manifest.agents}
claude = agent_by_base["claude-code"]
codex = agent_by_base["codex"]

first = assignments[0]
second = assignments[1]
observations = (
    PairedAttemptObservation(
        first.task_id, first.pair_id, first.execution_id,
        first.attempt_ids[claude], claude, "completed", True, 1,
    ),
    PairedAttemptObservation(
        first.task_id, first.pair_id, first.execution_id,
        first.attempt_ids[codex], codex, "completed", True, 0,
    ),
    PairedAttemptObservation(
        second.task_id, second.pair_id, second.execution_id,
        second.attempt_ids[claude], claude, "completed", True, 1,
    ),
    PairedAttemptObservation(
        second.task_id, second.pair_id, second.execution_id,
        second.attempt_ids[codex], codex, "failed", False, None,
    ),
)

report = analyze_paired_observations(manifest, observations)
overall = report["overall_quota_diagnostic_not_workload_value"]
assert overall["pair_count"] == 4
assert overall["binary_observed_pair_count"] == 1
assert overall["quality_missing_pair_count"] == 3
assert overall["evaluator_coverage"] == 0.25
assert 0.0 <= overall["evaluator_coverage"] <= 1.0
