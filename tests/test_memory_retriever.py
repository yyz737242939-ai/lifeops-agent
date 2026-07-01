from pathlib import Path
import tempfile
import unittest

from app.memory.memory_retriever import MemoryRetriever
from app.memory.memory_store import SemanticMemoryStore


class MemoryRetrieverTests(unittest.TestCase):
    def test_retrieves_active_memory_by_keyword(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SemanticMemoryStore(Path(directory) / "semantic_memories.json")
            matched = store.save_memory(
                memory_type="preference",
                content="用户喜欢早上学习。",
                tags=["learning"],
            )
            store.save_memory(
                memory_type="constraint",
                content="晚上不安排高强度训练。",
                tags=["energy"],
            )
            retriever = MemoryRetriever(store)

            result = retriever.retrieve("今天怎么安排学习？")

        self.assertEqual([memory.item.id for memory in result], [matched.id])
        self.assertIn("keyword", result[0].reason)

    def test_retrieves_by_type_or_tag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SemanticMemoryStore(Path(directory) / "semantic_memories.json")
            goal = store.save_memory(
                memory_type="goal",
                content="长期目标是构建 LifeOps Agent。",
                tags=["project"],
            )
            constraint = store.save_memory(
                memory_type="constraint",
                content="晚上不安排高强度学习。",
                tags=["energy"],
            )
            retriever = MemoryRetriever(store)

            by_type = retriever.retrieve("我的目标是什么？")
            by_tag = retriever.retrieve("energy 相关约束")

        self.assertEqual([memory.item.id for memory in by_type], [goal.id])
        self.assertEqual([memory.item.id for memory in by_tag], [constraint.id])

    def test_deleted_memory_is_not_retrieved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SemanticMemoryStore(Path(directory) / "semantic_memories.json")
            memory = store.save_memory(
                memory_type="preference",
                content="用户喜欢早上学习。",
            )
            store.delete_memory(memory.id)
            retriever = MemoryRetriever(store)

            result = retriever.retrieve("怎么安排学习？")

        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
