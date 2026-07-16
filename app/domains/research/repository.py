"""SQLite repository for saved Research knowledge facts."""

from __future__ import annotations

import sqlite3

from app.common.errors import StorageError
from app.common.ids import new_id
from app.common.time import utc_now_iso
from app.domains.research.models import (
    ExternalObservation,
    KnowledgeLink,
    ResearchBrief,
    ResearchBriefDraft,
    ResearchNote,
    ResearchContextCandidate,
    ResearchMemoryCandidate,
    ResearchPlanningSnapshot,
    ResearchSavedItem,
    ResearchRevision,
    ResearchSource,
    ResearchSourceSnapshot,
    ResearchTopic,
)


_ITEM_TABLES = {
    "topic": "research_topics",
    "source": "research_sources",
    "note": "research_notes",
    "brief": "research_briefs",
}


class ResearchRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save_source(self, observation: ExternalObservation) -> ResearchSource:
        duplicate_content = self._conn.execute(
            "SELECT 1 FROM research_source_snapshots WHERE content_hash = ?",
            (observation.content_hash,),
        ).fetchone()
        if duplicate_content is not None:
            raise StorageError(
                "Research source content already exists.",
                code="research_source_content_duplicate",
            )
        existing = self._conn.execute(
            """SELECT id, source_key, title, url, source_type, created_at
               FROM research_sources WHERE url = ?""",
            (observation.url,),
        ).fetchone()
        if existing is None:
            source = ResearchSource(
                source_id=new_id("research-source"),
                source_key=observation.source_key,
                title=observation.title,
                url=observation.url,
                source_type=observation.source_type,
                created_at=utc_now_iso(),
            )
        else:
            source = ResearchSource(
                source_id=str(existing["id"]),
                source_key=str(existing["source_key"]),
                title=str(existing["title"]),
                url=str(existing["url"]),
                source_type=str(existing["source_type"]),
                created_at=str(existing["created_at"]),
            )
        snapshot = ResearchSourceSnapshot(
            snapshot_id=new_id("research-source-snapshot"),
            source_id=source.source_id,
            summary=observation.summary,
            content_hash=observation.content_hash,
            fetched_at=observation.fetched_at,
            published_at=observation.published_at,
            provenance=observation.provenance,
            created_at=utc_now_iso(),
        )
        try:
            if existing is None:
                self._conn.execute(
                    """INSERT INTO research_sources (
                           id, source_key, url, title, source_type, created_at
                       ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        source.source_id,
                        source.source_key,
                        source.url,
                        source.title,
                        source.source_type,
                        source.created_at,
                    ),
                )
            self._conn.execute(
                """INSERT INTO research_source_snapshots (
                       id, source_id, summary, content_hash, fetched_at,
                       published_at, provenance, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    snapshot.snapshot_id,
                    snapshot.source_id,
                    snapshot.summary,
                    snapshot.content_hash,
                    snapshot.fetched_at,
                    snapshot.published_at,
                    snapshot.provenance,
                    snapshot.created_at,
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

    def create_topic(self, name: str, description: str) -> ResearchTopic:
        topic = ResearchTopic(new_id("research-topic"), name, description, utc_now_iso())
        self._execute_insert(
            "INSERT INTO research_topics (id, name, description, created_at) VALUES (?, ?, ?, ?)",
            (topic.topic_id, topic.name, topic.description, topic.created_at),
            duplicate_code="research_topic_duplicate",
            failure_code="research_topic_create_failed",
        )
        return topic

    def create_note(self, title: str, body: str) -> ResearchNote:
        note = ResearchNote(new_id("research-note"), title, body, utc_now_iso())
        self._execute_insert(
            "INSERT INTO research_notes (id, title, body, created_at) VALUES (?, ?, ?, ?)",
            (note.note_id, note.title, note.body, note.created_at),
            failure_code="research_note_create_failed",
        )
        return note

    def save_brief(self, draft: ResearchBriefDraft) -> ResearchBrief:
        source_refs = tuple(self._source_ref_for_url(url) for url in draft.source_urls)
        brief = ResearchBrief(
            new_id("research-brief"),
            draft.title,
            draft.body,
            draft.provenance,
            utc_now_iso(),
        )
        try:
            self._conn.execute(
                "INSERT INTO research_briefs (id, title, body, provenance, created_at) VALUES (?, ?, ?, ?, ?)",
                (brief.brief_id, brief.title, brief.body, brief.provenance, brief.created_at),
            )
            self._conn.executemany(
                """INSERT INTO research_brief_sources
                   (brief_id, source_id, snapshot_id, position) VALUES (?, ?, ?, ?)""",
                (
                    (brief.brief_id, source_id, snapshot_id, position)
                    for position, (source_id, snapshot_id) in enumerate(source_refs)
                ),
            )
        except sqlite3.Error as exc:
            raise StorageError(
                "Failed to save Research brief.", code="research_brief_save_failed"
            ) from exc
        return brief

    def _source_ref_for_url(self, url: str) -> tuple[str, str]:
        row = self._conn.execute(
            """SELECT s.id AS source_id, ss.id AS snapshot_id
               FROM research_sources AS s
               JOIN research_source_snapshots AS ss ON ss.source_id = s.id
               WHERE s.url = ?
               ORDER BY ss.fetched_at DESC, ss.created_at DESC, ss.id
               LIMIT 1""",
            (url,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Brief source URL is not saved: {url}.")
        return str(row["source_id"]), str(row["snapshot_id"])

    def link_items(
        self,
        from_kind: str,
        from_id: str,
        to_kind: str,
        to_id: str,
        relation: str,
    ) -> KnowledgeLink:
        self._require_item(from_kind, from_id)
        self._require_item(to_kind, to_id)
        link = KnowledgeLink(
            new_id("research-link"),
            from_kind,
            from_id,
            to_kind,
            to_id,
            relation,
            utc_now_iso(),
        )
        self._execute_insert(
            """INSERT INTO research_links
               (id, from_kind, from_id, to_kind, to_id, relation, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                link.link_id,
                link.from_kind,
                link.from_id,
                link.to_kind,
                link.to_id,
                link.relation,
                link.created_at,
            ),
            duplicate_code="research_link_duplicate",
            failure_code="research_link_create_failed",
        )
        return link

    def append_revision(
        self, item_kind: str, item_id: str, content: str
    ) -> ResearchRevision:
        self._require_item(item_kind, item_id)
        row = self._conn.execute(
            """SELECT COALESCE(MAX(version), 0) + 1 AS next_version
               FROM research_revisions WHERE item_kind = ? AND item_id = ?""",
            (item_kind, item_id),
        ).fetchone()
        revision = ResearchRevision(
            new_id("research-revision"),
            item_kind,
            item_id,
            int(row["next_version"]),
            content,
            utc_now_iso(),
        )
        self._execute_insert(
            """INSERT INTO research_revisions
               (id, item_kind, item_id, version, content, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                revision.revision_id,
                revision.item_kind,
                revision.item_id,
                revision.version,
                revision.content,
                revision.created_at,
            ),
            failure_code="research_revision_append_failed",
        )
        return revision

    def get_planning_snapshot(self, topic_id: str) -> ResearchPlanningSnapshot:
        topic = self._conn.execute(
            "SELECT id, name, description, created_at FROM research_topics WHERE id = ?",
            (topic_id,),
        ).fetchone()
        if topic is None:
            raise ValueError(f"topic item is not available: {topic_id}.")
        counts = {
            kind: self._linked_item_count(topic_id, kind)
            for kind in ("source", "note", "brief")
        }
        recent_briefs = self._conn.execute(
            """SELECT DISTINCT b.title, b.created_at, b.id
               FROM research_briefs AS b
               JOIN research_links AS l ON (
                   (l.from_kind = 'brief' AND l.from_id = b.id
                    AND l.to_kind = 'topic' AND l.to_id = ?)
                   OR
                   (l.to_kind = 'brief' AND l.to_id = b.id
                    AND l.from_kind = 'topic' AND l.from_id = ?)
               )
               ORDER BY b.created_at DESC, b.id
               LIMIT 3""",
            (topic_id, topic_id),
        ).fetchall()
        unresolved_questions = self._conn.execute(
            """SELECT DISTINCT n.title, n.created_at, n.id
               FROM research_notes AS n
               JOIN research_links AS l ON (
                   (l.from_kind = 'note' AND l.from_id = n.id
                    AND l.to_kind = 'topic' AND l.to_id = ?)
                   OR
                   (l.to_kind = 'note' AND l.to_id = n.id
                    AND l.from_kind = 'topic' AND l.from_id = ?)
               )
               WHERE l.relation = 'unresolved_question'
               ORDER BY n.created_at DESC, n.id
               LIMIT 10""",
            (topic_id, topic_id),
        ).fetchall()
        return ResearchPlanningSnapshot(
            topic_id=str(topic["id"]),
            name=str(topic["name"]),
            description=str(topic["description"]),
            source_count=counts["source"],
            note_count=counts["note"],
            brief_count=counts["brief"],
            recent_brief_titles=tuple(str(row["title"]) for row in recent_briefs),
            unresolved_questions=tuple(
                str(row["title"]) for row in unresolved_questions
            ),
            created_at=str(topic["created_at"]),
        )

    def list_topics(
        self,
        limit: int,
        offset: int,
        *,
        filter_text: str | None = None,
    ) -> tuple[ResearchTopic, ...]:
        if filter_text:
            pattern = f"%{filter_text}%"
            rows = self._conn.execute(
                """SELECT id, name, description, created_at FROM research_topics
                   WHERE name LIKE ? OR description LIKE ?
                   ORDER BY created_at DESC, id LIMIT ? OFFSET ?""",
                (pattern, pattern, limit, offset),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT id, name, description, created_at FROM research_topics
                   ORDER BY created_at DESC, id LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()
        return tuple(
            ResearchTopic(
                topic_id=str(row["id"]),
                name=str(row["name"]),
                description=str(row["description"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        )

    def query_context_candidates(
        self, query: str, budget_hint: int, *, topic_id: str | None = None
    ) -> tuple[ResearchContextCandidate, ...]:
        rows = self._query_saved_content(
            query, include_sources=True, limit=100, topic_id=topic_id
        )
        candidates: list[ResearchContextCandidate] = []
        used_chars = 0
        for row in rows:
            content = str(row["content"])
            estimated_chars = len(str(row["title"])) + len(content)
            if used_chars + estimated_chars > budget_hint:
                continue
            candidates.append(
                ResearchContextCandidate(
                    candidate_id=str(row["id"]),
                    item_kind=str(row["item_kind"]),
                    title=str(row["title"]),
                    content=content,
                    provenance=str(row["provenance"]),
                    estimated_chars=estimated_chars,
                    created_at=str(row["created_at"]),
                )
            )
            used_chars += estimated_chars
        return tuple(candidates)

    def query_memory_candidates(
        self, query: str, limit: int, *, topic_id: str | None = None
    ) -> tuple[ResearchMemoryCandidate, ...]:
        return tuple(
            ResearchMemoryCandidate(
                candidate_id=str(row["id"]),
                item_kind=str(row["item_kind"]),
                title=str(row["title"]),
                content=str(row["content"]),
                provenance=str(row["provenance"]),
                created_at=str(row["created_at"]),
            )
            for row in self._query_saved_content(
                query, include_sources=False, limit=limit, topic_id=topic_id
            )
        )

    def search_saved_items(
        self,
        query: str,
        item_kinds: tuple[str, ...],
        limit: int,
        offset: int,
    ) -> tuple[ResearchSavedItem, ...]:
        select_specs = {
            "source": """SELECT s.id, 'source' AS item_kind, s.title, s.created_at
                         FROM research_sources AS s
                         JOIN research_source_snapshots AS ss ON ss.source_id = s.id
                         WHERE ss.id = (
                             SELECT latest.id FROM research_source_snapshots AS latest
                             WHERE latest.source_id = s.id
                             ORDER BY latest.fetched_at DESC, latest.created_at DESC, latest.id
                             LIMIT 1
                         )
                         AND instr(lower(s.title || ' ' || ss.summary), lower(?)) > 0""",
            "note": """SELECT id, 'note' AS item_kind, title, created_at
                       FROM research_notes
                       WHERE instr(lower(title || ' ' || body), lower(?)) > 0""",
            "brief": """SELECT id, 'brief' AS item_kind, title, created_at
                        FROM research_briefs
                        WHERE instr(lower(title || ' ' || body), lower(?)) > 0""",
        }
        selects = []
        for item_kind in item_kinds:
            selects.append(select_specs[item_kind])
        parameters: tuple[object, ...] = (*((query,) * len(selects)), limit, offset)
        rows = self._conn.execute(
            f"""SELECT * FROM ({' UNION ALL '.join(selects)})
                ORDER BY created_at DESC, item_kind, id
                LIMIT ? OFFSET ?""",
            parameters,
        ).fetchall()
        return tuple(
            ResearchSavedItem(
                item_id=str(row["id"]),
                item_kind=str(row["item_kind"]),
                title=str(row["title"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        )

    def _linked_item_count(self, topic_id: str, item_kind: str) -> int:
        row = self._conn.execute(
            """SELECT COUNT(DISTINCT item_id) AS item_count
               FROM (
                   SELECT from_id AS item_id FROM research_links
                   WHERE from_kind = ? AND to_kind = 'topic' AND to_id = ?
                   UNION
                   SELECT to_id AS item_id FROM research_links
                   WHERE to_kind = ? AND from_kind = 'topic' AND from_id = ?
               )""",
            (item_kind, topic_id, item_kind, topic_id),
        ).fetchone()
        return int(row["item_count"])

    def _query_saved_content(
        self,
        query: str,
        *,
        include_sources: bool,
        limit: int,
        topic_id: str | None = None,
    ) -> list[sqlite3.Row]:
        if topic_id is not None:
            self._require_item("topic", topic_id)
        source_select = """
            SELECT s.id, 'source' AS item_kind, s.title, ss.summary AS content,
                   ss.provenance, s.created_at
            FROM research_sources AS s
            JOIN research_source_snapshots AS ss ON ss.source_id = s.id
            WHERE ss.id = (
                SELECT latest.id FROM research_source_snapshots AS latest
                WHERE latest.source_id = s.id
                ORDER BY latest.fetched_at DESC, latest.created_at DESC, latest.id
                LIMIT 1
            )
        """
        selects = [
            """SELECT id, 'note' AS item_kind, title, body AS content,
                      'research-note:user-confirmed' AS provenance, created_at
               FROM research_notes""",
            """SELECT id, 'brief' AS item_kind, title, body AS content,
                      provenance, created_at FROM research_briefs""",
        ]
        if include_sources:
            selects.insert(0, source_select)
        union_sql = " UNION ALL ".join(selects)
        return self._conn.execute(
            f"""SELECT * FROM ({union_sql}) AS saved
                WHERE instr(lower(title || ' ' || content), lower(?)) > 0
                AND (? IS NULL OR EXISTS (
                    SELECT 1 FROM research_links AS link
                    WHERE (
                        link.from_kind = saved.item_kind
                        AND link.from_id = saved.id
                        AND link.to_kind = 'topic'
                        AND link.to_id = ?
                    ) OR (
                        link.to_kind = saved.item_kind
                        AND link.to_id = saved.id
                        AND link.from_kind = 'topic'
                        AND link.from_id = ?
                    )
                ))
                ORDER BY created_at DESC, item_kind, id
                LIMIT ?""",
            (query, topic_id, topic_id, topic_id, limit),
        ).fetchall()

    def _require_item(self, item_kind: str, item_id: str) -> None:
        try:
            table_name = _ITEM_TABLES[item_kind]
        except KeyError as exc:
            raise ValueError(f"Unknown research item kind: {item_kind}.") from exc
        row = self._conn.execute(
            f"SELECT 1 FROM {table_name} WHERE id = ?", (item_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"{item_kind} item is not available: {item_id}.")

    def _execute_insert(
        self,
        sql: str,
        parameters: tuple[object, ...],
        *,
        failure_code: str,
        duplicate_code: str | None = None,
    ) -> None:
        try:
            self._conn.execute(sql, parameters)
        except sqlite3.IntegrityError as exc:
            raise StorageError(
                "Research knowledge fact violates a storage constraint.",
                code=duplicate_code or failure_code,
            ) from exc
        except sqlite3.Error as exc:
            raise StorageError(
                "Failed to save Research knowledge fact.", code=failure_code
            ) from exc
