from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.context.models import ContextQuery, ContextQueryOrigin
from app.memory.document_store import MemoryDocumentStore
from app.memory.errors import MemoryErrorCode, MemoryRepositoryError
from app.memory.models import (
    MemoryEntry,
    MemoryIndexRecord,
    MemorySaveResult,
    MemoryStatus,
    encode_memory_tags,
)
from app.memory.repository import SqliteMemoryRepository
from app.memory.retriever import DeterministicMemoryRetriever
from tests.helpers import create_test_connection


class DeterministicMemoryRetrieverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "memory"
        self.conn = create_test_connection()
        self.repository = SqliteMemoryRepository(self.conn)
        self.store = MemoryDocumentStore(self.root)
        self.retriever = DeterministicMemoryRetriever(self.repository, self.store)

    def tearDown(self) -> None:
        self.conn.close()
        self.temporary.cleanup()

    def test_tag_substring_overlap_time_and_id_define_stable_order(self) -> None:
        self._save("memory_a", "unrelated preference", ("travel",), "00:00:00")
        self._save("memory_b", "travel by train", (), "01:00:00")
        self._save("memory_c", "travel by plane", (), "02:00:00")
        self._save("memory_d", "travel by boat", (), "02:00:00")

        first = self.retriever.search(_query("travel"), 10, 100)
        second = self.retriever.search(_query("travel"), 10, 100)

        self.assertEqual(first, second)
        self.assertEqual(
            tuple(item.provenance.attributes[0][1] for item in first),
            ("memory_a", "memory_c", "memory_d", "memory_b"),
        )

    def test_chinese_substring_and_english_punctuation_terms_match(self) -> None:
        self._save("memory_cn", "用户偏好靠窗座位。", ("出行",), "00:00:00")
        self._save("memory_en", "Prefers early morning trains.", (), "01:00:00")

        chinese = self.retriever.search(_query("靠窗座位"), 10, 100)
        english = self.retriever.search(_query("morning, trains"), 10, 100)

        self.assertEqual(chinese[0].content, "用户偏好靠窗座位。")
        self.assertEqual(english[0].content, "Prefers early morning trains.")

    def test_item_and_token_budgets_skip_oversized_entries_deterministically(self) -> None:
        self._save("memory_large", "travel " * 20, ("travel",), "02:00:00")
        self._save("memory_small", "travel train", (), "01:00:00")

        selected = self.retriever.search(_query("travel"), 1, 4)

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].content, "travel train")
        self.assertLessEqual(selected[0].estimated_tokens, 4)
        self.assertEqual(self.retriever.search(_query("travel"), 0, 100), ())
        self.assertEqual(self.retriever.search(_query("travel"), 10, 0), ())

    def test_corrupt_or_missing_single_file_is_skipped_without_hiding_valid_memory(self) -> None:
        valid = self._save("memory_valid", "travel train", (), "01:00:00")
        corrupt = self._save("memory_corrupt", "travel plane", (), "02:00:00")
        (self.root / corrupt.entry.record.relative_path).write_text(
            "tampered", encoding="utf-8"
        )
        missing = self._save("memory_missing", "travel boat", (), "03:00:00")
        (self.root / missing.entry.record.relative_path).unlink()

        selected = self.retriever.search(_query("travel"), 10, 100)

        self.assertEqual(tuple(item.content for item in selected), (valid.entry.document.content,))

    def test_index_failure_degrades_to_empty_memory(self) -> None:
        retriever = DeterministicMemoryRetriever(_FailingListRepository(), self.store)

        self.assertEqual(retriever.search(_query("anything"), 10, 100), ())

    def _save(
        self,
        memory_id: str,
        content: str,
        tags: tuple[str, ...],
        time: str,
    ):
        document = self.store.write_immutable(memory_id, 1, content)
        record = MemoryIndexRecord(
            memory_id=memory_id,
            version=1,
            status=MemoryStatus.ACTIVE,
            relative_path=document.relative_path,
            content_hash=document.content_hash,
            tags_json=encode_memory_tags(tags),
            created_at=f"2026-07-16T{time}Z",
            updated_at=f"2026-07-16T{time}Z",
            supersedes_memory_id=None,
            supersedes_version=None,
            source_session_id="session_1",
            source_turn_id="turn_1",
            source_run_id="run_1",
            source_tool_call_id="call_1",
            confirmation_ref="confirmation_1",
            evidence_ref="evidence_1",
        )
        self.repository.insert_active(record)
        return MemorySaveResult(MemoryEntry(document, record))


class _FailingListRepository:
    def list_active_index(self):
        raise MemoryRepositoryError(
            "Memory index operation failed.",
            code=MemoryErrorCode.INDEX_FAILED,
        )


def _query(text: str) -> ContextQuery:
    return ContextQuery(
        text=text,
        origin=ContextQueryOrigin.CURRENT_USER_GOAL,
        session_id="session_1",
        run_id="run_1",
        turn_id="turn_1",
    )


if __name__ == "__main__":
    unittest.main()
