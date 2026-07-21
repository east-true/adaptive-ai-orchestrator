import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.core.domain import MemoryEntry, MemoryEntryType
from adaptive_orchestrator.infrastructure.memory import EngineeringMemoryStore


class EngineeringMemoryStoreTests(unittest.TestCase):
    def test_records_and_searches_back_without_filters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.jsonl"
            store = EngineeringMemoryStore(path)
            entry = MemoryEntry(
                MemoryEntryType.ARCHITECTURE_DECISION,
                "Use JSONL",
                "Store explicit memory entries.",
                rationale="It is append-only.",
                alternatives_considered=("sqlite",),
                tags=("memory", "architecture"),
                related_task_description="Design the memory store",
            )
            store.record(entry)

            results = store.search()
            self.assertEqual(results, [entry])

    def test_search_filters_by_entry_type(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.jsonl"
            store = EngineeringMemoryStore(path)
            store.record(MemoryEntry(MemoryEntryType.ARCHITECTURE_DECISION, "Decision", "Use JSONL"))
            store.record(MemoryEntry(MemoryEntryType.FAILURE_HISTORY, "Failure", "Malformed lines are skipped"))

            results = store.search(entry_type=MemoryEntryType.FAILURE_HISTORY)
            self.assertEqual([entry.entry_type for entry in results], [MemoryEntryType.FAILURE_HISTORY])

    def test_search_filters_by_tag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.jsonl"
            store = EngineeringMemoryStore(path)
            store.record(MemoryEntry(MemoryEntryType.PROJECT_CONTEXT, "Context", "Workspace notes", tags=("workspace", "context")))
            store.record(MemoryEntry(MemoryEntryType.CODE_EVOLUTION, "Evolution", "Refactor", tags=("refactor",)))

            results = store.search(tag="workspace")
            self.assertEqual([entry.title for entry in results], ["Context"])

    def test_search_filters_by_keyword_case_insensitively_across_all_text_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.jsonl"
            store = EngineeringMemoryStore(path)
            store.record(
                MemoryEntry(
                    MemoryEntryType.DESIGN_REASONING,
                    "Why this route",
                    "The summary does not mention it.",
                    rationale="We kept the old path for CACHE invalidation safety.",
                )
            )

            results = store.search(keyword="cache")
            self.assertEqual([entry.title for entry in results], ["Why this route"])

    def test_redacts_sensitive_values_on_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.jsonl"
            store = EngineeringMemoryStore(path)
            store.record(
                MemoryEntry(
                    MemoryEntryType.PROJECT_CONTEXT,
                    "Credential note",
                    "credential: abc123",
                )
            )

            payload = json.loads(path.read_text())
            self.assertEqual(payload["summary"], "credential=[REDACTED]")
            self.assertNotIn("abc123", payload["summary"])

    def test_skips_malformed_lines_without_raising(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "memory.jsonl"
            path.write_text(
                "\n".join(
                    [
                        json.dumps({
                            "entry_type": "PROJECT_CONTEXT",
                            "title": "First",
                            "summary": "Valid line",
                            "rationale": "",
                            "alternatives_considered": [],
                            "tags": ["context"],
                            "related_task_description": None,
                        }),
                        "{not valid json",
                        json.dumps({
                            "entry_type": "CODE_EVOLUTION",
                            "title": "Second",
                            "summary": "Still valid",
                            "rationale": "",
                            "alternatives_considered": [],
                            "tags": ["evolution"],
                            "related_task_description": None,
                        }),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            results = EngineeringMemoryStore(path).search()
            self.assertEqual([entry.title for entry in results], ["First", "Second"])

    def test_missing_file_returns_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            results = EngineeringMemoryStore(Path(directory) / "missing.jsonl").search()
            self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
