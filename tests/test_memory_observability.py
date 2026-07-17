from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.memory.document_store import MemoryDocumentStore
from app.memory.models import MemoryWriteContext
from app.memory.repository import SqliteMemoryRepository
from app.memory.service import MemoryService
from app.memory.tools import SAVE_MEMORY_TOOL, build_memory_tools
from app.tools.gateway import ToolGateway
from app.tools.models import AllowedToolSet, ConfirmedAction, ToolCall, ToolCallStatus
from app.tools.registry import ToolRegistry
from tests.helpers import create_test_connection


class MemoryObservabilityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "memory"
        self.conn = create_test_connection()
        self.trace = _Trace()
        self.repository = SqliteMemoryRepository(self.conn)
        service = MemoryService(
            self.repository,
            MemoryDocumentStore(self.root),
            id_factory=lambda: "memory_1",
            clock=lambda: "2026-07-16T00:00:00Z",
        )

        def context(call: ToolCall) -> MemoryWriteContext:
            return MemoryWriteContext(
                "session_secret",
                "turn_secret",
                "run_1",
                call.call_id,
                "confirmation_secret_ref",
                "evidence_secret_ref",
            )

        self.registry = ToolRegistry(
            build_memory_tools(service, context, event_sink=self.trace)
        )
        self.gateway = ToolGateway(self.registry)

    def tearDown(self) -> None:
        self.conn.close()
        self.temporary.cleanup()

    def test_success_event_contains_only_safe_identity_lifecycle_and_counts(self) -> None:
        secret = "SECRET_MEMORY_CONTENT"
        call = ToolCall(
            "call_1",
            SAVE_MEMORY_TOOL,
            {"content": secret, "tags": ["SECRET_TAG"]},
        )

        result = self.gateway.execute(
            call,
            AllowedToolSet((SAVE_MEMORY_TOOL,)),
            confirmation=ConfirmedAction.for_call(
                "run_1", call, expires_at="2099-01-01T00:00:00+00:00"
            ),
            run_id="run_1",
            trace=self.trace,
        )

        self.assertEqual(result.status, ToolCallStatus.SUCCEEDED)
        event = next(item for item in self.trace.events if item[0] == "memory.tool.completed")
        self.assertEqual(
            set(event[1]),
            {
                "tool_name",
                "call_id",
                "status",
                "evidence_count",
                "memory_id",
                "version",
                "idempotent_existing",
            },
        )
        serialized = repr(self.trace.events)
        for forbidden in (
            secret,
            "SECRET_TAG",
            "session_secret",
            "turn_secret",
            "confirmation_secret_ref",
            "evidence_secret_ref",
            "entries/memory_1/v1.md",
            "arguments_digest",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_failed_event_records_safe_code_without_content_or_candidates(self) -> None:
        first = ToolCall("call_1", SAVE_MEMORY_TOOL, {"content": "first", "tags": ["shared"]})
        self._confirmed(first)
        conflict_secret = "SECRET_CONFLICT_CONTENT"
        second = ToolCall(
            "call_2",
            SAVE_MEMORY_TOOL,
            {"content": conflict_secret, "tags": ["shared"]},
        )

        result = self._confirmed(second)

        self.assertEqual(result.status, ToolCallStatus.FAILED)
        event = [item for item in self.trace.events if item[0] == "memory.tool.failed"][-1]
        self.assertEqual(
            set(event[1]),
            {"tool_name", "call_id", "status", "evidence_count", "error_code"},
        )
        self.assertNotIn(conflict_secret, repr(event))
        self.assertNotIn("first", repr(event))

    def _confirmed(self, call: ToolCall):
        return self.gateway.execute(
            call,
            AllowedToolSet((SAVE_MEMORY_TOOL,)),
            confirmation=ConfirmedAction.for_call(
                "run_1", call, expires_at="2099-01-01T00:00:00+00:00"
            ),
            run_id="run_1",
            trace=self.trace,
        )


class _Trace:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def append(self, event_type: str, payload=None) -> None:
        self.events.append((event_type, payload or {}))


if __name__ == "__main__":
    unittest.main()
