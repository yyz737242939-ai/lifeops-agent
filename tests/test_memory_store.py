from pathlib import Path
import tempfile
import unittest

from app.memory.memory_store import SemanticMemoryStore


class SemanticMemoryStoreTests(unittest.TestCase):
    def test_save_memory_persists_user_authorized_item(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SemanticMemoryStore(Path(directory) / "semantic_memories.json")

            memory = store.save_memory(
                memory_type="preference",
                content="用户希望解释代码时优先使用中文。",
                tags=["Learning", "learning", "  code  ", ""],
            )
            stored = store.list_memories()

        self.assertTrue(memory.id.startswith("mem_"))
        self.assertEqual(memory.source, "user_authorized")
        self.assertEqual(memory.status, "active")
        self.assertEqual(memory.tags, ["learning", "code"])
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].content, "用户希望解释代码时优先使用中文。")

    def test_list_memories_filters_by_type_and_tag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SemanticMemoryStore(Path(directory) / "semantic_memories.json")
            store.save_memory(
                memory_type="preference",
                content="用户喜欢中文解释。",
                tags=["learning"],
            )
            store.save_memory(
                memory_type="constraint",
                content="晚上不安排高强度学习。",
                tags=["energy"],
            )

            by_type = store.list_memories(memory_type="constraint")
            by_tag = store.list_memories(tag="LEARNING")

        self.assertEqual([memory.content for memory in by_type], ["晚上不安排高强度学习。"])
        self.assertEqual([memory.content for memory in by_tag], ["用户喜欢中文解释。"])

    def test_delete_memory_soft_deletes_and_hides_active_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SemanticMemoryStore(Path(directory) / "semantic_memories.json")
            memory = store.save_memory(
                memory_type="goal",
                content="长期目标是构建 LifeOps Agent。",
            )

            deleted = store.delete_memory(memory.id)
            active = store.list_memories()
            all_memories = store.list_memories(include_deleted=True)

        self.assertIsNotNone(deleted)
        assert deleted is not None
        self.assertEqual(deleted.status, "deleted")
        self.assertIsNotNone(deleted.updated_at)
        self.assertEqual(active, [])
        self.assertEqual(len(all_memories), 1)
        self.assertEqual(all_memories[0].status, "deleted")

    def test_delete_missing_memory_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SemanticMemoryStore(Path(directory) / "semantic_memories.json")

            deleted = store.delete_memory("mem_missing")

        self.assertIsNone(deleted)


if __name__ == "__main__":
    unittest.main()
