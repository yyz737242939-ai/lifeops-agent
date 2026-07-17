from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.context.models import ContextQuery, ContextQueryOrigin
from app.memory.document_store import MemoryDocumentStore
from app.memory.errors import MemoryErrorCode, MemoryRepositoryError
from app.memory.models import MemoryStatus, MemoryWriteContext
from app.memory.repository import SqliteMemoryRepository
from app.memory.retriever import DeterministicMemoryRetriever
from app.memory.service import MemoryConflictError, MemoryService
from tests.helpers import create_test_connection


class MemoryUpdateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "memory"
        self.conn = create_test_connection()
        self.repository = SqliteMemoryRepository(self.conn)
        self.store = MemoryDocumentStore(self.root)
        self.service = MemoryService(
            self.repository,
            self.store,
            id_factory=lambda: "memory_1",
            clock=lambda: "2026-07-16T00:00:00Z",
        )
        self.first = self.service.save_confirmed(
            "Prefers a window seat.",
            ("travel",),
            _write_context("call_save"),
        )

    def tearDown(self) -> None:
        self.conn.close()
        self.temporary.cleanup()

    def test_update_writes_new_version_and_atomically_supersedes_previous(self) -> None:
        service = self._update_service(self.repository)

        updated = service.update_confirmed(
            "memory_1",
            1,
            "Prefers an aisle seat.",
            ("travel",),
            _write_context("call_update"),
        )

        versions = self.repository.list_versions("memory_1")
        self.assertEqual(
            tuple(record.status for record in versions),
            (MemoryStatus.SUPERSEDED, MemoryStatus.ACTIVE),
        )
        self.assertEqual(updated.entry.record.version, 2)
        self.assertEqual(updated.entry.record.supersedes_version, 1)
        self.assertEqual(updated.entry.record.source_tool_call_id, "call_update")
        self.assertEqual(
            (self.root / "entries" / "memory_1" / "v1.md").read_text(encoding="utf-8"),
            "Prefers a window seat.",
        )
        self.assertEqual(
            (self.root / "entries" / "memory_1" / "v2.md").read_text(encoding="utf-8"),
            "Prefers an aisle seat.",
        )

    def test_stale_expected_version_is_zero_write(self) -> None:
        service = self._update_service(self.repository)
        service.update_confirmed(
            "memory_1", 1, "Prefers an aisle seat.", ("travel",), _write_context("call_2")
        )

        with self.assertRaises(MemoryRepositoryError) as caught:
            service.update_confirmed(
                "memory_1", 1, "Prefers no seat.", ("travel",), _write_context("call_3")
            )

        self.assertEqual(caught.exception.code, MemoryErrorCode.VERSION_CONFLICT.value)
        self.assertFalse((self.root / "entries" / "memory_1" / "v3.md").exists())
        self.assertEqual(len(self.repository.list_versions("memory_1")), 2)

    def test_index_failure_after_v2_file_leaves_orphan_and_v1_active(self) -> None:
        failing = _FailingSupersedeRepository(self.repository)
        service = self._update_service(failing)

        with self.assertRaises(MemoryRepositoryError):
            service.update_confirmed(
                "memory_1", 1, "Prefers an aisle seat.", ("travel",), _write_context("call_2")
            )

        self.assertEqual(self.repository.get_version("memory_1", 1).status, MemoryStatus.ACTIVE)
        self.assertEqual(failing.list_all_index(), (self.first.entry.record,))
        self.assertEqual(service.audit_orphans(), ("entries/memory_1/v2.md",))

    def test_update_conflict_with_other_active_memory_is_zero_write(self) -> None:
        MemoryService(
            self.repository,
            self.store,
            id_factory=lambda: "memory_2",
            clock=lambda: "2026-07-16T01:00:00Z",
        ).save_confirmed("Uses dark mode.", ("software",), _write_context("call_other"))

        with self.assertRaises(MemoryConflictError):
            self._update_service(self.repository).update_confirmed(
                "memory_1", 1, "Uses light mode.", ("software",), _write_context("call_2")
            )

        self.assertFalse((self.root / "entries" / "memory_1" / "v2.md").exists())
        self.assertEqual(len(self.repository.list_versions("memory_1")), 1)

    def test_same_content_update_is_idempotent_without_new_version(self) -> None:
        result = self._update_service(self.repository).update_confirmed(
            "memory_1",
            1,
            "  Prefers a window seat.  ",
            ("travel",),
            _write_context("call_2"),
        )

        self.assertTrue(result.idempotent_existing)
        self.assertEqual(result.entry.record.version, 1)
        self.assertEqual(len(self.repository.list_versions("memory_1")), 1)

    def test_same_content_with_changed_tags_creates_metadata_version(self) -> None:
        result = self._update_service(self.repository).update_confirmed(
            "memory_1",
            1,
            "Prefers a window seat.",
            ("seat-preference",),
            _write_context("call_2"),
        )

        self.assertFalse(result.idempotent_existing)
        self.assertEqual(result.entry.record.version, 2)
        self.assertEqual(len(self.repository.list_versions("memory_1")), 2)

    def test_retrieval_returns_only_new_active_version(self) -> None:
        self._update_service(self.repository).update_confirmed(
            "memory_1", 1, "Prefers an aisle seat.", ("travel",), _write_context("call_2")
        )

        results = DeterministicMemoryRetriever(self.repository, self.store).search(
            ContextQuery(
                "seat",
                ContextQueryOrigin.CURRENT_USER_GOAL,
                "session_1",
                "run_1",
                "turn_1",
            ),
            10,
            100,
        )

        self.assertEqual(tuple(item.content for item in results), ("Prefers an aisle seat.",))

    def _update_service(self, repository) -> MemoryService:
        return MemoryService(
            repository,
            self.store,
            id_factory=lambda: (_ for _ in ()).throw(AssertionError("unexpected id")),
            clock=lambda: "2026-07-16T02:00:00Z",
        )


class _FailingSupersedeRepository:
    def __init__(self, delegate: SqliteMemoryRepository) -> None:
        self._delegate = delegate

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    def supersede_and_insert(self, expected_version, new_record) -> None:
        raise MemoryRepositoryError(
            "Memory index operation failed.",
            code=MemoryErrorCode.INDEX_FAILED,
        )


def _write_context(tool_call_id: str) -> MemoryWriteContext:
    return MemoryWriteContext(
        "session_1",
        "turn_1",
        "run_1",
        tool_call_id,
        f"confirmation_{tool_call_id}",
        f"evidence_{tool_call_id}",
    )


if __name__ == "__main__":
    unittest.main()
