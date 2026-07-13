"""Research domain models for temporary inputs and saved knowledge facts."""

from __future__ import annotations

from dataclasses import dataclass

from app.common.validation import require_non_empty_string


RESEARCH_ITEM_KINDS = frozenset({"topic", "source", "note", "brief"})


def _require_research_item_kind(value: str, field_name: str) -> None:
    require_non_empty_string(value, field_name)
    if value not in RESEARCH_ITEM_KINDS:
        raise ValueError(
            f"{field_name} must be one of: {', '.join(sorted(RESEARCH_ITEM_KINDS))}."
        )


@dataclass(frozen=True)
class ExternalObservation:
    observation_id: str
    source_key: str
    title: str
    url: str
    summary: str
    content_hash: str
    fetched_at: str
    provenance: str
    source_type: str = "web_page"
    published_at: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "observation_id",
            "source_key",
            "title",
            "url",
            "summary",
            "content_hash",
            "fetched_at",
            "provenance",
            "source_type",
        ):
            require_non_empty_string(getattr(self, field_name), field_name)
        if self.published_at is not None:
            require_non_empty_string(self.published_at, "published_at")


@dataclass(frozen=True)
class FetchedSourceDocument:
    document_id: str
    observation_id: str
    source_key: str
    title: str
    url: str
    content_type: str
    content: str
    content_hash: str
    fetched_at: str
    provenance: str
    source_type: str = "web_page"
    published_at: str | None = None

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            value = getattr(self, field_name)
            if field_name == "published_at" and value is None:
                continue
            require_non_empty_string(value, field_name)


@dataclass(frozen=True)
class ResearchItem:
    item_id: str
    source_key: str
    title: str
    url: str
    raw_position: int
    topic_hint: str | None = None
    score: int | None = None

    def __post_init__(self) -> None:
        for field_name in ("item_id", "source_key", "title", "url"):
            require_non_empty_string(getattr(self, field_name), field_name)
        if (
            not isinstance(self.raw_position, int)
            or isinstance(self.raw_position, bool)
            or self.raw_position < 1
        ):
            raise ValueError("raw_position must be a positive integer.")
        if self.topic_hint is not None:
            require_non_empty_string(self.topic_hint, "topic_hint")
        if self.score is not None and (
            not isinstance(self.score, int) or isinstance(self.score, bool)
        ):
            raise ValueError("score must be an integer or None.")


@dataclass(frozen=True)
class ResearchItemSet:
    item_set_id: str
    document_ids: tuple[str, ...]
    items: tuple[ResearchItem, ...]
    created_at: str

    def __post_init__(self) -> None:
        require_non_empty_string(self.item_set_id, "item_set_id")
        require_non_empty_string(self.created_at, "created_at")
        if not isinstance(self.document_ids, tuple) or not self.document_ids:
            raise ValueError("document_ids must be a non-empty tuple.")
        for document_id in self.document_ids:
            require_non_empty_string(document_id, "document_ids")
        if len(set(self.document_ids)) != len(self.document_ids):
            raise ValueError("document_ids must not contain duplicates.")
        if not isinstance(self.items, tuple) or not self.items:
            raise ValueError("items must be a non-empty tuple.")
        if any(not isinstance(item, ResearchItem) for item in self.items):
            raise ValueError("items must contain ResearchItem values.")


@dataclass(frozen=True)
class ResearchSource:
    source_id: str
    source_key: str
    title: str
    url: str
    source_type: str
    created_at: str

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            require_non_empty_string(getattr(self, field_name), field_name)


@dataclass(frozen=True)
class ResearchSourceSnapshot:
    snapshot_id: str
    source_id: str
    summary: str
    content_hash: str
    fetched_at: str
    published_at: str | None
    provenance: str
    created_at: str

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            value = getattr(self, field_name)
            if field_name == "published_at" and value is None:
                continue
            require_non_empty_string(value, field_name)


@dataclass(frozen=True)
class ResearchTopic:
    topic_id: str
    name: str
    description: str
    created_at: str

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            require_non_empty_string(getattr(self, field_name), field_name)


@dataclass(frozen=True)
class ResearchNote:
    note_id: str
    title: str
    body: str
    created_at: str

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            require_non_empty_string(getattr(self, field_name), field_name)


@dataclass(frozen=True)
class ResearchBriefDraft:
    draft_id: str
    title: str
    body: str
    source_urls: tuple[str, ...]
    provenance: str
    created_at: str

    def __post_init__(self) -> None:
        for field_name in ("draft_id", "title", "body", "provenance", "created_at"):
            require_non_empty_string(getattr(self, field_name), field_name)
        if not isinstance(self.source_urls, tuple) or not self.source_urls:
            raise ValueError("source_urls must be a non-empty tuple.")
        for source_url in self.source_urls:
            require_non_empty_string(source_url, "source_urls")
        if len(set(self.source_urls)) != len(self.source_urls):
            raise ValueError("source_urls must not contain duplicates.")


@dataclass(frozen=True)
class ResearchBrief:
    brief_id: str
    title: str
    body: str
    provenance: str
    created_at: str

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            require_non_empty_string(getattr(self, field_name), field_name)


@dataclass(frozen=True)
class KnowledgeLink:
    link_id: str
    from_kind: str
    from_id: str
    to_kind: str
    to_id: str
    relation: str
    created_at: str

    def __post_init__(self) -> None:
        for field_name in ("link_id", "from_id", "to_id", "relation", "created_at"):
            require_non_empty_string(getattr(self, field_name), field_name)
        _require_research_item_kind(self.from_kind, "from_kind")
        _require_research_item_kind(self.to_kind, "to_kind")
        if self.from_kind == self.to_kind and self.from_id == self.to_id:
            raise ValueError("A knowledge item cannot link to itself.")


@dataclass(frozen=True)
class ResearchRevision:
    revision_id: str
    item_kind: str
    item_id: str
    version: int
    content: str
    created_at: str

    def __post_init__(self) -> None:
        for field_name in ("revision_id", "item_id", "content", "created_at"):
            require_non_empty_string(getattr(self, field_name), field_name)
        _require_research_item_kind(self.item_kind, "item_kind")
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise ValueError("version must be a positive integer.")


@dataclass(frozen=True)
class ResearchPlanningSnapshot:
    topic_id: str
    name: str
    description: str
    source_count: int
    note_count: int
    brief_count: int
    recent_brief_titles: tuple[str, ...]
    unresolved_questions: tuple[str, ...]
    created_at: str

    def __post_init__(self) -> None:
        for field_name in ("topic_id", "name", "description", "created_at"):
            require_non_empty_string(getattr(self, field_name), field_name)
        for field_name in ("source_count", "note_count", "brief_count"):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer.")
        if not isinstance(self.recent_brief_titles, tuple):
            raise ValueError("recent_brief_titles must be a tuple.")
        for title in self.recent_brief_titles:
            require_non_empty_string(title, "recent_brief_titles")
        if not isinstance(self.unresolved_questions, tuple):
            raise ValueError("unresolved_questions must be a tuple.")
        for question in self.unresolved_questions:
            require_non_empty_string(question, "unresolved_questions")


@dataclass(frozen=True)
class ResearchContextCandidate:
    candidate_id: str
    item_kind: str
    title: str
    content: str
    provenance: str
    estimated_chars: int
    created_at: str

    def __post_init__(self) -> None:
        for field_name in (
            "candidate_id",
            "title",
            "content",
            "provenance",
            "created_at",
        ):
            require_non_empty_string(getattr(self, field_name), field_name)
        _require_research_item_kind(self.item_kind, "item_kind")
        if (
            not isinstance(self.estimated_chars, int)
            or isinstance(self.estimated_chars, bool)
            or self.estimated_chars < 1
        ):
            raise ValueError("estimated_chars must be a positive integer.")


@dataclass(frozen=True)
class ResearchMemoryCandidate:
    candidate_id: str
    item_kind: str
    title: str
    content: str
    provenance: str
    created_at: str

    def __post_init__(self) -> None:
        for field_name in (
            "candidate_id",
            "title",
            "content",
            "provenance",
            "created_at",
        ):
            require_non_empty_string(getattr(self, field_name), field_name)
        if self.item_kind not in {"note", "brief"}:
            raise ValueError("Memory candidates must be saved notes or briefs.")


@dataclass(frozen=True)
class ResearchSavedItem:
    item_id: str
    item_kind: str
    title: str
    created_at: str

    def __post_init__(self) -> None:
        for field_name in ("item_id", "title", "created_at"):
            require_non_empty_string(getattr(self, field_name), field_name)
        _require_research_item_kind(self.item_kind, "item_kind")
