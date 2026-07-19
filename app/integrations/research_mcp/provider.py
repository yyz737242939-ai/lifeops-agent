"""Provider façade and bounded paper normalization for the MCP server."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

import httpx
from huggingface_hub import HfApi
from huggingface_hub.errors import HfHubHTTPError
from pydantic import BaseModel, ConfigDict, Field


class PaperRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=300)
    authors: list[str] = Field(default_factory=list, max_length=20)
    summary: str = Field(default="", max_length=4000)
    published_at: str | None = None
    url: str = Field(min_length=1, max_length=500)


@dataclass(frozen=True)
class PaperProviderResult:
    papers: tuple[PaperRecord, ...]
    invalid_count: int = 0


class PaperProvider(Protocol):
    def search_papers(self, query: str, limit: int) -> PaperProviderResult: ...


class ResearchPaperProviderError(Exception):
    """Safe provider failure that can cross the local MCP wire."""

    def __init__(self, *, code: str, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class HuggingFacePaperProvider:
    """Public, read-only Hugging Face papers provider."""

    def __init__(self, api: Any | None = None) -> None:
        self._api = api or HfApi(token=False)

    def search_papers(self, query: str, limit: int) -> PaperProviderResult:
        try:
            raw_papers = self._api.list_papers(
                query=query,
                limit=limit,
                token=False,
            )
            papers: list[PaperRecord] = []
            invalid_count = 0
            for item in raw_papers:
                try:
                    papers.append(_normalize_hugging_face_paper(item))
                except (TypeError, ValueError):
                    invalid_count += 1
            return PaperProviderResult(tuple(papers), invalid_count)
        except HfHubHTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 429:
                raise ResearchPaperProviderError(
                    code="research_paper_rate_limited",
                    retryable=True,
                ) from exc
            if isinstance(status, int) and status >= 500:
                raise ResearchPaperProviderError(
                    code="research_paper_provider_unavailable",
                    retryable=True,
                ) from exc
            raise ResearchPaperProviderError(
                code="research_paper_provider_failed",
                retryable=False,
            ) from exc
        except (httpx.TimeoutException, httpx.NetworkError, TimeoutError, OSError) as exc:
            raise ResearchPaperProviderError(
                code="research_paper_provider_unavailable",
                retryable=True,
            ) from exc


class FixturePaperProvider:
    """Deterministic provider used by real-transport offline tests."""

    def __init__(self, fixture_path: Path) -> None:
        raw = json.loads(fixture_path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("Paper fixture must be a list.")
        self._papers = tuple(PaperRecord.model_validate(item) for item in raw)

    def search_papers(self, query: str, limit: int) -> PaperProviderResult:
        normalized_query = query.casefold()
        matched = (
            paper
            for paper in self._papers
            if normalized_query in f"{paper.title}\n{paper.summary}".casefold()
        )
        return PaperProviderResult(tuple(list(matched)[:limit]))


def validate_search_request(query: str, limit: int) -> tuple[str, int]:
    normalized_query = query.strip()
    if not normalized_query or len(normalized_query) > 200:
        raise ValueError("query must contain between 1 and 200 characters.")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 10:
        raise ValueError("limit must be an integer between 1 and 10.")
    return normalized_query, limit


def _normalize_hugging_face_paper(item: Any) -> PaperRecord:
    paper_id = _bounded_text(getattr(item, "id", None), 200)
    if not paper_id:
        raise ValueError("Hugging Face paper is missing an id.")
    title = _bounded_text(getattr(item, "title", None), 300) or paper_id
    summary = _bounded_text(getattr(item, "summary", None), 4000)
    authors = [
        name
        for author in list(getattr(item, "authors", None) or ())[:20]
        if (name := _bounded_text(getattr(author, "name", None), 120))
    ]
    published_at = _normalize_datetime(getattr(item, "published_at", None))
    return PaperRecord(
        paper_id=paper_id,
        title=title,
        authors=authors,
        summary=summary,
        published_at=published_at,
        url=f"https://huggingface.co/papers/{quote(paper_id, safe='')}",
    )


def _bounded_text(value: object, maximum: int) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())[:maximum]


def _normalize_datetime(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    text = _bounded_text(value, 64)
    return text or None
