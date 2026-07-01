"""Formatting helpers for injecting Memory into model context."""

from typing import Any

from app.memory.memory_retriever import RetrievedMemory
from app.memory.profile_loader import ProfileMemory


PROFILE_CONTEXT_TITLE = "Long-term profile (read-only, user maintained)"
SEMANTIC_MEMORY_CONTEXT_TITLE = "Relevant saved memories"


def profile_context_message(profile: ProfileMemory) -> dict[str, str] | None:
    """Convert a loaded profile into a system message for this model request."""
    if not profile.loaded:
        return None
    return {
        "role": "system",
        "content": f"{PROFILE_CONTEXT_TITLE}:\n{profile.content}",
    }


def profile_context_report(
    profile: ProfileMemory,
    message: dict[str, str] | None,
    semantic_memories: list[RetrievedMemory] | None = None,
    semantic_message: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Diagnostic metadata for logs; avoids copying profile text into reports."""
    semantic_memories = semantic_memories or []
    semantic_context_chars = len(semantic_message["content"]) if semantic_message else 0
    return {
        "profile_loaded": profile.loaded,
        "profile_exists": profile.exists,
        "profile_path": profile.path,
        "profile_chars": profile.char_count,
        "profile_injected": message is not None,
        "semantic_memory_ids": [memory.item.id for memory in semantic_memories],
        "semantic_memory_count": len(semantic_memories),
        "semantic_memory_injected": semantic_message is not None,
        "semantic_memory_matches": [
            {
                "id": memory.item.id,
                "type": memory.item.type,
                "reason": memory.reason,
            }
            for memory in semantic_memories
        ],
        "memory_context_chars": (
            (len(message["content"]) if message else 0) + semantic_context_chars
        ),
    }


def semantic_memory_context_message(
    memories: list[RetrievedMemory],
) -> dict[str, str] | None:
    """Format retrieved Semantic Memory as request-local system context."""
    if not memories:
        return None

    lines = [f"{SEMANTIC_MEMORY_CONTEXT_TITLE}:"]
    for memory in memories:
        item = memory.item
        tag_text = f" tags={','.join(item.tags)}" if item.tags else ""
        lines.append(f"- [{item.id}] ({item.type}{tag_text}) {item.content}")
    return {"role": "system", "content": "\n".join(lines)}
