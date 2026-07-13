"""Deterministic parsing, deduplication, and ranking for Research sources."""

from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin

from app.domains.research.models import FetchedSourceDocument, ResearchItem


HF_BASE_URL = "https://huggingface.co"
MAX_PARSED_ITEMS = 20
_SOURCE_PATH_PREFIXES = {
    "hf_daily_papers": "/papers/",
    "hf_blog": "/blog/",
}


class _LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text_parts: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self._href = href
                self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._href is None:
            return
        title = _clean_text(" ".join(self._text_parts))
        if title:
            self.links.append((self._href, title))
        self._href = None
        self._text_parts = []


def parse_research_items(
    document: FetchedSourceDocument, limit: int = MAX_PARSED_ITEMS
) -> tuple[ResearchItem, ...]:
    """Parse a supported fetched document without mutating request state."""
    if not isinstance(document, FetchedSourceDocument):
        raise ValueError("document must be a FetchedSourceDocument.")
    try:
        path_prefix = _SOURCE_PATH_PREFIXES[document.source_key]
    except KeyError as exc:
        raise ValueError("document source is not supported by the parser.") from exc
    bounded_limit = _bounded_limit(limit)
    collector = _LinkCollector()
    collector.feed(document.content)

    items: list[ResearchItem] = []
    seen_urls: set[str] = set()
    for href, title in collector.links:
        clean_href = href.split("#", maxsplit=1)[0]
        if not clean_href.startswith(path_prefix) or clean_href == path_prefix.rstrip("/"):
            continue
        url = urljoin(HF_BASE_URL, clean_href)
        if url in seen_urls or not _looks_like_title(title):
            continue
        seen_urls.add(url)
        position = len(items) + 1
        items.append(
            ResearchItem(
                item_id=f"{document.source_key}:{position}",
                source_key=document.source_key,
                title=title,
                url=url,
                raw_position=position,
                topic_hint=_topic_hint(title),
            )
        )
        if len(items) >= bounded_limit:
            break
    return tuple(items)


def dedupe_research_items(
    items: tuple[ResearchItem, ...],
) -> tuple[ResearchItem, ...]:
    """Preserve first occurrence, deduplicating by URL then normalized title."""
    deduped: list[ResearchItem] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    for item in items:
        if not isinstance(item, ResearchItem):
            raise ValueError("items must contain ResearchItem values.")
        normalized_url = item.url.strip().lower()
        normalized_title = _clean_text(item.title).lower()
        if normalized_url in seen_urls or normalized_title in seen_titles:
            continue
        seen_urls.add(normalized_url)
        seen_titles.add(normalized_title)
        deduped.append(item)
    return tuple(deduped)


def rank_research_items(
    items: tuple[ResearchItem, ...],
    limit: int = MAX_PARSED_ITEMS,
    topic_filter: str | None = None,
) -> tuple[ResearchItem, ...]:
    """Rank by optional score, then retain deterministic source order."""
    filtered = filter_research_items(items, topic_filter)
    return tuple(
        sorted(
            dedupe_research_items(filtered),
            key=lambda item: (-(item.score or 0), item.raw_position, item.url),
        )[: _bounded_limit(limit)]
    )


def filter_research_items(
    items: tuple[ResearchItem, ...], topic_filter: str | None
) -> tuple[ResearchItem, ...]:
    """Filter by the deterministic topic hint or a title keyword."""
    if topic_filter is None:
        return items
    if not isinstance(topic_filter, str) or not topic_filter.strip():
        raise ValueError("topic_filter must be a non-empty string or None.")
    normalized = topic_filter.strip().lower()
    return tuple(
        item
        for item in items
        if item.topic_hint == normalized or normalized in item.title.lower()
    )


def _bounded_limit(limit: int) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise ValueError("limit must be an integer.")
    return min(max(limit, 1), MAX_PARSED_ITEMS)


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _looks_like_title(title: str) -> bool:
    if len(title) < 4:
        return False
    return title.lower() not in {"blog", "papers", "daily papers", "hugging face"}


def _topic_hint(title: str) -> str | None:
    lowered = title.lower()
    if any(keyword in lowered for keyword in ("agent", "tool use", "workflow")):
        return "agent"
    if any(keyword in lowered for keyword in ("llm", "language model", "reasoning")):
        return "llm"
    if any(keyword in lowered for keyword in ("vision", "multimodal", "video", "image")):
        return "multimodal"
    return None
