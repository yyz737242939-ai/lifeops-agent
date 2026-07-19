"""Research external source ports and deterministic fixture adapter."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.common.errors import AppError
from app.common.ids import new_id
from app.common.time import utc_now_iso
from app.domains.research.models import (
    ExternalObservation,
    FetchedSourceDocument,
    PaperSearchResult,
)
from app.domains.research.source_manifest import load_research_source


MAX_RESEARCH_SOURCE_BYTES = 500_000
RESEARCH_SOURCE_TIMEOUT_SECONDS = 8.0
RESEARCH_SOURCE_USER_AGENT = "LifeOps-Agent/0.1 read-only research source fetcher"


class ResearchExternalSourceError(AppError):
    """Raised when a declared Research source cannot be fetched safely."""


class ResearchPaperSearchError(AppError):
    """Stable failure returned by a paper-search adapter."""

    def __init__(self, message: str, *, code: str, retryable: bool) -> None:
        super().__init__(message, code=code, details={"retryable": retryable})
        self.retryable = retryable


class ResearchSourcePort(Protocol):
    def fetch(self, source_key: str) -> ExternalObservation:
        ...


class ResearchContentPort(Protocol):
    def fetch(self, source_key: str) -> FetchedSourceDocument:
        ...


class PaperSearchPort(Protocol):
    def search_papers(
        self,
        query: str,
        limit: int,
    ) -> PaperSearchResult:
        ...


class HuggingFaceResearchContentPort:
    """Fetch declared Hugging Face HTML sources behind a typed port."""

    def __init__(
        self,
        skill_root: Path,
        *,
        max_bytes: int = MAX_RESEARCH_SOURCE_BYTES,
        timeout_seconds: float = RESEARCH_SOURCE_TIMEOUT_SECONDS,
    ) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive.")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")
        self._skill_root = skill_root
        self._max_bytes = max_bytes
        self._timeout_seconds = timeout_seconds

    def fetch(self, source_key: str) -> FetchedSourceDocument:
        definition = load_research_source(self._skill_root, source_key)
        request = Request(
            definition.url, headers={"User-Agent": RESEARCH_SOURCE_USER_AGENT}
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                status = int(getattr(response, "status", 200))
                final_url = str(response.geturl())
                content_type = str(response.headers.get("Content-Type", ""))
                if status < 200 or status >= 300:
                    raise ResearchExternalSourceError(
                        "Research source returned an unsuccessful status.",
                        code="research_source_http_error",
                    )
                if final_url != definition.url:
                    raise ResearchExternalSourceError(
                        "Research source redirected away from its declared URL.",
                        code="research_source_redirect_forbidden",
                    )
                if not content_type.lower().startswith("text/html"):
                    raise ResearchExternalSourceError(
                        "Research source did not return HTML.",
                        code="research_source_content_type_invalid",
                    )
                raw = response.read(self._max_bytes + 1)
                if len(raw) > self._max_bytes:
                    raise ResearchExternalSourceError(
                        "Research source exceeds the configured size limit.",
                        code="research_source_too_large",
                    )
                charset = response.headers.get_content_charset() or "utf-8"
                content = raw.decode(charset)
        except ResearchExternalSourceError:
            raise
        except HTTPError as exc:
            raise ResearchExternalSourceError(
                "Research source returned an HTTP error.",
                code="research_source_http_error",
                details={"status": exc.code},
            ) from exc
        except (URLError, TimeoutError, OSError, UnicodeError) as exc:
            raise ResearchExternalSourceError(
                "Research source fetch failed.", code="research_source_fetch_failed"
            ) from exc
        if not content.strip():
            raise ResearchExternalSourceError(
                "Research source returned empty HTML.", code="research_source_empty"
            )
        return FetchedSourceDocument(
            document_id=new_id("research-document"),
            observation_id=new_id("observation"),
            source_key=definition.source_key,
            title=definition.name,
            url=definition.url,
            content_type="text/html",
            content=content,
            content_hash=sha256(raw).hexdigest(),
            fetched_at=utc_now_iso(),
            provenance=f"external:{definition.source_key}:{definition.url}",
        )


class FixtureResearchSourcePort:
    """Fetch only explicitly declared fixture source keys."""

    def __init__(self, sources: Mapping[str, Mapping[str, str]]) -> None:
        self._sources = {key: dict(value) for key, value in sources.items()}

    def fetch(self, source_key: str) -> ExternalObservation:
        try:
            source = self._sources[source_key]
        except KeyError as exc:
            raise ValueError("source_key is not declared by the fixture adapter.") from exc
        title = source["title"]
        url = source["url"]
        summary = source["summary"]
        return ExternalObservation(
            observation_id=new_id("observation"),
            source_key=source_key,
            title=title,
            url=url,
            summary=summary,
            content_hash=sha256(summary.encode("utf-8")).hexdigest(),
            fetched_at=utc_now_iso(),
            provenance=f"fixture:{source_key}",
        )
