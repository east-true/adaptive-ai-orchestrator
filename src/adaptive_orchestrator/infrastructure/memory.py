from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from adaptive_orchestrator.core.domain import MemoryEntry, MemoryEntryType
from adaptive_orchestrator.infrastructure.logging import redact


class EngineeringMemoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, entry: MemoryEntry) -> None:
        payload = redact(asdict(entry))
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, default=str) + "\n")

    def search(self, entry_type: MemoryEntryType | None = None, tag: str | None = None, keyword: str | None = None) -> list[MemoryEntry]:
        if not self.path.exists():
            return []

        matches: list[MemoryEntry] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
                entry = MemoryEntry(
                    entry_type=MemoryEntryType(item["entry_type"]),
                    title=item["title"],
                    summary=item["summary"],
                    rationale=item.get("rationale", ""),
                    alternatives_considered=tuple(item.get("alternatives_considered", ())),
                    tags=tuple(item.get("tags", ())),
                    related_task_description=item.get("related_task_description"),
                )
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue

            if entry_type is not None and entry.entry_type is not entry_type:
                continue
            if tag is not None and tag not in entry.tags:
                continue
            if keyword is not None:
                haystack = " ".join((entry.title, entry.summary, entry.rationale)).lower()
                if keyword.lower() not in haystack:
                    continue
            matches.append(entry)
        return matches
