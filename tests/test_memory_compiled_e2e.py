from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.context.assembler import ContextAssembler
from app.context.models import ContextBudget, ContextContributionKind, ContextQuery, ContextQueryOrigin
from app.context.repository import JsonlConversationRepository
from app.context.summarizer import FakeContextSummarizer
from app.context.summary_service import RollingSummaryService
from app.executor.models import FinalAnswerDecision, ToolActionDecision
from app.executor.service import ReactExecutor
from app.intent.models import IntentDecision, IntentType
from app.memory.document_store import MemoryDocumentStore
from app.memory.models import MemoryStatus, MemoryWriteContext
from app.memory.profile import FileProfileProvider
from app.memory.repository import SqliteMemoryRepository
from app.memory.retriever import DeterministicMemoryRetriever
from app.memory.service import MemoryService
from app.memory.tools import (
    ARCHIVE_MEMORY_TOOL,
    LIST_MEMORY_TOOL,
    SAVE_MEMORY_TOOL,
    SEARCH_MEMORY_TOOL,
    UPDATE_MEMORY_TOOL,
    build_memory_tools,
)
from app.orchestration.graph import RuntimeOrchestrator
from app.policy.models import PolicyAction, PolicyDecision
from app.runtime.models import RuntimeRequest, RuntimeStatus
from app.skills.loader import discover_skills
from app.skills.registry import SkillRegistry
from app.skills.service import SkillService
from app.storage.migrations import migrate
from app.storage.sqlite import connect_sqlite
from app.tools.models import ConfirmedAction, ToolCall, ToolCallStatus
from app.tools.registry import ToolRegistry
from app.tools.runtime import ToolRuntime
from tests.executor_fakes import FakeExecutorModelClient


class MemoryCompiledE2ETest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.root = base / "memory"
        self.database = base / "lifeops.db"
        self.conversations = base / "conversations"
        self.conn = connect_sqlite(self.database)
        migrate(self.conn)
        self.repository = SqliteMemoryRepository(self.conn)
        self.store = MemoryDocumentStore(self.root)
        self.next_id = 1
        self.run_number = 0

    def tearDown(self) -> None:
        self.conn.close()
        self.temporary.cleanup()

    def test_01_profile_enters_context_without_profile_tool_or_write(self) -> None:
        self.root.mkdir(parents=True)
        (self.root / "profile.md").write_text("Profile stable preference.", encoding="utf-8")

        assembly = self._assembler().assemble(_query("hello"), _budget())
        runtime = self._scope(RuntimeRequest("hello", "session_1"), None)

        self.assertEqual(assembly.contributions[0].kind, ContextContributionKind.PROFILE)
        self.assertFalse(any(item.name.startswith("profile.") for item in runtime.registry.list_definitions()))
        self.assertEqual(self.repository.list_all_index(), ())

    def test_02_explicit_save_confirm_commits_file_index_and_evidence(self) -> None:
        call = ToolCall("call_save", SAVE_MEMORY_TOOL, {"content": "Window seat.", "tags": ["travel"]})

        state, model = self._invoke(call, effect="write", confirm=True)

        self.assertEqual(state["result"].status, RuntimeStatus.OK)
        observation = model.inputs[-1].observations[-1]
        self.assertEqual(observation.status, ToolCallStatus.SUCCEEDED)
        self.assertEqual(len(observation.evidence), 1)
        record = self.repository.get_version("memory_1", 1)
        self.assertEqual(record.evidence_ref, observation.evidence[0].reference)
        self.assertTrue((self.root / record.relative_path).exists())

    def test_03_duplicate_save_is_idempotent(self) -> None:
        self._invoke(ToolCall("call_1", SAVE_MEMORY_TOOL, {"content": "Window seat.", "tags": []}), effect="write")

        _, model = self._invoke(
            ToolCall("call_2", SAVE_MEMORY_TOOL, {"content": "  Window seat.  ", "tags": ["other"]}),
            effect="write",
        )

        observation = model.inputs[-1].observations[-1]
        self.assertTrue(observation.output["idempotent_existing"])
        self.assertEqual(len(self.repository.list_all_index()), 1)
        self.assertEqual(len(tuple((self.root / "entries").glob("*/v*.md"))), 1)

    def test_04_restart_retrieves_from_index_file_and_hash(self) -> None:
        self._invoke(ToolCall("call_1", SAVE_MEMORY_TOOL, {"content": "Window seat.", "tags": []}), effect="write")
        self.conn.close()
        self.conn = connect_sqlite(self.database)
        migrate(self.conn)
        self.repository = SqliteMemoryRepository(self.conn)

        _, model = self._invoke(
            ToolCall("call_search", SEARCH_MEMORY_TOOL, {"query": "window", "limit": 5}),
            effect="read",
            confirm=False,
        )

        items = model.inputs[-1].observations[-1].output["items"]
        self.assertEqual(items[0]["memory_id"], "memory_1")

    def test_05_conflict_then_confirmed_update_preserves_lifecycle(self) -> None:
        self._invoke(
            ToolCall("call_1", SAVE_MEMORY_TOOL, {"content": "Window seat.", "tags": ["travel"]}),
            effect="write",
        )
        _, conflict_model = self._invoke(
            ToolCall("call_2", SAVE_MEMORY_TOOL, {"content": "Aisle seat.", "tags": ["travel"]}),
            effect="write",
        )

        self.assertEqual(conflict_model.inputs[-1].observations[-1].status, ToolCallStatus.FAILED)
        self.assertEqual(len(self.repository.list_active_index()), 1)

        self._invoke(
            ToolCall(
                "call_3",
                UPDATE_MEMORY_TOOL,
                {
                    "memory_id": "memory_1",
                    "expected_version": 1,
                    "content": "Aisle seat.",
                    "tags": ["travel"],
                },
            ),
            effect="write",
        )

        self.assertEqual(
            tuple(item.status for item in self.repository.list_versions("memory_1")),
            (MemoryStatus.SUPERSEDED, MemoryStatus.ACTIVE),
        )

    def test_06_archive_excludes_normal_search_but_history_remains(self) -> None:
        self._invoke(ToolCall("call_1", SAVE_MEMORY_TOOL, {"content": "Window seat.", "tags": []}), effect="write")
        self._invoke(
            ToolCall("call_archive", ARCHIVE_MEMORY_TOOL, {"memory_id": "memory_1", "expected_version": 1}),
            effect="write",
        )
        _, search_model = self._invoke(
            ToolCall("call_search", SEARCH_MEMORY_TOOL, {"query": "window"}), effect="read", confirm=False
        )
        _, history_model = self._invoke(
            ToolCall("call_history", LIST_MEMORY_TOOL, {"mode": "history", "memory_id": "memory_1"}),
            effect="read",
            confirm=False,
        )

        self.assertEqual(search_model.inputs[-1].observations[-1].output["items"], [])
        history = history_model.inputs[-1].observations[-1].output["items"]
        self.assertEqual(history[0]["status"], "archived")
        self.assertTrue((self.root / "entries" / "memory_1" / "v1.md").exists())

    def test_07_one_corrupt_file_is_skipped_without_hiding_valid_memory(self) -> None:
        self._invoke(
            ToolCall("call_1", SAVE_MEMORY_TOOL, {"content": "Window preference.", "tags": ["travel"]}),
            effect="write",
        )
        self._invoke(
            ToolCall("call_2", SAVE_MEMORY_TOOL, {"content": "Dark mode preference.", "tags": ["software"]}),
            effect="write",
        )
        (self.root / "entries" / "memory_1" / "v1.md").write_text("tampered", encoding="utf-8")

        _, model = self._invoke(
            ToolCall("call_search", SEARCH_MEMORY_TOOL, {"query": "preference", "limit": 10}),
            effect="read",
            confirm=False,
        )

        items = model.inputs[-1].observations[-1].output["items"]
        self.assertEqual(tuple(item["memory_id"] for item in items), ("memory_2",))

    def test_08_non_explicit_conversation_cannot_trigger_memory_save(self) -> None:
        state, model = self._invoke(None, effect=None, confirm=False, select_memory=False)

        self.assertEqual(state["result"].status, RuntimeStatus.OK)
        self.assertEqual(len(model.inputs), 1)
        self.assertEqual(self.repository.list_all_index(), ())
        self.assertFalse(self.root.exists())

    def _invoke(
        self,
        call: ToolCall | None,
        *,
        effect: str | None,
        confirm: bool = True,
        select_memory: bool = True,
    ):
        self.run_number += 1
        request = RuntimeRequest(
            "explicit memory operation" if call else "ordinary conversation",
            "session_1",
            f"turn_{self.run_number}",
            f"run_{self.run_number}",
            "2026-07-16T00:00:00Z",
        )
        decisions = (
            [ToolActionDecision(call), FinalAnswerDecision("done")]
            if call is not None
            else [FinalAnswerDecision("chat only")]
        )
        model = FakeExecutorModelClient(decisions)
        executor = ReactExecutor(
            model,
            confirmation_provider=_Approver() if confirm else _DenyConfirmation(),
        )
        orchestrator = RuntimeOrchestrator(
            skill_service=SkillService(
                SkillRegistry(discover_skills(Path("app/skills"))),
                _SkillSelector(select_memory),
            ),
            intent_service=_Intent(effect),
            policy_service=_Policy(effect),
            execution_scope_factory=self._scope,
            executor=executor,
        )
        state = orchestrator.invoke(request)
        return state, model

    def _scope(self, request: RuntimeRequest, trace) -> ToolRuntime:
        service = MemoryService(
            self.repository,
            self.store,
            id_factory=self._new_memory_id,
            clock=lambda: "2026-07-16T00:00:00Z",
        )

        def context(call: ToolCall) -> MemoryWriteContext:
            return MemoryWriteContext(
                request.session_id,
                request.turn_id,
                request.run_id,
                call.call_id,
                f"confirmation://{request.run_id}/{call.call_id}",
                f"tool-evidence://{request.run_id}/{call.call_id}",
            )

        return ToolRuntime.from_registry(
            ToolRegistry(build_memory_tools(service, context, event_sink=trace))
        )

    def _new_memory_id(self) -> str:
        value = f"memory_{self.next_id}"
        self.next_id += 1
        return value

    def _assembler(self) -> ContextAssembler:
        repository = JsonlConversationRepository(self.conversations)
        return ContextAssembler(
            repository,
            RollingSummaryService(repository, FakeContextSummarizer(())),
            profile_provider=FileProfileProvider(self.root),
            memory_retriever=DeterministicMemoryRetriever(self.repository, self.store),
        )


class _SkillSelector:
    def __init__(self, selected: bool) -> None:
        self.selected = selected

    def select(self, request, skill_metadata):
        return {
            "selected_skill_ids": ["memory"] if self.selected else [],
            "reason": "deterministic E2E selection",
        }


class _Intent:
    def __init__(self, effect: str | None) -> None:
        self.effect = effect

    def classify(self, request):
        intent_type = (
            IntentType.WRITE_REQUEST
            if self.effect == "write"
            else IntentType.READ if self.effect == "read" else IntentType.CHAT
        )
        return IntentDecision(intent_type, 1.0, write_candidate=self.effect == "write")


class _Policy:
    def __init__(self, effect: str | None) -> None:
        self.effect = effect

    def evaluate(self, request, intent):
        return PolicyDecision(
            PolicyAction.ALLOW,
            allowed_effects=[self.effect] if self.effect else [],
        )


class _Approver:
    def confirm(self, run_id, call, definition):
        return ConfirmedAction.for_call(
            run_id,
            call,
            expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        )


class _DenyConfirmation:
    def confirm(self, run_id, call, definition):
        return None


def _query(text: str) -> ContextQuery:
    return ContextQuery(text, ContextQueryOrigin.CURRENT_USER_GOAL, "session_1", "run_1", "turn_1")


def _budget() -> ContextBudget:
    return ContextBudget(100, 8, 20, 30, 5, 30, 30)


if __name__ == "__main__":
    unittest.main()
