"""Research-owned adapter from MCP paper results to domain observations."""

from __future__ import annotations

import json
from collections.abc import Mapping
from hashlib import sha256
from typing import Any, Protocol

from app.common.ids import new_id
from app.common.time import utc_now_iso
from app.domains.research.models import ExternalObservation, PaperSearchResult
from app.domains.research.ports import ResearchPaperSearchError
from app.integrations.mcp.client import OneShotStdioMcpClient
from app.integrations.mcp.errors import McpClientError
from app.integrations.mcp.models import McpServerConfig, McpToolCallResult
from app.integrations.research_mcp.contracts import SEARCH_PAPERS_INPUT_SCHEMA


class McpToolCaller(Protocol):
    def call_tool(
        self,
        config: McpServerConfig,
        *,
        tool_name: str,
        arguments: Mapping[str, Any],
        expected_input_schema: Mapping[str, Any],
    ) -> McpToolCallResult: ...


class HuggingFaceMcpPaperSearchAdapter:
    """Validate the fixed MCP result and release all SDK types at this edge."""

    def __init__(
        self,
        config: McpServerConfig,
        client: McpToolCaller | None = None,
    ) -> None:
        self._config = config
        self._client = client or OneShotStdioMcpClient()

    def search_papers(
        self,
        query: str,
        limit: int,
    ) -> PaperSearchResult:
        normalized_query = query.strip()
        if not normalized_query or len(normalized_query) > 200:
            raise ValueError("query must contain between 1 and 200 characters.")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 10:
            raise ValueError("limit must be an integer between 1 and 10.")

        try:
            result = self._client.call_tool(
                self._config,
                tool_name="search_papers",
                arguments={"query": normalized_query, "limit": limit},
                expected_input_schema=SEARCH_PAPERS_INPUT_SCHEMA,
            )
        except McpClientError as exc:
            raise ResearchPaperSearchError(
                "Paper search is temporarily unavailable.",
                code=exc.code,
                retryable=exc.retryable,
            ) from exc
        if result.is_error:
            raise ResearchPaperSearchError(
                "The paper provider rejected the search request.",
                code="research_paper_provider_error",
                retryable=False,
            )
        error_code = result.structured_content.get("error_code")
        retryable = result.structured_content.get("retryable", False)
        if error_code is not None:
            if (
                error_code
                not in {
                    "research_paper_rate_limited",
                    "research_paper_provider_unavailable",
                    "research_paper_provider_failed",
                }
                or not isinstance(retryable, bool)
                or result.structured_content.get("papers") != []
            ):
                raise ResearchPaperSearchError(
                    "The paper provider returned an invalid result.",
                    code="research_paper_result_invalid",
                    retryable=False,
                )
            raise ResearchPaperSearchError(
                "Paper search is temporarily unavailable.",
                code=error_code,
                retryable=retryable,
            )
        papers = result.structured_content.get("papers")
        invalid_count = result.structured_content.get("invalid_count")
        if (
            not isinstance(papers, list)
            or len(papers) > 10
            or not isinstance(invalid_count, int)
            or isinstance(invalid_count, bool)
            or not 0 <= invalid_count <= 10
            or len(papers) + invalid_count > limit
        ):
            raise ResearchPaperSearchError(
                "The paper provider returned an invalid result.",
                code="research_paper_result_invalid",
                retryable=False,
            )

        observations: list[ExternalObservation] = []
        identities: set[tuple[str, str]] = set()
        for paper in papers:
            try:
                observation, identity = _to_observation(paper)
            except (KeyError, TypeError, ValueError):
                invalid_count += 1
                continue
            if identity in identities:
                continue
            identities.add(identity)
            observations.append(observation)
        if invalid_count and not observations:
            raise ResearchPaperSearchError(
                "The paper provider returned an invalid result.",
                code="research_paper_result_invalid",
                retryable=False,
            )
        return PaperSearchResult(tuple(observations), invalid_count)


def _to_observation(
    raw: object,
) -> tuple[ExternalObservation, tuple[str, str]]:
    if not isinstance(raw, dict) or set(raw) != {
        "paper_id",
        "title",
        "authors",
        "summary",
        "published_at",
        "url",
    }:
        raise ValueError("Paper fields do not match the adapter contract.")
    paper_id = _required_bounded_text(raw["paper_id"], 200)
    title = _required_bounded_text(raw["title"], 300)
    url = _required_bounded_text(raw["url"], 500)
    if not url.startswith("https://huggingface.co/papers/"):
        raise ValueError("Paper URL is not canonical.")
    authors_raw = raw["authors"]
    if not isinstance(authors_raw, list) or len(authors_raw) > 20:
        raise ValueError("Paper authors are invalid.")
    authors = tuple(_required_bounded_text(author, 120) for author in authors_raw)
    raw_summary = _optional_bounded_text(raw["summary"], 4000)
    author_line = f"Authors: {', '.join(authors)}\n\n" if authors else ""
    summary = (author_line + (raw_summary or title))[:4500]
    published_at = raw["published_at"]
    if published_at is not None:
        published_at = _required_bounded_text(published_at, 64)

    projection = {
        "paper_id": paper_id,
        "title": title,
        "authors": authors,
        "summary": raw_summary,
        "published_at": published_at,
        "url": url,
    }
    content_hash = sha256(
        json.dumps(
            projection,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return (
        ExternalObservation(
            observation_id=new_id("observation"),
            source_key="hf_paper",
            title=title,
            url=url,
            summary=summary,
            content_hash=content_hash,
            fetched_at=utc_now_iso(),
            provenance=f"external:mcp:huggingface-papers:{paper_id}",
            source_type="paper",
            published_at=published_at,
            external_id=paper_id,
            authors=authors,
        ),
        (paper_id, url),
    )


def _required_bounded_text(value: object, maximum: int) -> str:
    if not isinstance(value, str):
        raise TypeError("Expected a string.")
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > maximum:
        raise ValueError("String is empty or too long.")
    return normalized


def _optional_bounded_text(value: object, maximum: int) -> str:
    if not isinstance(value, str):
        raise TypeError("Expected a string.")
    normalized = " ".join(value.split())
    if len(normalized) > maximum:
        raise ValueError("String is too long.")
    return normalized
