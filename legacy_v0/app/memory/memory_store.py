"""Persistent Semantic Memory store."""

from pathlib import Path

from app.memory.memory_types import MemoryItem, MemoryType
from app.utils.json_file import load_model_list, save_model_list
from app.utils.time import now_iso, timestamp_id


DATA_DIR = Path(__file__).resolve().parents[2] / "data"
MEMORY_DIR = DATA_DIR / "memory"
SEMANTIC_MEMORIES_FILE = MEMORY_DIR / "semantic_memories.json"


class SemanticMemoryStore:
    """JSON-backed store for user-authorized semantic memories."""

    def __init__(self, path: str | Path = SEMANTIC_MEMORIES_FILE) -> None:
        self.path = Path(path)

    def save_memory(
        self,
        *,
        memory_type: MemoryType,
        content: str,
        tags: list[str] | None = None,
    ) -> MemoryItem:
        memories = self._load()
        memory = MemoryItem(
            id=self._next_id(),
            type=memory_type,
            content=content,
            tags=tags or [],
        )
        memories.append(memory)
        self._save(memories)
        return memory

    def list_memories(
        self,
        *,
        memory_type: MemoryType | None = None,
        tag: str | None = None,
        include_deleted: bool = False,
    ) -> list[MemoryItem]:
        memories = self._load()
        normalized_tag = tag.strip().lower() if tag else None
        result: list[MemoryItem] = []

        for memory in memories:
            if not include_deleted and memory.status != "active":
                continue
            if memory_type is not None and memory.type != memory_type:
                continue
            if normalized_tag is not None and normalized_tag not in memory.tags:
                continue
            result.append(memory)

        return result

    def delete_memory(self, memory_id: str) -> MemoryItem | None:
        memories = self._load()
        for index, memory in enumerate(memories):
            if memory.id != memory_id:
                continue
            if memory.status == "deleted":
                return memory

            updated = memory.model_copy(
                update={"status": "deleted", "updated_at": now_iso()}
            )
            memories[index] = updated
            self._save(memories)
            return updated
        return None

    def _load(self) -> list[MemoryItem]:
        return load_model_list(self.path, MemoryItem)

    def _save(self, memories: list[MemoryItem]) -> None:
        save_model_list(self.path, memories)

    @staticmethod
    def _next_id() -> str:
        return f"mem_{timestamp_id()}"
