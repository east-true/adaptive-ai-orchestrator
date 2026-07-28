import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.execution.agents import CodexAgent
from adaptive_orchestrator.core.domain import ExecutionStatus, Task
from adaptive_orchestrator.infrastructure.events import EventLogError, JsonlEventStore, LifecycleEvent, LifecycleEventType
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
from adaptive_orchestrator.routing.state import EventProjector, LifecycleRecorder, ReplayError, RoutingStateStore


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

    def test_direct_append_fails_closed_without_mutating_the_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonlEventStore(Path(directory) / "events.jsonl")

            with self.assertRaisesRegex(EventLogError, "LifecycleRecorder.record"):
                store.append(
                    LifecycleEventType.SELECTION_MADE,
                    execution_id="execution",
                    task_id="task",
                    attempt_id="attempt",
                    payload=selection_payload(),
                )

            self.assertEqual(store.read(), ())

    def test_stable_id_retry_after_projection_failure_uses_persisted_payload(self) -> None:
        class FailingStateStore(RoutingStateStore):
            def write(self, state):
                raise OSError("injected projection failure")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = JsonlEventStore(root / "events.jsonl")
            state_path = root / "routing-state.json"
            recorder = LifecycleRecorder(store, RoutingStateStore(state_path))
            payload = selection_payload()
            payload["api_key"] = "same-secret"
            payload["artifact_path"] = Path("reports/result.json")
            recorder.state_store = FailingStateStore(state_path)

            with self.assertRaisesRegex(OSError, "injected projection failure"):
                recorder.record(
                    LifecycleEventType.SELECTION_MADE,
                    execution_id="execution",
                    task_id="task",
                    attempt_id="attempt",
                    event_id="stable-event",
                    payload=payload,
                )

            first = store.read()[0]
            recorder.state_store = RoutingStateStore(state_path)
            duplicate = recorder.record(
                LifecycleEventType.SELECTION_MADE,
                execution_id="execution",
                task_id="task",
                attempt_id="attempt",
                event_id="stable-event",
                payload=payload,
            )

            self.assertEqual(first, duplicate)
            self.assertEqual(len(store.read()), 1)
            self.assertEqual(first.payload["api_key"], "[REDACTED]")
            self.assertEqual(first.payload["artifact_path"], "reports/result.json")
            self.assertIn("execution", recorder.state_store.read()["executions"])

            with self.assertRaisesRegex(ValueError, "collision"):
                recorder.record(
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

    def test_recorder_rejects_invalid_transition_before_durable_append(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonlEventStore(Path(directory) / "events.jsonl")
            recorder = LifecycleRecorder(store)
            common = {
                "execution_id": "execution",
                "task_id": "task",
                "attempt_id": "attempt",
            }

            with self.assertRaisesRegex(ReplayError, "before selection"):
                recorder.record(LifecycleEventType.EXECUTION_STARTED, **common)

            self.assertEqual(store.read(), ())
            self.assertEqual(recorder.rebuild_state().executions, {})
            recorder.record(
                LifecycleEventType.SELECTION_MADE,
                payload=selection_payload(),
                **common,
            )
            self.assertEqual(len(store.read()), 1)

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
            seed = LifecycleRecorder(store)
            seed.record(
                LifecycleEventType.SELECTION_MADE,
                execution_id="execution",
                task_id="task",
                attempt_id="attempt",
                payload=selection_payload(),
            )
            seed.record(
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

    def test_explicit_reconcile_updates_the_materialized_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = JsonlEventStore(root / "events.jsonl")
            recorder = LifecycleRecorder(store, RoutingStateStore(root / "routing-state.json"))
            common = {"execution_id": "execution", "task_id": "task", "attempt_id": "attempt"}
            recorder.record(LifecycleEventType.SELECTION_MADE, payload=selection_payload(), **common)
            recorder.record(LifecycleEventType.EXECUTION_STARTED, **common)

            reconciled = recorder.reconcile_incomplete()

            self.assertEqual(len(reconciled), 1)
            materialized = recorder.state_store.read()
            self.assertIsNotNone(materialized)
            self.assertEqual(
                materialized["executions"]["execution"]["attempts"]["attempt"]["status"],
                "finalized",
            )

    def test_startup_finalizes_a_partially_reconciled_attempt_once(self) -> None:
        class FailFirstOutcomeStore(JsonlEventStore):
            def __init__(self, path: Path) -> None:
                super().__init__(path)
                self.failed = False

            def _append_validated(self, event_type, **kwargs):
                if event_type is LifecycleEventType.OUTCOME_FINALIZED and not self.failed:
                    self.failed = True
                    raise OSError("injected outcome append failure")
                return super()._append_validated(event_type, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            store = JsonlEventStore(path)
            common = {"execution_id": "execution", "task_id": "task", "attempt_id": "attempt"}
            seed = LifecycleRecorder(store)
            seed.record(LifecycleEventType.SELECTION_MADE, payload=selection_payload(), **common)
            seed.record(LifecycleEventType.EXECUTION_STARTED, **common)

            with self.assertRaisesRegex(OSError, "injected outcome append failure"):
                LifecycleRecorder(FailFirstOutcomeStore(path))

            self.assertEqual(
                [event.event_type for event in store.read()],
                [
                    LifecycleEventType.SELECTION_MADE,
                    LifecycleEventType.EXECUTION_STARTED,
                    LifecycleEventType.EXECUTION_RECONCILED,
                ],
            )

            LifecycleRecorder(JsonlEventStore(path))
            recorder = LifecycleRecorder(JsonlEventStore(path))

            events = store.read()
            self.assertEqual(
                sum(event.event_type is LifecycleEventType.EXECUTION_RECONCILED for event in events),
                1,
            )
            self.assertEqual(
                sum(event.event_type is LifecycleEventType.OUTCOME_FINALIZED for event in events),
                1,
            )
            self.assertEqual(
                events[-1].payload,
                {"status": "abandoned", "reason": "recovered_on_next_start"},
            )
            state = recorder.rebuild_state()
            self.assertEqual(state.executions["execution"].attempts["attempt"].status, "finalized")

    def test_does_not_reconcile_attempt_owned_by_live_local_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonlEventStore(Path(directory) / "events.jsonl")
            common = {"execution_id": "execution", "task_id": "task", "attempt_id": "attempt"}
            seed = LifecycleRecorder(store)
            seed.record(LifecycleEventType.SELECTION_MADE, payload=selection_payload(), **common)
            seed.record(
                LifecycleEventType.EXECUTION_STARTED,
                payload={"owner_pid": os.getpid(), "owner_host": socket.gethostname()},
                **common,
            )

            recorder = LifecycleRecorder(store)

            self.assertEqual(len(store.read()), 2)
            state = recorder.rebuild_state()
            self.assertEqual(state.executions["execution"].attempts["attempt"].status, "started")

    def test_concurrent_recorders_reconcile_one_abandoned_attempt_once(self) -> None:
        class BlockingFirstReadStore(JsonlEventStore):
            def __init__(self, path: Path, entered: threading.Event, release: threading.Event) -> None:
                super().__init__(path)
                self.entered = entered
                self.release = release
                self._first_read = True

            def read(self):
                events = super().read()
                if self._first_read:
                    self._first_read = False
                    self.entered.set()
                    if not self.release.wait(5):
                        raise RuntimeError("timed out waiting to release lifecycle read")
                return events

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "events.jsonl"
            store = JsonlEventStore(path)
            common = {"execution_id": "execution", "task_id": "task", "attempt_id": "attempt"}
            seed = LifecycleRecorder(store)
            seed.record(LifecycleEventType.SELECTION_MADE, payload=selection_payload(), **common)
            seed.record(LifecycleEventType.EXECUTION_STARTED, **common)

            entered = threading.Event()
            release = threading.Event()
            outcomes: list[BaseException] = []

            def create_recorder(event_store: JsonlEventStore) -> None:
                try:
                    LifecycleRecorder(event_store, RoutingStateStore(root / "routing-state.json"))
                except BaseException as exc:
                    outcomes.append(exc)

            first = threading.Thread(
                target=create_recorder,
                args=(BlockingFirstReadStore(path, entered, release),),
            )
            second = threading.Thread(target=create_recorder, args=(JsonlEventStore(path),))
            first.start()
            self.assertTrue(entered.wait(5))
            second.start()
            self.assertTrue(second.is_alive())
            release.set()
            first.join(5)
            second.join(5)

            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertEqual(outcomes, [])
            events = store.read()
            self.assertEqual(
                [event.event_type for event in events],
                [
                    LifecycleEventType.SELECTION_MADE,
                    LifecycleEventType.EXECUTION_STARTED,
                    LifecycleEventType.EXECUTION_RECONCILED,
                    LifecycleEventType.OUTCOME_FINALIZED,
                ],
            )
            state = EventProjector().replay(events)
            self.assertEqual(state.executions["execution"].attempts["attempt"].status, "finalized")

    def test_concurrent_rebuild_cannot_overwrite_a_newer_projection(self) -> None:
        class BlockingStateStore(RoutingStateStore):
            def __init__(self, path: Path, entered: threading.Event, release: threading.Event) -> None:
                super().__init__(path)
                self.entered = entered
                self.release = release

            def write(self, state):
                self.entered.set()
                if not self.release.wait(5):
                    raise RuntimeError("timed out waiting to release state write")
                super().write(state)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event_store = JsonlEventStore(root / "events.jsonl")
            state_path = root / "routing-state.json"
            first = LifecycleRecorder(event_store, RoutingStateStore(state_path))
            second = LifecycleRecorder(event_store, RoutingStateStore(state_path))
            first.record(
                LifecycleEventType.SELECTION_MADE,
                execution_id="execution-a",
                task_id="task-a",
                attempt_id="attempt-a",
                payload=selection_payload(),
            )

            entered = threading.Event()
            release = threading.Event()
            errors: list[BaseException] = []
            second_finished = threading.Event()
            first.state_store = BlockingStateStore(state_path, entered, release)

            def rebuild_old_snapshot() -> None:
                try:
                    first.rebuild_state()
                except BaseException as exc:
                    errors.append(exc)

            def record_new_execution() -> None:
                try:
                    second.record(
                        LifecycleEventType.SELECTION_MADE,
                        execution_id="execution-b",
                        task_id="task-b",
                        attempt_id="attempt-b",
                        payload=selection_payload(),
                    )
                except BaseException as exc:
                    errors.append(exc)
                finally:
                    second_finished.set()

            stale = threading.Thread(target=rebuild_old_snapshot)
            latest = threading.Thread(target=record_new_execution)
            stale.start()
            self.assertTrue(entered.wait(5))
            latest.start()
            self.assertFalse(second_finished.wait(0.1))
            release.set()
            stale.join(5)
            latest.join(5)

            self.assertFalse(stale.is_alive())
            self.assertFalse(latest.is_alive())
            self.assertEqual(errors, [])
            self.assertTrue(second_finished.is_set())
            event_execution_ids = {event.execution_id for event in event_store.read()}
            materialized = RoutingStateStore(state_path).read()
            self.assertIsNotNone(materialized)
            self.assertEqual(set(materialized["executions"]), event_execution_ids)

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
