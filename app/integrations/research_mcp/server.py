"""Single-purpose local stdio MCP server for Hugging Face paper search."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

from app.integrations.research_mcp.contracts import SEARCH_PAPERS_INPUT_SCHEMA
from app.integrations.research_mcp.provider import (
    FixturePaperProvider,
    HuggingFacePaperProvider,
    PaperProvider,
    PaperProviderResult,
    PaperRecord,
    ResearchPaperProviderError,
    validate_search_request,
)


class SearchPapersResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    papers: list[PaperRecord]
    invalid_count: int = Field(default=0, ge=0, le=10)
    error_code: str | None = None
    retryable: bool = False


def create_server(provider: PaperProvider) -> FastMCP:
    server = FastMCP("lifeops-research-papers", log_level="ERROR")

    @server.tool(name="search_papers", structured_output=True)
    def search_papers(
        query: Annotated[str, Field(min_length=1, max_length=200)],
        limit: Annotated[int, Field(ge=1, le=10)] = 5,
    ) -> SearchPapersResult:
        normalized_query, normalized_limit = validate_search_request(query, limit)
        try:
            result = provider.search_papers(normalized_query, normalized_limit)
        except ResearchPaperProviderError as exc:
            return SearchPapersResult(
                papers=[],
                error_code=exc.code,
                retryable=exc.retryable,
            )
        return SearchPapersResult(
            papers=list(result.papers),
            invalid_count=result.invalid_count,
        )

    return server


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument(
        "--fixture-error",
        choices=(
            "research_paper_rate_limited",
            "research_paper_provider_unavailable",
        ),
    )
    arguments, _ = parser.parse_known_args()
    provider: PaperProvider
    if arguments.fixture_error is not None:
        provider = _FailurePaperProvider(arguments.fixture_error)
    elif arguments.fixture is None:
        provider = HuggingFacePaperProvider()
    else:
        provider = FixturePaperProvider(arguments.fixture)
    create_server(provider).run(transport="stdio")


class _FailurePaperProvider:
    def __init__(self, code: str) -> None:
        self._code = code

    def search_papers(self, query: str, limit: int) -> PaperProviderResult:
        del query, limit
        raise ResearchPaperProviderError(code=self._code, retryable=True)


if __name__ == "__main__":
    main()
