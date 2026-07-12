"""SQLite repository for saved Research sources."""

from __future__ import annotations

import sqlite3

from app.common.errors import StorageError
from app.common.ids import new_id
from app.common.time import utc_now_iso
from app.domains.research.models import ExternalObservation, ResearchSource


class ResearchRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save_source(self, observation: ExternalObservation) -> ResearchSource:
        source = ResearchSource(
            source_id=new_id("research-source"),
            source_key=observation.source_key,
            title=observation.title,
            url=observation.url,
            summary=observation.summary,
            content_hash=observation.content_hash,
            fetched_at=observation.fetched_at,
            provenance=observation.provenance,
            created_at=utc_now_iso(),
        )
        try:
            self._conn.execute(
                """
                INSERT INTO research_sources (
                    id, source_key, url, title, summary, content_hash,
                    fetched_at, provenance, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source.source_id,
                    source.source_key,
                    source.url,
                    source.title,
                    source.summary,
                    source.content_hash,
                    source.fetched_at,
                    source.provenance,
                    source.created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise StorageError(
                "Research source already exists.",
                code="research_source_duplicate",
            ) from exc
        except sqlite3.Error as exc:
            raise StorageError(
                "Failed to save Research source.",
                code="research_source_save_failed",
            ) from exc
        return source
