from __future__ import annotations

from adaptive_orchestrator.paired_experiment import ORDER_ASSIGNMENT_RULE, PAIRED_MANIFEST_SCHEMA, PRIMARY_METRIC


def manifest_dict() -> dict[str, object]:
    tasks = []
    languages = ("ko", "en", "mixed", "ko")
    categories = ("implementation", "replay", "planning", "analysis")
    for index in range(4):
        tasks.append({
            "task_id": f"task-{index + 1}",
            "task_set_version": "synthetic-v1",
            "source": "hidden-evaluator-fixture",
            "description": f"Synthetic task {index + 1}",
            "objective": "Exercise paired tooling",
            "constraints": [],
            "instruction_language": languages[index],
            "repository_code_language": "python",
            "repository_doc_language": languages[index],
            "task_category": categories[index],
            "required_capabilities": ["code_generation"],
            "risk": "low",
            "mutation_scope": "isolated-checkout",
            "read_only": False,
            "fixture_paths": ["README.md"],
            "fixture_hash": "0" * 64,
            "estimated_resource_bucket": "small",
            "evaluator": {
                "evaluator_id": f"synthetic-quality-{index + 1}",
                "version": "synthetic-v1",
                "role": "quality",
                "aggregation": "binary-single-v1",
                "command": ["python3", f"synthetic-{index + 1}.py"],
                "artifact_paths": [f"synthetic-{index + 1}.py"],
                "artifact_hash": "1" * 64,
                "timeout_seconds": 30,
            },
        })
    return {
        "schema_version": PAIRED_MANIFEST_SCHEMA,
        "protocol_version": "draft-2",
        "experiment_id": "synthetic-smoke-v1",
        "task_set_version": "synthetic-v1",
        "environment_epoch": "synthetic-env-v1",
        "base_revision": "0" * 40,
        "base_tree_hash": "0" * 40,
        "random_seed": 17,
        "order_assignment_rule": ORDER_ASSIGNMENT_RULE,
        "agents": [
            {
                "agent_id": "claude-code:test",
                "base_id": "claude-code",
                "model": "test",
                "reasoning_tier": None,
                "cli_version": "test",
                "permission_mode": "acceptEdits",
                "time_limit_seconds": 30,
            },
            {
                "agent_id": "codex:test:none",
                "base_id": "codex",
                "model": "test",
                "reasoning_tier": "none",
                "cli_version": "test",
                "permission_mode": "workspace-write",
                "time_limit_seconds": 30,
            },
        ],
        "tasks": tasks,
        "primary_metric": PRIMARY_METRIC,
        "secondary_metrics": ["evaluator-coverage"],
        "reporting_strata": ["instruction_language", "task_category"],
        "minimum_reporting_cell_size": 4,
        "non_inferiority_margin": 0.0,
        "confidence_level": 0.95,
        "interval_method": "exact-mcnemar-v1",
        "maximum_executions": 8,
        "maximum_resource_budget": {"wall_time_seconds": 240},
        "stopping_rules": ["stop on integrity failure"],
        "pause_rules": ["pause on missing evaluator"],
        "exclusion_rules": ["exclude only broken fixtures"],
    }
