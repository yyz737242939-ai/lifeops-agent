from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.memory.document_store import MemoryDocumentStore
from app.memory.errors import (
    MemoryDocumentStoreError,
    MemoryErrorCode,
    MemoryRepositoryError,
)
from app.memory.models import MemoryWriteContext
from app.memory.repository import SqliteMemoryRepository
from app.memory.service import MemoryService
from tests.helpers import create_test_connection


class MemoryServiceSaveTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "memory"
        self.conn = create_test_connection()
        self.repository = SqliteMemoryRepository(self.conn)
        self.store = MemoryDocumentStore(self.root)

    def tearDown(self) -> None:
        self.conn.close()
        self.temporary.cleanup()

    def test_save_is_file_first_then_commits_metadata_index(self) -> None:
        service = self._service(self.repository)

        result = service.save_confirmed(
            "\r\n  用户偏好靠窗座位。\r\n",
            ("偏好", "出行"),
            _write_context(),
        )

        self.assertEqual(result.entry.document.content, "用户偏好靠窗座位。")
        self.assertEqual(result.entry.record, self.repository.get_version("memory_1", 1))
        self.assertEqual(
            (self.root / result.entry.record.relative_path).read_text(encoding="utf-8"),
            "用户偏好靠窗座位。",
        )
        self.assertEqual(service.audit_orphans(), ())

    def test_file_failure_leaves_sqlite_empty(self) -> None:
        blocked_root = self.root / "blocked"
        blocked_root.parent.mkdir(parents=True)
        blocked_root.write_text("not a directory", encoding="utf-8")
        service = MemoryService(
            self.repository,
            MemoryDocumentStore(blocked_root),
            id_factory=lambda: "memory_1",
            clock=lambda: "2026-07-16T00:00:00Z",
        )

        with self.assertRaises(MemoryDocumentStoreError):
            service.save_confirmed("confirmed", (), _write_context())

        self.assertEqual(self.repository.list_all_index(), ())

    def test_index_failure_returns_failure_and_leaves_auditable_orphan(self) -> None:
        service = self._service(_FailingInsertRepository(self.repository))

        with self.assertRaises(MemoryRepositoryError) as caught:
            service.save_confirmed("confirmed", (), _write_context())

        self.assertEqual(caught.exception.code, MemoryErrorCode.INDEX_FAILED.value)
        self.assertEqual(self.repository.list_all_index(), ())
        self.assertEqual(service.audit_orphans(), ("entries/memory_1/v1.md",))

    def test_orphan_audit_keeps_committed_and_reports_only_unindexed_versions(self) -> None:
        service = self._service(self.repository)
        saved = service.save_confirmed("committed", (), _write_context())
        self.store.write_immutable("memory_2", 1, "orphan")

        self.assertEqual(
            service.audit_orphans(),
            ("entries/memory_2/v1.md",),
        )
        self.assertTrue((self.root / saved.entry.record.relative_path).exists())

    def _service(self, repository) -> MemoryService:
        return MemoryService(
            repository,
            self.store,
            id_factory=lambda: "memory_1",
            clock=lambda: "2026-07-16T00:00:00Z",
        )


class _FailingInsertRepository:
    def __init__(self, delegate: SqliteMemoryRepository) -> None:
        self._delegate = delegate

    def insert_active(self, record) -> None:
        raise MemoryRepositoryError(
            "Memory index operation failed.",
            code=MemoryErrorCode.INDEX_FAILED,
        )

    def find_active_duplicate(self, content_hash):
        return self._delegate.find_active_duplicate(content_hash)

    def list_active_index(self):
        return self._delegate.list_active_index()

    def list_all_index(self):
        return self._delegate.list_all_index()


def _write_context() -> MemoryWriteContext:
    return MemoryWriteContext(
        source_session_id="session_1",
        source_turn_id="turn_1",
        source_run_id="run_1",
        source_tool_call_id="call_1",
        confirmation_ref="confirmation_1",
        evidence_ref="evidence_1",
    )


if __name__ == "__main__":
    unittest.main()
