from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.memory.document_store import MemoryDocumentStore
from app.memory.models import MemoryWriteContext
from app.memory.repository import SqliteMemoryRepository
from app.memory.service import MemoryService
from app.memory.tools import (
    ARCHIVE_MEMORY_TOOL,
    LIST_MEMORY_TOOL,
    SAVE_MEMORY_TOOL,
    SEARCH_MEMORY_TOOL,
    UPDATE_MEMORY_TOOL,
    build_memory_tools,
)
from app.skills.loader import discover_skills
from app.tools.models import ToolCall, ToolCallStatus, ToolEffect
from app.tools.registry import ToolRegistry
from tests.helpers import create_test_connection


class MemoryToolsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "memory"
        self.conn = create_test_connection()
        repository = SqliteMemoryRepository(self.conn)
        service = MemoryService(
            repository,
            MemoryDocumentStore(self.root),
            id_factory=lambda: "memory_1",
            clock=lambda: "2026-07-16T00:00:00Z",
        )
        self.context_calls: list[ToolCall] = []

        def context_factory(call: ToolCall) -> MemoryWriteContext:
            self.context_calls.append(call)
            return MemoryWriteContext(
                "session_1",
                "turn_1",
                "run_1",
                call.call_id,
                f"confirmation_{call.call_id}",
                f"evidence_{call.call_id}",
            )

        self.registry = ToolRegistry(build_memory_tools(service, context_factory))

    def tearDown(self) -> None:
        self.conn.close()
        self.temporary.cleanup()

    def test_memory_skill_is_discoverable_with_candidate_only_boundaries(self) -> None:
        skill_root = Path(__file__).resolve().parents[1] / "app" / "skills"

        skills = {skill.skill_id: skill for skill in discover_skills(skill_root)}

        self.assertIn("memory", skills)
        body = (skill_root / "memory" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("never authorizes Tools", body)
        self.assertIn("Never save conversation", body)
        self.assertIn("do not retry `memory.save`", body)
        self.assertIn("After any successful Memory WRITE observation", body)

    def test_exact_five_tool_contracts_have_fixed_scope_and_no_path_surface(self) -> None:
        definitions = self.registry.list_definitions()

        self.assertEqual(
            tuple(item.name for item in definitions),
            (
                ARCHIVE_MEMORY_TOOL,
                LIST_MEMORY_TOOL,
                SAVE_MEMORY_TOOL,
                SEARCH_MEMORY_TOOL,
                UPDATE_MEMORY_TOOL,
            ),
        )
        effects = {item.name: item.effect for item in definitions}
        save_definition = next(item for item in definitions if item.name == SAVE_MEMORY_TOOL)
        self.assertIn("at most once per user request", save_definition.description)
        self.assertIn("do not call memory.save again", save_definition.description)
        self.assertEqual(effects[SAVE_MEMORY_TOOL], ToolEffect.WRITE)
        self.assertEqual(effects[UPDATE_MEMORY_TOOL], ToolEffect.WRITE)
        self.assertEqual(effects[ARCHIVE_MEMORY_TOOL], ToolEffect.WRITE)
        self.assertEqual(effects[SEARCH_MEMORY_TOOL], ToolEffect.READ)
        self.assertEqual(effects[LIST_MEMORY_TOOL], ToolEffect.READ)
        for definition in definitions:
            self.assertEqual(definition.skill_ids, ("memory",))
            properties = definition.input_schema.get("properties", {})
            self.assertTrue(
                {"path", "relative_path", "scope", "user_id", "session_id"}.isdisjoint(
                    properties
                )
            )

    def test_all_handlers_delegate_lifecycle_to_memory_service(self) -> None:
        save = self._call(
            SAVE_MEMORY_TOOL,
            {"content": "Prefers a window seat.", "tags": ["travel"]},
            "call_save",
        )
        search = self._call(
            SEARCH_MEMORY_TOOL,
            {"query": "window seat", "limit": 5},
            "call_search",
        )
        listed = self._call(
            LIST_MEMORY_TOOL,
            {"mode": "active", "limit": 20},
            "call_list",
        )
        update = self._call(
            UPDATE_MEMORY_TOOL,
            {
                "memory_id": "memory_1",
                "expected_version": 1,
                "content": "Prefers an aisle seat.",
                "tags": ["travel"],
            },
            "call_update",
        )
        history = self._call(
            LIST_MEMORY_TOOL,
            {"mode": "history", "memory_id": "memory_1", "limit": 20},
            "call_history",
        )
        archive = self._call(
            ARCHIVE_MEMORY_TOOL,
            {"memory_id": "memory_1", "expected_version": 2},
            "call_archive",
        )

        for result in (save, search, listed, update, history, archive):
            self.assertEqual(result.status, ToolCallStatus.SUCCEEDED)
        self.assertEqual(save.output["version"], 1)
        self.assertEqual(search.output["items"][0]["memory_id"], "memory_1")
        self.assertEqual(listed.output["items"][0]["status"], "active")
        self.assertEqual(update.output["version"], 2)
        self.assertEqual(len(history.output["items"]), 2)
        self.assertEqual(archive.output["status"], "archived")
        self.assertEqual(
            tuple(call.call_id for call in self.context_calls),
            ("call_save", "call_update", "call_archive"),
        )
        self.assertTrue(save.evidence)
        self.assertTrue(update.evidence)
        self.assertTrue(archive.evidence)
        self.assertFalse(search.evidence)
        self.assertFalse(listed.evidence)

    def _call(self, name: str, arguments: dict[str, object], call_id: str):
        call = ToolCall(call_id, name, arguments)
        return self.registry.resolve(name).handler(call)


if __name__ == "__main__":
    unittest.main()
