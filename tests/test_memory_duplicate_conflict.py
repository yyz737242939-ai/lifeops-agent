from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.memory.models import MemoryWriteContext
from app.memory.document_store import MemoryDocumentStore
from app.memory.repository import SqliteMemoryRepository
from app.memory.service import MemoryConflictError, MemoryService
from tests.helpers import create_test_connection


class MemoryDuplicateConflictTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "memory"
        self.conn = create_test_connection()
        self.repository = SqliteMemoryRepository(self.conn)
        self.store = MemoryDocumentStore(self.root)
        self.first = self._service("memory_1", "00:00:00").save_confirmed(
            "Prefers a window seat on trains.",
            ("travel",),
            _write_context(),
        )

    def tearDown(self) -> None:
        self.conn.close()
        self.temporary.cleanup()

    def test_normalized_duplicate_is_idempotent_without_new_file_or_index(self) -> None:
        service = MemoryService(
            self.repository,
            self.store,
            id_factory=lambda: (_ for _ in ()).throw(AssertionError("new id requested")),
            clock=lambda: (_ for _ in ()).throw(AssertionError("clock requested")),
        )

        duplicate = service.save_confirmed(
            "\r\n  Prefers a window seat on trains.  \r\n",
            ("different-tag",),
            _write_context(),
        )

        self.assertTrue(duplicate.idempotent_existing)
        self.assertEqual(duplicate.entry.record.memory_id, "memory_1")
        self.assertEqual(len(self.repository.list_all_index()), 1)
        self.assertEqual(tuple((self.root / "entries").glob("*/v*.md")), (
            self.root / "entries" / "memory_1" / "v1.md",
        ))

    def test_shared_tag_conflict_is_returned_before_any_write(self) -> None:
        service = self._service("memory_2", "01:00:00")

        with self.assertRaises(MemoryConflictError) as caught:
            service.save_confirmed(
                "Prefers an aisle seat on flights.",
                ("travel",),
                _write_context(),
            )

        self.assertEqual(caught.exception.candidates[0].memory_id, "memory_1")
        self.assertEqual(caught.exception.candidates[0].reason, "shared_tag")
        self.assertEqual(len(self.repository.list_all_index()), 1)
        self.assertFalse((self.root / "entries" / "memory_2").exists())

    def test_keyword_conflict_without_tags_is_detected(self) -> None:
        service = self._service("memory_2", "01:00:00")

        candidates = service.detect_conflicts(
            "Prefers an aisle seat on trains.",
            (),
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].memory_id, "memory_1")
        self.assertEqual(candidates[0].reason, "keyword_overlap")

    def test_unrelated_content_can_create_another_active_memory(self) -> None:
        second = self._service("memory_2", "01:00:00").save_confirmed(
            "Uses dark mode in coding tools.",
            ("software",),
            _write_context(),
        )

        self.assertFalse(second.idempotent_existing)
        self.assertEqual(len(self.repository.list_active_index()), 2)

    def test_corrupt_duplicate_is_not_reported_as_success(self) -> None:
        (self.root / self.first.entry.record.relative_path).write_text(
            "tampered", encoding="utf-8"
        )

        with self.assertRaises(Exception):
            self._service("memory_2", "01:00:00").save_confirmed(
                "Prefers a window seat on trains.",
                (),
                _write_context(),
            )

        self.assertEqual(len(self.repository.list_all_index()), 1)
        self.assertFalse((self.root / "entries" / "memory_2").exists())

    def _service(self, memory_id: str, time: str) -> MemoryService:
        return MemoryService(
            self.repository,
            self.store,
            id_factory=lambda: memory_id,
            clock=lambda: f"2026-07-16T{time}Z",
        )


def _write_context() -> MemoryWriteContext:
    return MemoryWriteContext(
        "session_1",
        "turn_1",
        "run_1",
        "call_1",
        "confirmation_1",
        "evidence_1",
    )


if __name__ == "__main__":
    unittest.main()
