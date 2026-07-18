import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.events import JsonlEventStore, LifecycleEventType
from adaptive_orchestrator.paired_experiment import (
    ORDER_ASSIGNMENT_RULE,
    PAIRED_MANIFEST_SCHEMA,
    PRIMARY_METRIC,
    PairedAttemptObservation,
    PairedExperimentError,
    analyze_paired_observations,
    assign_pairs,
    load_paired_manifest,
    observations_from_routing_state,
    paired_manifest_from_dict,
    prepare_paired_workspaces,
    validate_paired_environment,
)
from adaptive_orchestrator.routing_state import LifecycleRecorder
from adaptive_orchestrator.verification import evaluator_content_version, hash_evaluator_artifacts


def git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ("git", "-C", str(repository), *arguments),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def build_manifest_fixture(root: Path) -> tuple[Path, Path, dict]:
    source = root / "source"
    source.mkdir()
    fixture = source / "fixture.txt"
    fixture.write_text("stable fixture\n")
    (source / "app.py").write_text("VALUE = 1\n")
    git(source, "init", "-q")
    git(source, "add", "fixture.txt", "app.py")
    git(source, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "base")
    commit_hash = git(source, "rev-parse", "HEAD")
    tree_hash = git(source, "rev-parse", "HEAD^{tree}")
    fixture_hash = hash_evaluator_artifacts((str(fixture),))

    evaluator_root = root / "protected-evaluators"
    evaluator_root.mkdir()
    tasks = []
    languages = ("ko", "en", "mixed", "ko")
    categories = ("implementation", "debugging", "testing", "repository-analysis")
    for index in range(4):
        artifact = evaluator_root / f"task-{index + 1}.py"
        artifact.write_text(f"# held-out evaluator {index + 1}\n")
        artifact.chmod(0o444)
        artifact_paths = (str(artifact),)
        command = ("python3", str(artifact))
        tasks.append({
            "task_id": f"task-{index + 1}",
            "task_set_version": "smoke-set-v1",
            "source": f"fixture-{index + 1}",
            "description": f"Task {index + 1}",
            "objective": "Pass the held-out evaluator",
            "constraints": ["Do not access the network"],
            "instruction_language": languages[index],
            "repository_code_language": "python",
            "repository_doc_language": languages[index],
            "task_category": categories[index],
            "required_capabilities": ["code_generation"],
            "risk": "low",
            "mutation_scope": "isolated-worktree",
            "read_only": False,
            "fixture_paths": ["fixture.txt"],
            "fixture_hash": fixture_hash,
            "estimated_resource_bucket": "small",
            "evaluator": {
                "evaluator_id": f"quality-task-{index + 1}",
                "version": evaluator_content_version(command, artifact_paths),
                "role": "quality",
                "aggregation": "binary-single-v1",
                "command": list(command),
                "artifact_paths": list(artifact_paths),
                "artifact_hash": hash_evaluator_artifacts(artifact_paths),
                "timeout_seconds": 30,
            },
        })

    raw = {
        "schema_version": PAIRED_MANIFEST_SCHEMA,
        "protocol_version": "draft-2",
        "experiment_id": "phase2a-smoke-v1",
        "task_set_version": "smoke-set-v1",
        "environment_epoch": "test-env-v1",
        "base_revision": commit_hash,
        "base_tree_hash": tree_hash,
        "random_seed": 17,
        "order_assignment_rule": ORDER_ASSIGNMENT_RULE,
        "agents": [
            {
                "agent_id": "claude-code:opus",
                "base_id": "claude-code",
                "model": "opus",
                "reasoning_tier": None,
                "cli_version": "2.1.211",
                "permission_mode": "acceptEdits",
                "time_limit_seconds": 300,
            },
            {
                "agent_id": "codex:gpt-5.5:high",
                "base_id": "codex",
                "model": "gpt-5.5",
                "reasoning_tier": "high",
                "cli_version": "0.144.5",
                "permission_mode": "workspace-write",
                "time_limit_seconds": 300,
            },
        ],
        "tasks": tasks,
        "primary_metric": PRIMARY_METRIC,
        "secondary_metrics": ["reliability", "wall-time", "evaluator-coverage"],
        "reporting_strata": ["instruction_language", "task_category"],
        "minimum_reporting_cell_size": 4,
        "non_inferiority_margin": 0.0,
        "confidence_level": 0.95,
        "interval_method": "exact-mcnemar-v1",
        "maximum_executions": 8,
        "maximum_resource_budget": {"wall_time_seconds": 2400},
        "stopping_rules": ["stop on secret or production access"],
        "pause_rules": ["pause on evaluator mismatch"],
        "exclusion_rules": ["exclude only broken fixtures before both executions"],
    }
    manifest_path = root / "paired-manifest.json"
    manifest_path.write_text(json.dumps(raw, indent=2))
    return source, manifest_path, raw


def binary_observations(manifest, outcomes):
    agents = {agent.base_id: agent.agent_id for agent in manifest.agents}
    outcome_by_task = {task.task_id: outcome for task, outcome in zip(manifest.tasks, outcomes)}
    observations = []
    for assignment in assign_pairs(manifest):
        claude_score, codex_score = outcome_by_task[assignment.task_id]
        for base_id, score in (("claude-code", claude_score), ("codex", codex_score)):
            agent_id = agents[base_id]
            observations.append(PairedAttemptObservation(
                assignment.task_id,
                assignment.pair_id,
                assignment.execution_id,
                assignment.attempt_ids[agent_id],
                agent_id,
                "completed",
                True,
                score,
            ))
    return tuple(observations)


class PairedManifestTests(unittest.TestCase):
    def test_validates_manifest_environment_and_pinned_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, manifest_path, _ = build_manifest_fixture(root)

            manifest = load_paired_manifest(manifest_path)
            environment = validate_paired_environment(manifest, manifest_path, source)

            self.assertEqual(environment["tree_hash"], manifest.base_tree_hash)
            self.assertEqual(len(environment["artifact_hashes"]), 4)
            self.assertEqual(len(environment["fixture_hashes"]), 4)

    def test_rejects_non_four_task_smoke_and_changed_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, manifest_path, raw = build_manifest_fixture(root)
            unpinned_model = json.loads(json.dumps(raw))
            unpinned_model["agents"][0]["model"] = None
            with self.assertRaisesRegex(PairedExperimentError, "model must be a non-empty string"):
                paired_manifest_from_dict(unpinned_model)

            raw["tasks"].pop()
            with self.assertRaisesRegex(PairedExperimentError, "exactly four tasks"):
                paired_manifest_from_dict(raw)

            manifest = load_paired_manifest(manifest_path)
            artifact = Path(manifest.tasks[0].evaluator.artifact_paths[0])
            artifact.chmod(0o644)
            artifact.write_text("changed\n")
            artifact.chmod(0o444)
            with self.assertRaisesRegex(PairedExperimentError, "artifact hash changed"):
                validate_paired_environment(manifest, manifest_path, source)


class PairAssignmentTests(unittest.TestCase):
    def test_seeded_assignment_is_balanced_and_byte_stable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, manifest_path, _ = build_manifest_fixture(Path(directory))
            manifest = load_paired_manifest(manifest_path)

            first = assign_pairs(manifest)
            second = assign_pairs(manifest)

            self.assertEqual(first, second)
            first_agents = [assignment.agent_order[0] for assignment in first]
            self.assertEqual(first_agents.count(manifest.agents[0].agent_id), 2)
            self.assertEqual(first_agents.count(manifest.agents[1].agent_id), 2)
            self.assertEqual(len({assignment.execution_id for assignment in first}), 4)
            self.assertEqual(len({attempt for assignment in first for attempt in assignment.attempt_ids.values()}), 8)

    def test_prepares_eight_clean_isolated_workspaces_at_identical_base(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, manifest_path, _ = build_manifest_fixture(root)
            manifest = load_paired_manifest(manifest_path)

            report = prepare_paired_workspaces(manifest, manifest_path, source, root / "workspaces")

            self.assertFalse(report["agent_execution_started"])
            self.assertTrue(report["base_hashes_identical"])
            self.assertEqual(len(report["workspaces"]), 8)
            self.assertEqual(len({item["path"] for item in report["workspaces"]}), 8)
            self.assertTrue(all(item["clean"] for item in report["workspaces"]))
            self.assertEqual({item["tree_hash"] for item in report["workspaces"]}, {manifest.base_tree_hash})
            with self.assertRaisesRegex(PairedExperimentError, "target already exists"):
                prepare_paired_workspaces(manifest, manifest_path, source, root / "workspaces")


class PairedAnalysisTests(unittest.TestCase):
    def test_synthetic_two_by_two_matches_manual_counts_without_ranking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, manifest_path, _ = build_manifest_fixture(Path(directory))
            manifest = load_paired_manifest(manifest_path)
            observations = binary_observations(manifest, ((1, 1), (1, 0), (0, 1), (0, 0)))

            report = analyze_paired_observations(manifest, observations)
            overall = report["overall_quota_diagnostic_not_workload_value"]

            self.assertEqual(overall["table_2x2"], {
                "claude_pass_codex_pass": 1,
                "claude_pass_codex_fail": 1,
                "claude_fail_codex_pass": 1,
                "claude_fail_codex_fail": 1,
            })
            self.assertEqual(overall["claude_win_tie_loss"], {"win": 1, "tie": 2, "loss": 1})
            self.assertEqual(overall["paired_risk_difference"], 0.0)
            self.assertEqual(overall["reporting_status"], "estimable")
            self.assertIsNone(overall["preferred_agent"])
            self.assertFalse(report["promotion_allowed"])
            self.assertTrue(all(
                cell["reporting_status"] == "insufficient_data"
                for stratum in report["strata"].values()
                for cell in stratum.values()
            ))

    def test_one_sided_failure_and_incomplete_pairs_are_retained_as_missing_quality(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, manifest_path, _ = build_manifest_fixture(Path(directory))
            manifest = load_paired_manifest(manifest_path)
            assignments = assign_pairs(manifest)
            agents = {agent.base_id: agent.agent_id for agent in manifest.agents}
            first = assignments[0]
            observations = (
                PairedAttemptObservation(
                    first.task_id, first.pair_id, first.execution_id,
                    first.attempt_ids[agents["claude-code"]], agents["claude-code"],
                    "completed", True, 1,
                ),
                PairedAttemptObservation(
                    first.task_id, first.pair_id, first.execution_id,
                    first.attempt_ids[agents["codex"]], agents["codex"],
                    "failed", False, None,
                ),
            )

            report = analyze_paired_observations(manifest, observations)
            overall = report["overall_quota_diagnostic_not_workload_value"]

            self.assertEqual(overall["pair_status_counts"], {
                "complete": 0,
                "one-sided failure": 1,
                "incomplete": 3,
            })
            self.assertEqual(overall["binary_observed_pair_count"], 0)
            self.assertEqual(overall["quality_missing_pair_count"], 4)
            self.assertIsNone(overall["paired_risk_difference"])

    def test_projects_paired_event_state_with_pinned_evaluator_integrity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, manifest_path, _ = build_manifest_fixture(root)
            manifest = load_paired_manifest(manifest_path)
            recorder = LifecycleRecorder(JsonlEventStore(root / "control" / "events.jsonl"))
            agents = tuple(agent.agent_id for agent in manifest.agents)
            outcomes = {task.task_id: outcome for task, outcome in zip(manifest.tasks, ((1, 1), (1, 0), (0, 1), (0, 0)))}
            task_by_id = {task.task_id: task for task in manifest.tasks}
            base_by_id = {agent.agent_id: agent.base_id for agent in manifest.agents}

            for assignment in assign_pairs(manifest):
                for agent_id in assignment.agent_order:
                    common = {
                        "execution_id": assignment.execution_id,
                        "task_id": assignment.task_id,
                        "attempt_id": assignment.attempt_ids[agent_id],
                    }
                    probabilities = {candidate: float(candidate == agent_id) for candidate in agents}
                    recorder.record(LifecycleEventType.SELECTION_MADE, payload={
                        "selected_agent": agent_id,
                        "selected_agent_base_id": base_by_id[agent_id],
                        "selection_mode": "paired_eval",
                        "cohort": "paired",
                        "pair_id": assignment.pair_id,
                        "pair_order_index": assignment.order_index,
                        "agent_order_position": assignment.agent_order.index(agent_id),
                        "context_features": {"environment_epoch": manifest.environment_epoch},
                        "eligible_candidates": list(agents),
                        "ineligible_reasons": {},
                        "candidate_probabilities": probabilities,
                        "selected_probability": 1.0,
                    }, **common)
                    recorder.record(LifecycleEventType.EXECUTION_STARTED, **common)
                    recorder.record(LifecycleEventType.EXECUTION_TERMINAL, payload={"status": "completed"}, **common)
                    task = task_by_id[assignment.task_id]
                    score = outcomes[assignment.task_id][0 if base_by_id[agent_id] == "claude-code" else 1]
                    recorder.record(LifecycleEventType.EVALUATION_COMPLETED, payload={
                        "evaluator_id": task.evaluator.evaluator_id,
                        "version": task.evaluator.version,
                        "role": "quality",
                        "status": "passed" if score else "failed",
                        "observed": True,
                        "score": score,
                        "artifact_hash_expected": task.evaluator.artifact_hash,
                        "artifact_hash_before": task.evaluator.artifact_hash,
                        "artifact_hash_after": task.evaluator.artifact_hash,
                        "artifact_integrity_verified": True,
                    }, **common)
                    recorder.record(LifecycleEventType.OUTCOME_FINALIZED, payload={"execution_status": "completed"}, **common)

            state = recorder.rebuild_state()
            first_assignment = assign_pairs(manifest)[0]
            first_execution = state.executions[first_assignment.execution_id]
            first_attempt = first_execution.attempts[first_assignment.attempt_ids[first_assignment.agent_order[0]]]
            second_attempt = first_execution.attempts[first_assignment.attempt_ids[first_assignment.agent_order[1]]]
            self.assertEqual(state.state_schema_version, 2)
            self.assertLess(first_attempt.selection_sequence, second_attempt.selection_sequence)
            observations = observations_from_routing_state(manifest, state)
            report = analyze_paired_observations(manifest, observations)

            self.assertEqual(len(observations), 8)
            self.assertEqual(report["overall_quota_diagnostic_not_workload_value"]["binary_observed_pair_count"], 4)
            self.assertEqual(report["overall_quota_diagnostic_not_workload_value"]["paired_risk_difference"], 0.0)


if __name__ == "__main__":
    unittest.main()
