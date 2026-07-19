from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.context.assembler import ContextAssembler
from app.context.models import (
    ContextBudget,
    ContextContributionKind,
    ContextQuery,
    ContextQueryOrigin,
    ConversationRole,
    ConversationTurn,
    ConversationTurnKind,
)
from app.context.repository import JsonlConversationRepository
from app.context.summarizer import FakeContextSummarizer
from app.context.summary_service import RollingSummaryService
from app.memory.document_store import MemoryDocumentStore
from app.memory.models import MemoryWriteContext
from app.memory.profile import FileProfileProvider
from app.memory.repository import SqliteMemoryRepository
from app.memory.retriever import DeterministicMemoryRetriever
from app.memory.service import MemoryService
from app.storage.migrations import migrate
from app.storage.sqlite import connect_sqlite


class MemoryContextIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.memory_root = base / "memory"
        self.conversation_root = base / "conversations"
        self.database = base / "lifeops.db"
        self.conn = connect_sqlite(self.database)
        migrate(self.conn)
        self.memory_repository = SqliteMemoryRepository(self.conn)
        self.memory_store = MemoryDocumentStore(self.memory_root)
        self.conversation_repository = JsonlConversationRepository(
            self.conversation_root
        )
        self._append_turn(1, "Earlier travel discussion.", "turn_old")
        self._append_turn(2, "What seat do I prefer?", "turn_current")
        self.memory_root.mkdir(parents=True, exist_ok=True)
        (self.memory_root / "profile.md").write_text(
            "Profile: user prefers concise answers.", encoding="utf-8"
        )
        MemoryService(
            self.memory_repository,
            self.memory_store,
            id_factory=lambda: "memory_seat",
            clock=lambda: "2026-07-16T00:00:00Z",
        ).save_confirmed(
            "User prefers a window seat.",
            ("seat",),
            _write_context(),
        )

    def tearDown(self) -> None:
        self.conn.close()
        self.temporary.cleanup()

    def test_profile_memory_recent_and_current_use_frozen_precedence(self) -> None:
        assembly = self._assembler().assemble(_query(), _budget())

        self.assertEqual(
            tuple(item.kind for item in assembly.contributions),
            (
                ContextContributionKind.PROFILE,
                ContextContributionKind.MEMORY,
                ContextContributionKind.CONVERSATION_TURN,
                ContextContributionKind.CURRENT_INPUT,
            ),
        )
        self.assertEqual(assembly.report.memory_candidate_count, 1)
        self.assertEqual(assembly.report.memory_selected_count, 1)
        self.assertTrue(assembly.report.profile_included)
        self.assertEqual(
            next(
                item.content
                for item in assembly.contributions
                if item.kind == ContextContributionKind.MEMORY
            ),
            "User prefers a window seat.",
        )

    def test_optional_profile_and_memory_cannot_squeeze_recent_or_current(self) -> None:
        assembly = self._assembler().assemble(
            _query(),
            ContextBudget(18, 8, 0, 18, 5, 18, 10),
        )

        kinds = tuple(item.kind for item in assembly.contributions)
        self.assertNotIn(ContextContributionKind.PROFILE, kinds)
        self.assertNotIn(ContextContributionKind.MEMORY, kinds)
        self.assertIn(ContextContributionKind.CONVERSATION_TURN, kinds)
        self.assertEqual(kinds[-1], ContextContributionKind.CURRENT_INPUT)

    def test_restart_rebuilds_context_from_same_profile_index_file_and_hash(self) -> None:
        self.conn.close()
        reopened = connect_sqlite(self.database)
        try:
            migrate(reopened)
            assembler = ContextAssembler(
                JsonlConversationRepository(self.conversation_root),
                RollingSummaryService(
                    JsonlConversationRepository(self.conversation_root),
                    FakeContextSummarizer(()),
                ),
                profile_provider=FileProfileProvider(self.memory_root),
                memory_retriever=DeterministicMemoryRetriever(
                    SqliteMemoryRepository(reopened),
                    MemoryDocumentStore(self.memory_root),
                ),
                id_factory=lambda prefix: f"{prefix}_restart",
                clock=lambda: "2026-07-16T01:00:00Z",
            )

            assembly = assembler.assemble(_query(), _budget())

            self.assertEqual(assembly.report.memory_selected_count, 1)
            self.assertTrue(assembly.report.profile_included)
        finally:
            reopened.close()
            self.conn = connect_sqlite(self.database)

    def test_archived_memory_is_excluded_without_affecting_profile(self) -> None:
        service = MemoryService(
            self.memory_repository,
            self.memory_store,
            clock=lambda: "2026-07-16T02:00:00Z",
        )
        service.archive_confirmed("memory_seat", 1, _write_context())

        assembly = self._assembler().assemble(_query(), _budget())

        self.assertEqual(assembly.report.memory_candidate_count, 0)
        self.assertEqual(assembly.report.memory_selected_count, 0)
        self.assertTrue(assembly.report.profile_included)

    def _assembler(self) -> ContextAssembler:
        return ContextAssembler(
            self.conversation_repository,
            RollingSummaryService(
                self.conversation_repository,
                FakeContextSummarizer(()),
            ),
            profile_provider=FileProfileProvider(self.memory_root),
            memory_retriever=DeterministicMemoryRetriever(
                self.memory_repository,
                self.memory_store,
            ),
            id_factory=lambda prefix: f"{prefix}_1",
            clock=lambda: "2026-07-16T01:00:00Z",
        )

    def _append_turn(self, sequence: int, content: str, turn_id: str) -> None:
        self.conversation_repository.append_turn(
            ConversationTurn(
                1,
                "session_1",
                turn_id,
                sequence,
                ConversationRole.USER,
                ConversationTurnKind.NATURAL_INPUT,
                content,
                "run_1",
                f"2026-07-16T00:00:0{sequence}Z",
            )
        )


def _query() -> ContextQuery:
    return ContextQuery(
        "What seat do I prefer?",
        ContextQueryOrigin.CURRENT_USER_GOAL,
        "session_1",
        "run_1",
        "turn_current",
    )


def _budget() -> ContextBudget:
    return ContextBudget(200, 8, 50, 50, 5, 50, 50)


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
