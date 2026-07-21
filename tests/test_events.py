import json
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.execution.agents import CodexAgent
from adaptive_orchestrator.core.domain import ExecutionStatus, Task
from adaptive_orchestrator.infrastructure.events import JsonlEventStore, LifecycleEvent, LifecycleEventType
from adaptive_orchestrator.orchestration.kernel import OrchestratorKernel
from adaptive_orchestrator.infrastructure.logging import JsonlExecutionLogger
from adaptive_orchestrator.execution.process_runner import ProcessResult
from adaptive_orchestrator.operations.replay import (
    replay_digest,
    replay_event_log,
    replay_events,
    summarize_attempts,
    validate_legacy_execution_log,
)
from adaptive_orchestrator.routing.state import EventProjector, LifecycleRecorder, ReplayError


def selection_payload(agent_id: str = "codex") -> dict[str, object]:
    return {
        "selected_agent": agent_id,
        "eligible_candidates": [agent_id],
        "ineligible_reasons": {},
        "candidate_probabilities": {agent_id: 1.0},
        "selected_probability": 1.0,
    }


class EventStoreTests(unittest.TestCase):
    def test_selection_event_rejects_invalid_propensity_contract(self) -> None:
        with self.assertRaisesRegex(ValueError, "sum to one"):
            LifecycleEvent(
                LifecycleEventType.SELECTION_MADE,
                "execution",
                1,
                "task",
                "attempt",
                payload={
                    "selected_agent": "codex",
                    "eligible_candidates": ["codex", "claude-code"],
                    "ineligible_reasons": {},
                    "candidate_probabilities": {"codex": 0.6, "claude-code": 0.3},
                    "selected_probability": 0.6,
                },
            )

        with self.assertRaisesRegex(ValueError, "ineligible candidates"):
            LifecycleEvent(
                LifecycleEventType.SELECTION_MADE,
                "execution",
                1,
                "task",
                "attempt",
                payload={
                    "selected_agent": "codex",
                    "eligible_candidates": ["codex"],
                    "ineligible_reasons": {"claude-code": ["manual exclusion"]},
                    "candidate_probabilities": {"codex": 0.8, "claude-code": 0.2},
                    "selected_probability": 0.8,
                },
            )

    def test_duplicate_event_id_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonlEventStore(Path(directory) / "events.jsonl")
            first = store.append(
                LifecycleEventType.SELECTION_MADE,
                execution_id="execution",
                task_id="task",
                attempt_id="attempt",
                event_id="stable-event",
                payload=selection_payload(),
            )
            duplicate = store.append(
                LifecycleEventType.SELECTION_MADE,
                execution_id="execution",
                task_id="task",
                attempt_id="attempt",
                event_id="stable-event",
                payload=selection_payload(),
            )

            self.assertEqual(first, duplicate)
            self.assertEqual(len(store.read()), 1)

            with self.assertRaisesRegex(ValueError, "collision"):
                store.append(
                    LifecycleEventType.EXECUTION_STARTED,
                    execution_id="execution",
                    task_id="task",
                    attempt_id="attempt",
                    event_id="stable-event",
                )

    def test_projector_ignores_identical_duplicate_and_rejects_sequence_gap(self) -> None:
        event = LifecycleEvent(
            LifecycleEventType.SELECTION_MADE,
            "execution",
            1,
            "task",
            "attempt",
            event_id="event-1",
            payload=selection_payload(),
        )
        state = EventProjector().replay((event, event))
        self.assertEqual(state.duplicate_event_ids, ("event-1",))
        self.assertEqual(len(state.applied_event_ids), 1)

        gap = LifecycleEvent(
            LifecycleEventType.SELECTION_MADE,
            "execution",
            2,
            "task",
            "attempt",
            payload=selection_payload(),
        )
        with self.assertRaisesRegex(ReplayError, "Sequence gap"):
            EventProjector().replay((gap,))

    def test_projector_rejects_invalid_transition(self) -> None:
        selected = LifecycleEvent(LifecycleEventType.SELECTION_MADE, "execution", 1, "task", "attempt", payload=selection_payload())
        evaluated = LifecycleEvent(LifecycleEventType.EVALUATION_COMPLETED, "execution", 2, "task", "attempt")
        with self.assertRaisesRegex(ReplayError, "requires terminal"):
            EventProjector().replay((selected, evaluated))

    def test_projector_rejects_parent_identity_change(self) -> None:
        selected = LifecycleEvent(
            LifecycleEventType.SELECTION_MADE,
            "execution",
            1,
            "task",
            "attempt",
            payload=selection_payload(),
        )
        started = LifecycleEvent(
            LifecycleEventType.EXECUTION_STARTED,
            "execution",
            2,
            "task",
            "attempt",
            parent_attempt_id="different-parent",
        )
        with self.assertRaisesRegex(ReplayError, "Parent attempt id changed"):
            EventProjector().replay((selected, started))

    def test_reconciles_started_attempt_on_next_recorder_startup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonlEventStore(Path(directory) / "events.jsonl")
            store.append(
                LifecycleEventType.SELECTION_MADE,
                execution_id="execution",
                task_id="task",
                attempt_id="attempt",
                payload=selection_payload(),
            )
            store.append(
                LifecycleEventType.EXECUTION_STARTED,
                execution_id="execution",
                task_id="task",
                attempt_id="attempt",
            )

            recorder = LifecycleRecorder(store)
            state = recorder.rebuild_state()

            events = store.read()
            self.assertEqual(events[-2].event_type, LifecycleEventType.EXECUTION_RECONCILED)
            self.assertEqual(events[-2].payload["status"], "abandoned")
            self.assertEqual(events[-1].event_type, LifecycleEventType.OUTCOME_FINALIZED)
            self.assertEqual(state.executions["execution"].attempts["attempt"].status, "finalized")

    def test_does_not_reconcile_attempt_owned_by_live_local_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonlEventStore(Path(directory) / "events.jsonl")
            common = {"execution_id": "execution", "task_id": "task", "attempt_id": "attempt"}
            store.append(LifecycleEventType.SELECTION_MADE, payload=selection_payload(), **common)
            store.append(
                LifecycleEventType.EXECUTION_STARTED,
                payload={"owner_pid": os.getpid(), "owner_host": socket.gethostname()},
                **common,
            )

            recorder = LifecycleRecorder(store)

            self.assertEqual(len(store.read()), 2)
            state = recorder.rebuild_state()
            self.assertEqual(state.executions["execution"].attempts["attempt"].status, "started")

    def test_replay_and_materialized_state_are_byte_stable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonlEventStore(Path(directory) / "events.jsonl")
            recorder = LifecycleRecorder(store)
            common = {"execution_id": "execution", "task_id": "task", "attempt_id": "attempt"}
            recorder.record(LifecycleEventType.SELECTION_MADE, payload=selection_payload(), **common)
            recorder.record(LifecycleEventType.EXECUTION_STARTED, **common)
            recorder.record(LifecycleEventType.EXECUTION_TERMINAL, payload={"status": "completed"}, **common)
            recorder.record(LifecycleEventType.OUTCOME_FINALIZED, payload={"status": "completed"}, **common)

            first = replay_event_log(store.path)
            second = replay_events(store.read())
            materialized = json.loads(recorder.state_store.path.read_text())

            self.assertEqual(first.to_json(), second.to_json())
            self.assertEqual(first.to_dict(), materialized)
            self.assertEqual(replay_digest(first), replay_digest(second))

    def test_legacy_replay_only_reports_schema_and_never_counterfactual_support(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "executions.jsonl"
            rows = [
                {"agent_id": "codex", "status": "completed", "verification": {"status": "passed"}},
                {
                    "agent_id": "claude-code",
                    "status": "completed",
                    "evaluations": [{"role": "quality", "observed": True, "score": 1.0}],
                },
            ]
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\nnot-json\n")

            report = validate_legacy_execution_log(path)

            self.assertEqual(report.row_count, 3)
            self.assertEqual(report.valid_record_count, 2)
            self.assertEqual(report.typed_quality_record_count, 1)
            self.assertEqual(report.malformed_row_count, 1)
            self.assertFalse(report.counterfactual_supported)


class AttemptSummaryTests(unittest.TestCase):
    def test_counts_exact_projector_statuses_from_one_state(self) -> None:
        selected = LifecycleEvent(
            LifecycleEventType.SELECTION_MADE,
            "selected-execution",
            1,
            "task",
            "selected-attempt",
            payload=selection_payload(),
        )
        finalized_common = {
            "execution_id": "finalized-execution",
            "task_id": "task",
            "attempt_id": "finalized-attempt",
        }
        finalized = (
            LifecycleEvent(LifecycleEventType.SELECTION_MADE, sequence=1, payload=selection_payload(), **finalized_common),
            LifecycleEvent(LifecycleEventType.EXECUTION_STARTED, sequence=2, **finalized_common),
            LifecycleEvent(
                LifecycleEventType.EXECUTION_TERMINAL,
                sequence=3,
                payload={"status": "completed"},
                **finalized_common,
            ),
            LifecycleEvent(LifecycleEventType.OUTCOME_FINALIZED, sequence=4, **finalized_common),
        )

        summary = summarize_attempts(replay_events((selected, *finalized)))

        self.assertEqual(summary.attempt_count, 2)
        self.assertEqual(summary.finalized_attempt_count, 1)
        self.assertEqual(summary.incomplete_attempt_count, 1)
        self.assertEqual(summary.attempt_status_counts, {"finalized": 1, "selected": 1})

    def test_empty_state_does_not_invent_statuses(self) -> None:
        summary = summarize_attempts(replay_events(()))
        self.assertEqual(summary.attempt_count, 0)
        self.assertEqual(summary.finalized_attempt_count, 0)
        self.assertEqual(summary.incomplete_attempt_count, 0)
        self.assertEqual(summary.attempt_status_counts, {})


class KernelLifecycleTests(unittest.TestCase):
    def test_started_event_is_durable_before_runner_is_called(self) -> None:
        class InspectingRunner:
            def __init__(self, event_path: Path) -> None:
                self.event_path = event_path

            def run(self, command, cwd, timeout_seconds):
                events = JsonlEventStore(self.event_path).read()
                self_types = [event.event_type for event in events]
                if self_types != [LifecycleEventType.SELECTION_MADE, LifecycleEventType.EXECUTION_STARTED]:
                    raise AssertionError(f"unexpected pre-run events: {self_types}")
                return ProcessResult(command, ExecutionStatus.COMPLETED, "done", "", 0, 1)

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            event_path = workspace / ".orchestrator" / "events.jsonl"
            kernel = OrchestratorKernel(
                {"codex": CodexAgent()},
                JsonlExecutionLogger(workspace / "executions.jsonl"),
                workspace,
                InspectingRunner(event_path),
            )

            record = kernel.execute(Task("Do work", "Done"), "codex")

            events = JsonlEventStore(event_path).read()
            self.assertEqual(record.task_id, events[0].task_id)
            self.assertEqual([event.event_type for event in events], [
                LifecycleEventType.SELECTION_MADE,
                LifecycleEventType.EXECUTION_STARTED,
                LifecycleEventType.EXECUTION_TERMINAL,
                LifecycleEventType.OUTCOME_FINALIZED,
            ])
            self.assertEqual([event.sequence for event in events], [1, 2, 3, 4])

    def test_keyboard_interrupt_preserves_terminal_event_and_exception(self) -> None:
        class InterruptingRunner:
            def run(self, command, cwd, timeout_seconds):
                raise KeyboardInterrupt()

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            kernel = OrchestratorKernel(
                {"codex": CodexAgent()},
                JsonlExecutionLogger(workspace / "executions.jsonl"),
                workspace,
                InterruptingRunner(),
            )

            with self.assertRaises(KeyboardInterrupt):
                kernel.execute(Task("Do work", "Done"), "codex")

            events = JsonlEventStore(workspace / ".orchestrator" / "events.jsonl").read()
            self.assertEqual(events[-2].event_type, LifecycleEventType.EXECUTION_TERMINAL)
            self.assertEqual(events[-2].payload["status"], "interrupted")
            self.assertEqual(events[-1].event_type, LifecycleEventType.OUTCOME_FINALIZED)
            state = replay_events(events)
            attempt = next(iter(next(iter(state.executions.values())).attempts.values()))
            self.assertEqual(attempt.status, "finalized")


if __name__ == "__main__":
    unittest.main()
