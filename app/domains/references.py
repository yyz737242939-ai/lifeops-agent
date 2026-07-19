"""Shared stable references between LifeOps business domains."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.common.validation import require_non_empty_string


@dataclass(frozen=True)
class KnowledgeReference:
    reference_id: str
    domain: str
    item_kind: str
    item_id: str

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            require_non_empty_string(getattr(self, field_name), field_name)


@dataclass(frozen=True)
class KnowledgeReferenceResolution:
    reference: KnowledgeReference
    status: str
    title: str | None = None
    summary: str | None = None
    provenance: str | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.reference, KnowledgeReference):
            raise ValueError("reference must be a KnowledgeReference.")
        if self.status not in {"resolved", "unavailable"}:
            raise ValueError("status must be resolved or unavailable.")
        optional_values = (self.title, self.summary, self.provenance, self.error_code)
        for value in optional_values:
            if value is not None:
                require_non_empty_string(value, "resolution value")
        if self.status == "resolved" and (
            self.title is None or self.summary is None or self.provenance is None
        ):
            raise ValueError("resolved references require title, summary, and provenance.")
        if self.status == "resolved" and self.error_code is not None:
            raise ValueError("resolved references cannot contain error_code.")
        if self.status == "unavailable" and self.error_code is None:
            raise ValueError("unavailable references require error_code.")
        if self.status == "unavailable" and any(
            value is not None for value in (self.title, self.summary, self.provenance)
        ):
            raise ValueError("unavailable references cannot contain resolved content.")


class KnowledgeReferenceResolutionError(Exception):
    def __init__(self, code: str) -> None:
        require_non_empty_string(code, "code")
        self.code = code
        super().__init__("Knowledge reference could not be resolved.")


class KnowledgeReferenceResolver(Protocol):
    def resolve(self, reference: KnowledgeReference) -> KnowledgeReferenceResolution:
        ...
