"""Shared types for Profile and Semantic Memory."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.utils.time import now_iso


MemoryType = Literal["fact", "preference", "goal", "constraint"]
MemoryStatus = Literal["active", "deleted"]
MemorySource = Literal["user_authorized"]


class MemoryItem(BaseModel):
    """Persisted long-term semantic memory authorized by the user."""

    id: str
    type: MemoryType
    content: str
    source: MemorySource = "user_authorized"
    created_at: str = Field(default_factory=now_iso)
    updated_at: str | None = None
    status: MemoryStatus = "active"
    tags: list[str] = Field(default_factory=list)

    @field_validator("id", "content")
    @classmethod
    def text_must_not_be_empty(cls, value: str) -> str:
        clean_value = value.strip()
        if not clean_value:
            raise ValueError("Memory id and content cannot be empty")
        return clean_value

    @field_validator("tags")
    @classmethod
    def tags_must_be_normalized(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for tag in value:
            clean_tag = tag.strip().lower()
            if not clean_tag or clean_tag in seen:
                continue
            normalized.append(clean_tag)
            seen.add(clean_tag)
        return normalized
