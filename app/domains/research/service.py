"""Request-local Research workflow service."""

from __future__ import annotations

from app.domains.research.models import (
    ExternalObservation,
    FetchedSourceDocument,
    KnowledgeLink,
    PaperSearchResult,
    ResearchBrief,
    ResearchBriefBuildResult,
    ResearchBriefDraft,
    ResearchNote,
    ResearchItem,
    ResearchItemSet,
    ResearchRevision,
    ResearchSavedItem,
    ResearchSource,
    ResearchTopic,
)
from app.common.ids import new_id
from app.common.time import utc_now_iso
from app.domains.research.ports import (
    PaperSearchPort,
    ResearchContentPort,
    ResearchSourcePort,
)
from app.domains.research.processing import (
    parse_research_items,
    rank_research_items,
)
from app.domains.research.repository import ResearchRepository


class ResearchService:
    """Keep fetched observations temporary until an authorized save Tool runs."""

    def __init__(
        self,
        source_port: ResearchSourcePort,
        repository: ResearchRepository,
        *,
        content_port: ResearchContentPort | None = None,
        paper_search_port: PaperSearchPort | None = None,
    ) -> None:
        self._source_port = source_port
        self._repository = repository
        self._content_port = content_port
        self._paper_search_port = paper_search_port
        self._observations: dict[str, ExternalObservation] = {}
        self._documents: dict[str, FetchedSourceDocument] = {}
        self._item_sets: dict[str, ResearchItemSet] = {}
        self._brief_drafts: dict[str, ResearchBriefDraft] = {}

    def fetch_source(self, source_key: str) -> ExternalObservation:
        observation = self._source_port.fetch(source_key)
        self._observations[observation.observation_id] = observation
        return observation

    def save_source(self, observation_id: str) -> ResearchSource:
        try:
            observation = self._observations[observation_id]
        except KeyError as exc:
            raise ValueError("observation_id is not available in this request.") from exc
        return self._repository.save_source(observation)

    def search_papers(
        self,
        query: str,
        *,
        limit: int = 5,
    ) -> PaperSearchResult:
        if self._paper_search_port is None:
            raise RuntimeError("Research paper search port is not configured.")
        result = self._paper_search_port.search_papers(query, limit)
        for observation in result.observations:
            self._observations[observation.observation_id] = observation
        return result

    def fetch_content(self, source_key: str) -> FetchedSourceDocument:
        if self._content_port is None:
            raise RuntimeError("Research content port is not configured.")
        document = self._content_port.fetch(source_key)
        self._documents[document.document_id] = document
        self._observations[document.observation_id] = ExternalObservation(
            observation_id=document.observation_id,
            source_key=document.source_key,
            title=document.title,
            url=document.url,
            summary=f"Fetched declared HTML list page: {document.title}.",
            content_hash=document.content_hash,
            fetched_at=document.fetched_at,
            provenance=document.provenance,
        )
        return document

    def parse_items(
        self, document_id: str, *, limit: int = 20
    ) -> ResearchItemSet:
        try:
            document = self._documents[document_id]
        except KeyError as exc:
            raise ValueError("document_id is not available in this request.") from exc
        items = parse_research_items(document, limit)
        if not items:
            raise ValueError("No Research items were parsed from the document.")
        item_set = ResearchItemSet(
            item_set_id=new_id("research-item-set"),
            document_ids=(document.document_id,),
            items=items,
            created_at=utc_now_iso(),
        )
        self._item_sets[item_set.item_set_id] = item_set
        return item_set

    def rank_items(
        self,
        item_set_id: str,
        *,
        limit: int = 20,
        topic_filter: str | None = None,
    ) -> ResearchItemSet:
        item_set = self._get_item_set(item_set_id)
        ranked = ResearchItemSet(
            item_set_id=new_id("research-item-set"),
            document_ids=item_set.document_ids,
            items=rank_research_items(item_set.items, limit, topic_filter),
            created_at=utc_now_iso(),
        )
        self._item_sets[ranked.item_set_id] = ranked
        return ranked

    def build_brief_draft(
        self, item_set_id: str, title: str
    ) -> ResearchBriefDraft:
        item_set = self._get_item_set(item_set_id)
        body_lines = ["基于 Hugging Face 列表页可见信息：", ""]
        for item in item_set.items:
            topic = item.topic_hint or "other"
            body_lines.append(
                f"- [{item.title}]({item.url})（{item.source_key}；{topic}）"
            )
        draft = ResearchBriefDraft(
            draft_id=new_id("research-brief-draft"),
            title=title,
            body="\n".join(body_lines),
            source_urls=tuple(
                dict.fromkeys(
                    self._documents[document_id].url
                    for document_id in item_set.document_ids
                )
            ),
            provenance="request-local:hugging-face-list-pages",
            created_at=utc_now_iso(),
        )
        self.register_brief_draft(draft)
        return draft

    def build_brief(
        self,
        source_keys: tuple[str, ...],
        *,
        limit: int = 10,
        topic_filter: str | None = None,
    ) -> ResearchBriefBuildResult:
        if (
            not isinstance(source_keys, tuple)
            or not source_keys
            or len(source_keys) > 2
            or len(set(source_keys)) != len(source_keys)
        ):
            raise ValueError("source_keys must contain one or two unique sources.")
        if not 1 <= limit <= 20:
            raise ValueError("limit must be between 1 and 20.")
        documents = tuple(self.fetch_content(source_key) for source_key in source_keys)
        parsed_items = tuple(
            item
            for document in documents
            for item in parse_research_items(document, 20)
        )
        ranked_items = rank_research_items(parsed_items, limit, topic_filter)
        if not ranked_items:
            raise ValueError("No Research items matched the briefing request.")
        item_set = ResearchItemSet(
            item_set_id=new_id("research-item-set"),
            document_ids=tuple(document.document_id for document in documents),
            items=ranked_items,
            created_at=utc_now_iso(),
        )
        self._item_sets[item_set.item_set_id] = item_set
        title_suffix = topic_filter.strip() if topic_filter else "Hugging Face updates"
        draft = self.build_brief_draft(
            item_set.item_set_id,
            f"Research Brief: {title_suffix}",
        )
        return ResearchBriefBuildResult(
            draft=draft,
            source_observation_ids=tuple(
                document.observation_id for document in documents
            ),
            item_count=len(ranked_items),
        )

    def _get_item_set(self, item_set_id: str) -> ResearchItemSet:
        try:
            return self._item_sets[item_set_id]
        except KeyError as exc:
            raise ValueError("item_set_id is not available in this request.") from exc

    def register_brief_draft(self, draft: ResearchBriefDraft) -> None:
        """Keep a generated draft request-local until an authorized save runs."""
        self._brief_drafts[draft.draft_id] = draft

    def create_topic(self, name: str, description: str) -> ResearchTopic:
        return self._repository.create_topic(name, description)

    def create_note(self, title: str, body: str) -> ResearchNote:
        return self._repository.create_note(title, body)

    def save_brief(self, draft_id: str) -> ResearchBrief:
        try:
            draft = self._brief_drafts[draft_id]
        except KeyError as exc:
            raise ValueError("draft_id is not available in this request.") from exc
        return self._repository.save_brief(draft)

    def link_items(
        self,
        from_kind: str,
        from_id: str,
        to_kind: str,
        to_id: str,
        relation: str,
    ) -> KnowledgeLink:
        return self._repository.link_items(
            from_kind, from_id, to_kind, to_id, relation
        )

    def append_revision(
        self, item_kind: str, item_id: str, content: str
    ) -> ResearchRevision:
        return self._repository.append_revision(item_kind, item_id, content)

    def list_topics(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        filter_text: str | None = None,
    ) -> tuple[ResearchTopic, ...]:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Topic pagination is invalid.")
        normalized_filter = filter_text.strip() if filter_text else None
        if normalized_filter is not None and len(normalized_filter) > 200:
            raise ValueError("Topic filter is too long.")
        return self._repository.list_topics(
            limit,
            offset,
            filter_text=normalized_filter,
        )

    def search_saved_items(
        self,
        query: str,
        item_kinds: tuple[str, ...],
        *,
        limit: int,
        offset: int = 0,
    ) -> tuple[ResearchSavedItem, ...]:
        from app.domains.research.read_models import ResearchReadService

        return ResearchReadService(self._repository).search_saved_items(
            query, item_kinds, limit=limit, offset=offset
        )
