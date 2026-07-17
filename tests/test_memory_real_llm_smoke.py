from __future__ import annotations

import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.context.assembler import ContextAssembler
from app.context.models import ContextBudget, ContextQuery, ContextQueryOrigin
from app.context.repository import JsonlConversationRepository
from app.context.summarizer import FakeContextSummarizer
from app.context.summary_service import RollingSummaryService
from app.executor.model_adapter import OpenAIExecutorModelClient
from app.executor.models import ToolActionDecision
from app.executor.service import ReactExecutor
from app.intent.models import IntentDecision, IntentType
from app.memory.document_store import MemoryDocumentStore
from app.memory.models import MemoryStatus, MemoryWriteContext
from app.memory.profile import FileProfileProvider
from app.memory.repository import SqliteMemoryRepository
from app.memory.retriever import DeterministicMemoryRetriever
from app.memory.service import MemoryConflictError, MemoryService
from app.memory.tools import (
    ARCHIVE_MEMORY_TOOL,
    SAVE_MEMORY_TOOL,
    UPDATE_MEMORY_TOOL,
    build_memory_tools,
)
from app.policy.models import PolicyAction, PolicyDecision
from app.runtime.models import RuntimeRequest, RuntimeStatus
from app.runtime.service import RuntimeService
from app.skills.loader import discover_skills
from app.skills.registry import SkillRegistry
from app.skills.service import SkillService
from app.storage.migrations import migrate
from app.storage.sqlite import connect_sqlite
from app.tools.models import ConfirmedAction, ToolCall
from app.tools.registry import ToolRegistry
from app.tools.runtime import ToolRuntime


@unittest.skipUnless(
    os.environ.get("LIFEOPS_RUN_MEMORY_REAL_LLM_SMOKE") == "1",
    "Set LIFEOPS_RUN_MEMORY_REAL_LLM_SMOKE=1 to call the configured LLM.",
)
class MemoryRealLlmSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.memory_root = base / "memory"
        self.conversation_root = base / "conversations"
        self.database = base / "lifeops.db"
        self.conn = connect_sqlite(self.database)
        migrate(self.conn)
        self.repository = SqliteMemoryRepository(self.conn)
        self.store = MemoryDocumentStore(self.memory_root)
        self.services: list[RuntimeService] = []

    def tearDown(self) -> None:
        for service in self.services:
            service.close()
        self.conn.close()
        self.temporary.cleanup()

    def test_01_profile_read_is_read_only(self) -> None:
        marker = "PROFILE-CEDAR-7314"
        self.memory_root.mkdir(parents=True)
        (self.memory_root / "profile.md").write_text(
            f"My dietary profile token is {marker}; I avoid peanuts.",
            encoding="utf-8",
        )
        model = _CapturingRealModel()
        service = self._runtime(model, effect=None, confirmation=_DenyConfirmation())

        result = service.handle(self._request(
            "What exact dietary profile token do I have, and what food do I avoid?",
            "profile",
        ))

        self.assertEqual(
            result.status,
            RuntimeStatus.OK,
            msg=(
                f"error={result.error_code} tools={model.tool_names} "
                f"observations={_observation_debug(model)}"
            ),
        )
        self.assertIn(marker, result.message)
        self.assertTrue(any(
            marker in item.content
            for model_input in model.inputs
            for item in (
                model_input.context_contributions
                + model_input.memory_contributions
            )
        ))
        self.assertEqual(model.tool_names, ())
        self.assertEqual(self.repository.list_all_index(), ())

    def test_02_explicit_save_has_zero_write_before_confirmation(self) -> None:
        marker = "SAVE-AMBER-4821"
        prompt = (
            "Remember exactly one long-term Memory by making exactly one memory.save "
            "call. Use this entire quoted sentence as its content: "
            f"\"{marker}; my preferred focus time is 07:30.\" "
            "After the first successful Tool Observation, answer immediately and do "
            "not call memory.save again."
        )
        denied_model = _CapturingRealModel()
        denied_confirmation = _DenyConfirmation()
        denied = self._runtime(
            denied_model,
            effect="write",
            confirmation=denied_confirmation,
            tool_names=(SAVE_MEMORY_TOOL,),
        ).handle(self._request(prompt, "save_denied"))

        self.assertNotEqual(denied.status, RuntimeStatus.OK)
        self.assertEqual(denied_model.tool_names, (SAVE_MEMORY_TOOL,))
        self.assertEqual(denied_confirmation.calls, 1)
        self.assertEqual(self.repository.list_all_index(), ())
        self.assertFalse((self.memory_root / "entries").exists())

        approved_model = _CapturingRealModel()
        approved_confirmation = _Approver(SAVE_MEMORY_TOOL)
        approved = self._runtime(
            approved_model,
            effect="write",
            confirmation=approved_confirmation,
            tool_names=(SAVE_MEMORY_TOOL,),
        ).handle(self._request(prompt, "save_approved"))

        self.assertEqual(approved.status, RuntimeStatus.OK, approved.error_code)
        self.assertEqual(approved_model.tool_names, (SAVE_MEMORY_TOOL,))
        self.assertEqual(approved_confirmation.calls, 1)
        records = self.repository.list_all_index()
        self.assertEqual(len(records), 1)
        self.assertTrue((self.memory_root / records[0].relative_path).exists())
        observation = approved_model.inputs[-1].observations[-1]
        self.assertEqual(records[0].evidence_ref, observation.evidence[0].reference)

    def test_03_restart_retrieval_uses_verified_memory(self) -> None:
        marker = "RESTART-NOVA-6142"
        self._memory_service().save_confirmed(
            f"My saved seating preference is window seat. Durable code: {marker}.",
            ("travel",),
            _seed_context("restart"),
        )
        self._restart_storage()
        model = _CapturingRealModel()
        service = self._runtime(model, effect=None, confirmation=_DenyConfirmation())

        result = service.handle(self._request(
            "What is my saved seating preference? Include its exact durable code.",
            "restart",
        ))

        self.assertEqual(result.status, RuntimeStatus.OK, result.error_code)
        self.assertIn(marker, result.message)
        self.assertNotIn(marker, model.inputs[0].request.user_input)
        self.assertTrue(any(
            marker in item.content
            for item in model.inputs[0].memory_contributions
        ))
        self.assertEqual(model.tool_names, ())

    def test_04_conflict_is_followed_by_confirmed_update(self) -> None:
        initial = self._memory_service().save_confirmed(
            "My durable travel seat preference is window seat.",
            ("travel-seat",),
            _seed_context("conflict"),
        ).entry.record
        marker = "AISLE-UPDATE-9054"
        with self.assertRaises(MemoryConflictError) as caught:
            self._memory_service().save_confirmed(
                f"My durable travel seat preference is aisle seat, code {marker}.",
                ("travel-seat",),
                _seed_context("conflict_candidate"),
            )
        candidate = caught.exception.candidates[0]
        self.assertEqual(candidate.memory_id, initial.memory_id)
        self.assertEqual(candidate.version, initial.version)
        self.assertEqual(len(self.repository.list_versions(initial.memory_id)), 1)

        conflict_model = _CapturingRealModel()
        conflict_result = self._runtime(
            conflict_model,
            effect=None,
            confirmation=_DenyConfirmation(),
        ).handle(self._request(
            "The verified Memory service found a non-retryable conflict candidate: "
            f"Memory ID {candidate.memory_id}, version {candidate.version}, reason "
            f"{candidate.reason}. Explain the conflict and ask whether I want to update "
            "that exact version. Do not claim an update occurred.",
            "conflict_preview",
        ))

        self.assertEqual(
            conflict_result.status,
            RuntimeStatus.OK,
            msg=(
                f"error={conflict_result.error_code} tools={conflict_model.tool_names} "
                f"observations={_observation_debug(conflict_model)}"
            ),
        )
        self.assertEqual(conflict_model.tool_names, ())
        self.assertIn(initial.memory_id, conflict_result.message)
        self.assertIn(str(initial.version), conflict_result.message)
        self.assertEqual(len(self.repository.list_versions(initial.memory_id)), 1)

        update_model = _CapturingRealModel()
        update_confirmation = _Approver(UPDATE_MEMORY_TOOL)
        update_result = self._runtime(
            update_model,
            effect="write",
            confirmation=update_confirmation,
            tool_names=(UPDATE_MEMORY_TOOL,),
        ).handle(self._request(
            f"I explicitly authorize updating Memory ID {initial.memory_id}, expected "
            f"version {initial.version}. Make exactly one memory.update call. Set its "
            "content to this entire sentence: "
            f"\"My durable travel seat preference is aisle seat, code {marker}.\" "
            "Use tag travel-seat. After the successful update observation, answer "
            "immediately without another Memory ToolCall.",
            "conflict_update",
        ))

        self.assertEqual(
            update_result.status,
            RuntimeStatus.OK,
            msg=(
                f"error={update_result.error_code} tools={update_model.tool_names} "
                f"unexpected={update_confirmation.unexpected_tools} "
                f"observations={_observation_debug(update_model)}"
            ),
        )
        self.assertIn(
            update_model.tool_names,
            ((UPDATE_MEMORY_TOOL,), (UPDATE_MEMORY_TOOL, UPDATE_MEMORY_TOOL)),
        )
        self.assertEqual(update_confirmation.calls, len(update_model.tool_names))
        if len(update_model.tool_names) == 2:
            observations = _unique_observations(update_model)
            self.assertEqual(
                tuple(item.status.value for item in observations),
                ("succeeded", "failed"),
            )
            self.assertEqual(
                observations[-1].error.code,
                "memory_version_conflict",
            )
        versions = self.repository.list_versions(initial.memory_id)
        self.assertEqual(
            tuple(item.status for item in versions),
            (MemoryStatus.SUPERSEDED, MemoryStatus.ACTIVE),
        )
        self.assertEqual(versions[-1].version, 2)
        active = self._memory_service().list_active()
        self.assertEqual(len(active), 1)
        self.assertIn(marker, active[0].document.content)
        assembly = self._assembler().assemble(
            _query("travel seat preference", "verify_conflict"),
            _budget(),
        )
        memory_text = " ".join(item.content for item in assembly.contributions)
        self.assertIn(marker, memory_text)
        self.assertNotIn("window seat", memory_text)

    def test_05_archive_survives_restart_and_keeps_history(self) -> None:
        marker = "ARCHIVE-ORBIT-3371"
        record = self._memory_service().save_confirmed(
            f"Temporary project preference with archive code {marker}.",
            ("project-archive",),
            _seed_context("archive"),
        ).entry.record
        model = _CapturingRealModel()
        confirmation = _Approver(ARCHIVE_MEMORY_TOOL)
        service = self._runtime(
            model,
            effect="write",
            confirmation=confirmation,
            tool_names=(ARCHIVE_MEMORY_TOOL,),
        )

        result = service.handle(self._request(
            f"Archive long-term memory ID {record.memory_id}, expected version "
            f"{record.version}. This is an explicit archive request.",
            "archive",
        ))

        self.assertEqual(result.status, RuntimeStatus.OK, result.error_code)
        self.assertEqual(model.tool_names, (ARCHIVE_MEMORY_TOOL,))
        self.assertEqual(confirmation.calls, 1)
        self._restart_storage()
        self.assertEqual(
            self._memory_service().search("project preference", 5),
            (),
        )
        archived = self._memory_service().list_archived()
        history = self._memory_service().list_history(record.memory_id)
        self.assertEqual(len(archived), 1)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].record.status, MemoryStatus.ARCHIVED)
        self.assertTrue((self.memory_root / record.relative_path).exists())

    def _runtime(
        self,
        model,
        *,
        effect: str | None,
        confirmation,
        tool_names: tuple[str, ...] | None = None,
    ) -> RuntimeService:
        executor = ReactExecutor(model, confirmation_provider=confirmation)

        def scope(request: RuntimeRequest, trace) -> ToolRuntime:
            memory = self._memory_service()

            def write_context(call: ToolCall) -> MemoryWriteContext:
                return MemoryWriteContext(
                    request.session_id,
                    request.turn_id,
                    request.run_id,
                    call.call_id,
                    f"confirmation://{request.run_id}/{call.call_id}",
                    f"tool-evidence://{request.run_id}/{call.call_id}",
                )

            tools = build_memory_tools(memory, write_context, event_sink=trace)
            if tool_names is not None:
                tools = tuple(item for item in tools if item[0].name in tool_names)
            return ToolRuntime.from_registry(ToolRegistry(tools))

        service = RuntimeService(
            SkillService(
                SkillRegistry(discover_skills(Path("app/skills"))),
                _MemorySkillSelector(),
            ),
            intent_service=_Intent(effect),
            policy_service=_Policy(effect),
            execution_scope_factory=scope,
            executor=executor,
            conversation_repository=JsonlConversationRepository(self.conversation_root),
            context_assembler=self._assembler(),
            context_budget=_budget(),
        )
        self.services.append(service)
        return service

    def _assembler(self) -> ContextAssembler:
        conversations = JsonlConversationRepository(self.conversation_root)
        return ContextAssembler(
            conversations,
            RollingSummaryService(conversations, FakeContextSummarizer(())),
            profile_provider=FileProfileProvider(self.memory_root),
            memory_retriever=DeterministicMemoryRetriever(self.repository, self.store),
        )

    def _memory_service(self) -> MemoryService:
        return MemoryService(self.repository, self.store)

    def _restart_storage(self) -> None:
        self.conn.close()
        self.conn = connect_sqlite(self.database)
        migrate(self.conn)
        self.repository = SqliteMemoryRepository(self.conn)
        self.store = MemoryDocumentStore(self.memory_root)

    @staticmethod
    def _request(text: str, suffix: str) -> RuntimeRequest:
        return RuntimeRequest(
            text,
            f"session_memory_real_{suffix}",
            f"turn_memory_real_{suffix}",
            f"run_memory_real_{suffix}",
        )


class _CapturingRealModel:
    def __init__(self) -> None:
        self.delegate = OpenAIExecutorModelClient()
        self.inputs = []
        self.decisions = []

    def decide(self, model_input, *, llm_log=None):
        self.inputs.append(model_input)
        decision = self.delegate.decide(model_input, llm_log=llm_log)
        self.decisions.append(decision)
        return decision

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(
            decision.call.tool_name
            for decision in self.decisions
            if isinstance(decision, ToolActionDecision)
        )


class _MemorySkillSelector:
    def select(self, request, skill_metadata, *, llm_log=None):
        return {"selected_skill_ids": ["memory"], "reason": "memory real LLM smoke"}


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
    def __init__(self, expected_tool_name: str) -> None:
        self.expected_tool_name = expected_tool_name
        self.calls = 0
        self.unexpected_tools = []

    def confirm(self, run_id, call, definition):
        self.calls += 1
        if call.tool_name != self.expected_tool_name:
            self.unexpected_tools.append(call.tool_name)
            return None
        return ConfirmedAction.for_call(
            run_id,
            call,
            expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        )


class _DenyConfirmation:
    def __init__(self) -> None:
        self.calls = 0

    def confirm(self, run_id, call, definition):
        self.calls += 1
        return None


def _seed_context(suffix: str) -> MemoryWriteContext:
    return MemoryWriteContext(
        f"seed_session_{suffix}",
        f"seed_turn_{suffix}",
        f"seed_run_{suffix}",
        f"seed_call_{suffix}",
        f"confirmation://seed/{suffix}",
        f"tool-evidence://seed/{suffix}",
    )


def _query(text: str, suffix: str) -> ContextQuery:
    return ContextQuery(
        text,
        ContextQueryOrigin.CURRENT_USER_GOAL,
        f"session_{suffix}",
        f"run_{suffix}",
        f"turn_{suffix}",
    )


def _budget() -> ContextBudget:
    return ContextBudget(
        max_total_tokens=800,
        max_recent_turns=8,
        max_summary_tokens=100,
        max_profile_tokens=150,
        max_memory_items=5,
        max_memory_tokens=300,
        max_current_input_tokens=300,
    )


def _observation_debug(model: _CapturingRealModel) -> tuple[tuple[str, str, str | None], ...]:
    return tuple(
        (
            item.tool_name,
            item.status.value,
            item.error.code if item.error is not None else None,
        )
        for item in _unique_observations(model)
    )


def _unique_observations(model: _CapturingRealModel):
    seen = set()
    rows = []
    for model_input in model.inputs:
        for item in model_input.observations:
            key = (item.call_id, item.tool_name)
            if key in seen:
                continue
            seen.add(key)
            rows.append(item)
    return tuple(rows)


if __name__ == "__main__":
    unittest.main()
