import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.memory.memory_store import SemanticMemoryStore
from app.tools.capability_builder import build_capabilities
from app.tools.tool import call_tool


class MemoryToolTests(unittest.TestCase):
    def test_save_memory_tool_persists_only_when_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SemanticMemoryStore(Path(directory) / "semantic_memories.json")
            capability = build_capabilities(
                (),
                authorized_write_tool_names=frozenset({"save_memory"}),
            )

            with patch("app.tools.tool.memory_store", store):
                result = json.loads(
                    call_tool(
                        "save_memory",
                        {
                            "type": "preference",
                            "content": "用户希望解释代码时优先使用中文。",
                            "tags": ["learning"],
                        },
                        allowed_tool_names=capability.allowed_tool_names,
                    )
                )
                stored = store.list_memories()

        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "save_memory")
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].content, "用户希望解释代码时优先使用中文。")

    def test_denied_save_memory_does_not_persist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SemanticMemoryStore(Path(directory) / "semantic_memories.json")
            capability = build_capabilities(())

            with patch("app.tools.tool.memory_store", store):
                result = json.loads(
                    call_tool(
                        "save_memory",
                        {
                            "type": "preference",
                            "content": "用户喜欢早上学习。",
                        },
                        allowed_tool_names=capability.allowed_tool_names,
                    )
                )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "tool_not_allowed")
        self.assertEqual(store.list_memories(), [])

    def test_list_and_delete_memory_tools_use_active_items(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SemanticMemoryStore(Path(directory) / "semantic_memories.json")
            memory = store.save_memory(
                memory_type="goal",
                content="长期目标是构建 LifeOps Agent。",
                tags=["project"],
            )
            read_capability = build_capabilities(())
            delete_capability = build_capabilities(
                (),
                authorized_write_tool_names=frozenset({"delete_memory"}),
            )

            with patch("app.tools.tool.memory_store", store):
                listed_before = json.loads(
                    call_tool(
                        "list_memories",
                        {"tag": "project"},
                        allowed_tool_names=read_capability.allowed_tool_names,
                    )
                )
                deleted = json.loads(
                    call_tool(
                        "delete_memory",
                        {"memory_id": memory.id},
                        allowed_tool_names=delete_capability.allowed_tool_names,
                    )
                )
                listed_after = json.loads(
                    call_tool(
                        "list_memories",
                        {"tag": "project"},
                        allowed_tool_names=read_capability.allowed_tool_names,
                    )
                )

        self.assertEqual(len(listed_before["memories"]), 1)
        self.assertTrue(deleted["ok"])
        self.assertEqual(deleted["memory"]["status"], "deleted")
        self.assertEqual(listed_after["memories"], [])


if __name__ == "__main__":
    unittest.main()
