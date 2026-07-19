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
from app.memory.service import MemoryService
from app.storage.migrations import migrate
from app.storage.sqlite import connect_sqlite


class MemoryArchiveHistoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.root = base / "memory"
        self.database = base / "lifeops.db"
        self.conn = connect_sqlite(self.database)
        migrate(self.conn)
        self.repository = SqliteMemoryRepository(self.conn)
        self.store = MemoryDocumentStore(self.root)
        self.service = self._service(self.repository, "00:00:00")
        self.service.save_confirmed(
            "Prefers a window seat.",
            ("travel",),
            _write_context("call_save"),
        )

    def tearDown(self) -> None:
        self.conn.close()
        self.temporary.cleanup()

    def test_archive_changes_only_active_lifecycle_and_preserves_file(self) -> None:
        archived = self.service.archive_confirmed(
            "memory_1",
            1,
            _write_context("call_archive"),
        )

        self.assertEqual(archived.status, MemoryStatus.ARCHIVED)
        self.assertEqual(self.service.list_active(), ())
        self.assertEqual(self.service.list_archived()[0].record, archived)
        self.assertEqual(self.service.list_history("memory_1")[0].record, archived)
        self.assertTrue((self.root / archived.relative_path).exists())
        self.assertEqual(self._search("seat"), ())

    def test_updated_history_keeps_superseded_and_archived_versions(self) -> None:
        update_service = self._service(self.repository, "01:00:00")
        update_service.update_confirmed(
            "memory_1",
            1,
            "Prefers an aisle seat.",
            ("travel",),
            _write_context("call_update"),
        )
        archived = self._service(self.repository, "02:00:00").archive_confirmed(
            "memory_1",
            2,
            _write_context("call_archive"),
        )

        history = self.service.list_history("memory_1")
        self.assertEqual(
            tuple(entry.record.status for entry in history),
            (MemoryStatus.SUPERSEDED, MemoryStatus.ARCHIVED),
        )
        self.assertEqual(tuple(entry.record.version for entry in history), (1, 2))
        self.assertEqual(self.service.list_archived()[0].record, archived)
        self.assertTrue((self.root / "entries" / "memory_1" / "v1.md").exists())
        self.assertTrue((self.root / "entries" / "memory_1" / "v2.md").exists())

    def test_stale_or_repeated_archive_is_fail_closed(self) -> None:
        with self.assertRaises(MemoryRepositoryError) as stale:
            self.service.archive_confirmed(
                "memory_1", 2, _write_context("call_stale")
            )
        self.assertEqual(stale.exception.code, MemoryErrorCode.VERSION_CONFLICT.value)
        self.assertEqual(self.repository.get_version("memory_1", 1).status, MemoryStatus.ACTIVE)

        self.service.archive_confirmed("memory_1", 1, _write_context("call_archive"))
        with self.assertRaises(MemoryRepositoryError) as repeated:
            self.service.archive_confirmed(
                "memory_1", 1, _write_context("call_repeat")
            )
        self.assertEqual(repeated.exception.code, MemoryErrorCode.ALREADY_ARCHIVED.value)

    def test_restart_rebuilds_active_reads_from_sqlite_file_and_hash(self) -> None:
        self.conn.close()
        reopened = connect_sqlite(self.database)
        try:
            migrate(reopened)
            repository = SqliteMemoryRepository(reopened)
            service = self._service(repository, "03:00:00")
            retriever = DeterministicMemoryRetriever(repository, MemoryDocumentStore(self.root))

            results = retriever.search(_query("window seat"), 10, 100)

            self.assertEqual(tuple(item.content for item in results), ("Prefers a window seat.",))
            self.assertEqual(service.list_history("memory_1")[0].record.version, 1)
            archived = service.archive_confirmed(
                "memory_1", 1, _write_context("call_restart_archive")
            )
            self.assertEqual(archived.status, MemoryStatus.ARCHIVED)
            self.assertEqual(retriever.search(_query("window seat"), 10, 100), ())
        finally:
            reopened.close()
            self.conn = connect_sqlite(self.database)

    def test_management_lists_skip_corrupt_file_without_hiding_other_entries(self) -> None:
        second = MemoryService(
            self.repository,
            self.store,
            id_factory=lambda: "memory_2",
            clock=lambda: "2026-07-16T01:00:00Z",
        ).save_confirmed("Uses dark mode.", ("software",), _write_context("call_2"))
        (self.root / "entries" / "memory_1" / "v1.md").write_text(
            "tampered", encoding="utf-8"
        )

        active = self.service.list_active()

        self.assertEqual(active, (second.entry,))

    def test_archive_commits_even_when_content_file_is_corrupt(self) -> None:
        (self.root / "entries" / "memory_1" / "v1.md").write_text(
            "tampered", encoding="utf-8"
        )

        archived = self.service.archive_confirmed(
            "memory_1", 1, _write_context("call_archive")
        )

        self.assertEqual(archived.status, MemoryStatus.ARCHIVED)
        self.assertEqual(
            self.repository.get_version("memory_1", 1).status,
            MemoryStatus.ARCHIVED,
        )
        self.assertEqual(self.service.list_archived(), ())

    def _service(self, repository, time: str) -> MemoryService:
        return MemoryService(
            repository,
            self.store,
            id_factory=lambda: "memory_1",
            clock=lambda: f"2026-07-16T{time}Z",
        )

    def _search(self, text: str):
        return DeterministicMemoryRetriever(self.repository, self.store).search(
            _query(text), 10, 100
        )


def _query(text: str) -> ContextQuery:
    return ContextQuery(
        text,
        ContextQueryOrigin.CURRENT_USER_GOAL,
        "session_1",
        "run_1",
        "turn_1",
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
