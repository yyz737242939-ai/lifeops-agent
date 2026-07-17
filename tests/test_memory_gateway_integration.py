from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.intent.models import IntentType
from app.intent.classifiers import RuleBasedIntentClassifier
from app.intent.service import IntentService
from app.memory.document_store import MemoryDocumentStore
from app.memory.models import MemoryWriteContext
from app.memory.repository import SqliteMemoryRepository
from app.memory.service import MemoryService
from app.memory.tools import SAVE_MEMORY_TOOL, SEARCH_MEMORY_TOOL, build_memory_tools
from app.policy.models import PolicyAction, PolicyDecision
from app.policy.service import PolicyService
from app.runtime.models import RuntimeRequest
from app.tools.authorization import resolve_allowed_tools
from app.tools.gateway import ToolGateway
from app.tools.models import AllowedToolSet, ConfirmedAction, ToolCall, ToolCallStatus
from app.tools.registry import ToolRegistry
from tests.helpers import create_test_connection


class MemoryGatewayIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "memory"
        self.conn = create_test_connection()
        self.repository = SqliteMemoryRepository(self.conn)
        service = MemoryService(
            self.repository,
            MemoryDocumentStore(self.root),
            id_factory=lambda: "memory_1",
            clock=lambda: "2026-07-16T00:00:00Z",
        )
        self.registry = ToolRegistry(
            build_memory_tools(service, self._write_context)
        )
        self.gateway = ToolGateway(self.registry)
        self.run_id = "run_1"

    def tearDown(self) -> None:
        self.conn.close()
        self.temporary.cleanup()

    def test_explicit_remember_intent_policy_and_skill_expose_only_memory_writes(self) -> None:
        request = RuntimeRequest(
            "请记住我喜欢靠窗座位",
            "session_1",
            "turn_1",
            "run_1",
            "2026-07-16T00:00:00Z",
        )
        intent = IntentService((RuleBasedIntentClassifier(),)).classify(request)
        policy = PolicyService().evaluate(request, intent)

        allowed = resolve_allowed_tools(("memory",), policy, self.registry)

        self.assertEqual(intent.intent_type, IntentType.WRITE_REQUEST)
        self.assertEqual(policy.action, PolicyAction.ALLOW)
        self.assertEqual(
            allowed.tool_names,
            ("memory.archive", "memory.save", "memory.update"),
        )

    def test_explicit_update_and_archive_keep_memory_write_catalog_available(self) -> None:
        for user_input in (
            "Call memory.update exactly once for this memory.",
            "Call memory.archive exactly once for this memory.",
        ):
            with self.subTest(user_input=user_input):
                request = RuntimeRequest(user_input, "session_1")
                intent = IntentService((RuleBasedIntentClassifier(),)).classify(request)
                policy = PolicyService().evaluate(request, intent)
                allowed = resolve_allowed_tools(("memory",), policy, self.registry)

                self.assertEqual(intent.intent_type, IntentType.WRITE_REQUEST)
                self.assertEqual(policy.action, PolicyAction.ALLOW)
                self.assertEqual(
                    allowed.tool_names,
                    ("memory.archive", "memory.save", "memory.update"),
                )

    def test_unselected_skill_policy_deny_and_missing_confirmation_are_zero_write(self) -> None:
        call = _save_call()
        write_policy = PolicyDecision(PolicyAction.ALLOW, allowed_effects=["write"])
        no_skill = resolve_allowed_tools((), write_policy, self.registry)

        denied = self.gateway.execute(call, no_skill, run_id=self.run_id)
        requires = self.gateway.execute(
            call,
            resolve_allowed_tools(("memory",), write_policy, self.registry),
            run_id=self.run_id,
        )

        self.assertEqual(denied.status, ToolCallStatus.DENIED)
        self.assertEqual(requires.status, ToolCallStatus.REQUIRES_CONFIRMATION)
        self.assertEqual(self.repository.list_all_index(), ())
        self.assertFalse(self.root.exists())

    def test_mismatch_expiry_and_argument_change_are_zero_write(self) -> None:
        call = _save_call()
        allowed = _write_allowed(self.registry)
        mismatched = ConfirmedAction.for_call(
            "other_run", call, expires_at="2099-01-01T00:00:00+00:00"
        )
        expired = ConfirmedAction.for_call(
            self.run_id, call, expires_at="2000-01-01T00:00:00+00:00"
        )
        changed = ToolCall(
            call.call_id,
            call.tool_name,
            {"content": "changed", "tags": ["travel"]},
        )
        exact_for_original = ConfirmedAction.for_call(
            self.run_id, call, expires_at="2099-01-01T00:00:00+00:00"
        )

        results = (
            self.gateway.execute(call, allowed, confirmation=mismatched, run_id=self.run_id),
            self.gateway.execute(call, allowed, confirmation=expired, run_id=self.run_id),
            self.gateway.execute(changed, allowed, confirmation=exact_for_original, run_id=self.run_id),
        )

        self.assertTrue(
            all(item.status == ToolCallStatus.REQUIRES_CONFIRMATION for item in results)
        )
        self.assertEqual(self.repository.list_all_index(), ())
        self.assertFalse(self.root.exists())

    def test_exact_confirmation_reaches_handler_and_evidence_matches_committed_state(self) -> None:
        call = _save_call()
        confirmation = ConfirmedAction.for_call(
            self.run_id,
            call,
            expires_at="2099-01-01T00:00:00+00:00",
        )

        result = self.gateway.execute(
            call,
            _write_allowed(self.registry),
            confirmation=confirmation,
            run_id=self.run_id,
        )

        self.assertEqual(result.status, ToolCallStatus.SUCCEEDED)
        self.assertEqual(result.output["memory_id"], "memory_1")
        self.assertEqual(len(result.evidence), 1)
        record = self.repository.get_version("memory_1", 1)
        self.assertEqual(record.source_run_id, self.run_id)
        self.assertEqual(record.source_tool_call_id, call.call_id)
        self.assertEqual(record.evidence_ref, result.evidence[0].reference)
        self.assertTrue((self.root / record.relative_path).exists())

    def test_read_tool_needs_policy_and_skill_but_no_confirmation(self) -> None:
        save = _save_call()
        self.gateway.execute(
            save,
            _write_allowed(self.registry),
            confirmation=ConfirmedAction.for_call(
                self.run_id, save, expires_at="2099-01-01T00:00:00+00:00"
            ),
            run_id=self.run_id,
        )
        read_allowed = resolve_allowed_tools(
            ("memory",),
            PolicyDecision(PolicyAction.ALLOW, allowed_effects=["read"]),
            self.registry,
        )

        result = self.gateway.execute(
            ToolCall("call_search", SEARCH_MEMORY_TOOL, {"query": "window"}),
            read_allowed,
            run_id=self.run_id,
        )

        self.assertEqual(result.status, ToolCallStatus.SUCCEEDED)
        self.assertEqual(result.output["items"][0]["memory_id"], "memory_1")

    def _write_context(self, call: ToolCall) -> MemoryWriteContext:
        return MemoryWriteContext(
            "session_1",
            "turn_1",
            self.run_id,
            call.call_id,
            f"confirmation://{self.run_id}/{call.call_id}",
            f"tool-evidence://{self.run_id}/{call.call_id}",
        )


def _save_call() -> ToolCall:
    return ToolCall(
        "call_save",
        SAVE_MEMORY_TOOL,
        {"content": "Prefers a window seat.", "tags": ["travel"]},
    )


def _write_allowed(registry: ToolRegistry) -> AllowedToolSet:
    return resolve_allowed_tools(
        ("memory",),
        PolicyDecision(PolicyAction.ALLOW, allowed_effects=["write"]),
        registry,
    )


if __name__ == "__main__":
    unittest.main()
