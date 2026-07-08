from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin


HF_BASE_URL = "https://huggingface.co"


class _LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[dict[str, str]] = []
        self._current_href: str | None = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self._current_href = href
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._current_href is None:
            return
        text = " ".join(part.strip() for part in self._text_parts if part.strip())
        if text:
            self.links.append({"href": self._current_href, "text": _clean_text(text)})
        self._current_href = None
        self._text_parts = []


def parse_hf_daily_papers(html: str, limit: int) -> list[dict[str, Any]]:
    """Parse Hugging Face Papers list links into structured news items."""
    return _parse_hf_links(
        html,
        limit,
        source_id="hf_daily_papers",
        path_prefix="/papers/",
    )


def parse_hf_blog(html: str, limit: int) -> list[dict[str, Any]]:
    """Parse Hugging Face Blog list links into structured news items."""
    return _parse_hf_links(
        html,
        limit,
        source_id="hf_blog",
        path_prefix="/blog/",
    )


def rank_news_items(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Rank parsed news items without mutating the input list."""
    bounded_limit = _bounded_limit(limit)
    return sorted(
        dedupe_news_items(items),
        key=lambda item: (
            -(item.get("score_or_votes") or 0),
            int(item.get("raw_position") or 0),
        ),
    )[:bounded_limit]


def dedupe_news_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe news items by URL first, then normalized title."""
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        title = _clean_text(str(item.get("title") or ""))
        key = url or title.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        copy = dict(item)
        copy["title"] = title
        deduped.append(copy)
    return deduped


def _parse_hf_links(
    html: str,
    limit: int,
    *,
    source_id: str,
    path_prefix: str,
) -> list[dict[str, Any]]:
    collector = _LinkCollector()
    collector.feed(html or "")

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for link in collector.links:
        href = link["href"].split("#", maxsplit=1)[0]
        if not href.startswith(path_prefix):
            continue
        if href == path_prefix.rstrip("/"):
            continue
        url = urljoin(HF_BASE_URL, href)
        title = link["text"]
        key = url.lower()
        if key in seen or not _looks_like_title(title):
            continue
        seen.add(key)
        items.append(
            {
                "id": f"{source_id}:{len(items) + 1}",
                "source_id": source_id,
                "title": title,
                "url": url,
                "author_or_org": None,
                "published_or_relative_time": None,
                "score_or_votes": None,
                "topic_hint": _topic_hint(title),
                "raw_position": len(items) + 1,
            }
        )
        if len(items) >= _bounded_limit(limit):
            break
    return items


def _bounded_limit(limit: int) -> int:
    if limit < 1:
        return 1
    return min(limit, 20)


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _looks_like_title(title: str) -> bool:
    if len(title) < 4:
        return False
    lowered = title.lower()
    return lowered not in {"blog", "papers", "daily papers", "hugging face"}


def _topic_hint(title: str) -> str | None:
    lowered = title.lower()
    if any(keyword in lowered for keyword in ("agent", "tool use", "workflow")):
        return "agent"
    if any(keyword in lowered for keyword in ("llm", "language model", "reasoning")):
        return "llm"
    if any(keyword in lowered for keyword in ("vision", "multimodal", "video", "image")):
        return "multimodal"
    return None
