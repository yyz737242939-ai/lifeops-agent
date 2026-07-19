from __future__ import annotations

import unittest

from app.common.errors import StorageError
from app.common.time import utc_now_iso
from app.domains.research.models import (
    ExternalObservation,
    KnowledgeLink,
    ResearchBriefDraft,
    ResearchRevision,
)
from app.domains.research.ports import FixtureResearchSourcePort
from app.domains.research.repository import ResearchRepository
from app.domains.research.service import ResearchService
from tests.helpers import create_test_connection


class ResearchKnowledgeModelsTest(unittest.TestCase):
    def test_link_rejects_self_reference(self) -> None:
        with self.assertRaises(ValueError):
            KnowledgeLink(
                "link_1", "note", "note_1", "note", "note_1", "related", utc_now_iso()
            )

    def test_revision_requires_positive_version(self) -> None:
        with self.assertRaises(ValueError):
            ResearchRevision(
                "revision_1", "note", "note_1", 0, "body", utc_now_iso()
            )


class ResearchKnowledgeRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = create_test_connection()
        self.repository = ResearchRepository(self.conn)
        self.service = ResearchService(FixtureResearchSourcePort({}), self.repository)

    def tearDown(self) -> None:
        self.conn.close()

    def test_create_topic_note_link_and_append_only_revisions(self) -> None:
        topic = self.service.create_topic("Agent Runtime", "Runtime research")
        note = self.service.create_note("Guardrails", "Safety boundary notes")
        link = self.service.link_items(
            "note", note.note_id, "topic", topic.topic_id, "belongs_to"
        )
        first = self.service.append_revision("note", note.note_id, "first")
        second = self.service.append_revision("note", note.note_id, "second")

        self.assertEqual(link.to_id, topic.topic_id)
        self.assertEqual((first.version, second.version), (1, 2))
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM research_links").fetchone()[0], 1
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM research_revisions").fetchone()[0], 2
        )

    def test_duplicate_topic_and_missing_link_target_fail_closed(self) -> None:
        topic = self.service.create_topic("Agents", "First")
        with self.assertRaises(StorageError) as duplicate:
            self.service.create_topic("Agents", "Second")
        with self.assertRaises(ValueError):
            self.service.link_items(
                "topic", topic.topic_id, "note", "missing_note", "related"
            )

        self.assertEqual(duplicate.exception.code, "research_topic_duplicate")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM research_links").fetchone()[0], 0
        )

    def test_list_topics_is_stable_and_paginated(self) -> None:
        first = self.service.create_topic("First Topic", "First")
        second = self.service.create_topic("Second Topic", "Second")

        page = self.service.list_topics(limit=1, offset=0)
        repeated = self.service.list_topics(limit=1, offset=0)

        self.assertEqual(page, repeated)
        self.assertEqual(len(page), 1)
        self.assertIn(page[0].topic_id, {first.topic_id, second.topic_id})

    def test_brief_draft_stays_temporary_and_saved_brief_keeps_source_order(self) -> None:
        source = self.repository.save_source(
            ExternalObservation(
                "observation_brief",
                "fixture",
                "Source",
                "https://example.com/source",
                "Summary",
                "hash",
                utc_now_iso(),
                "fixture:test",
            )
        )
        draft = ResearchBriefDraft(
            "draft_1",
            "Weekly brief",
            "Source-linked body",
            ("https://example.com/source",),
            "generated-from-saved-sources",
            utc_now_iso(),
        )
        self.service.register_brief_draft(draft)

        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM research_briefs").fetchone()[0], 0
        )
        brief = self.service.save_brief(draft.draft_id)

        row = self.conn.execute(
            "SELECT source_id, position FROM research_brief_sources WHERE brief_id = ?",
            (brief.brief_id,),
        ).fetchone()
        self.assertEqual((row["source_id"], row["position"]), (source.source_id, 0))

    def test_unknown_brief_draft_and_missing_revision_item_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            self.service.save_brief("unknown")
        with self.assertRaises(ValueError):
            self.service.append_revision("note", "missing", "body")

    def test_brief_cannot_persist_until_its_source_urls_are_saved(self) -> None:
        draft = ResearchBriefDraft(
            "draft_unsaved",
            "Unsaved source brief",
            "Temporary body",
            ("https://example.com/not-saved",),
            "request-local:test",
            utc_now_iso(),
        )
        self.service.register_brief_draft(draft)

        with self.assertRaises(ValueError):
            self.service.save_brief(draft.draft_id)

        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM research_briefs").fetchone()[0], 0
        )

    def test_source_refresh_appends_snapshot_and_briefs_pin_snapshot_version(self) -> None:
        first_source = self.repository.save_source(
            ExternalObservation(
                "observation_v1",
                "versioned",
                "Versioned Source",
                "https://example.com/versioned",
                "Version one",
                "version-hash-1",
                "2026-07-11T00:00:00+00:00",
                "fixture:version-1",
            )
        )
        first_brief = self.repository.save_brief(
            ResearchBriefDraft(
                "draft_v1",
                "Brief v1",
                "Uses version one",
                (first_source.url,),
                "fixture:brief-v1",
                utc_now_iso(),
            )
        )
        refreshed_source = self.repository.save_source(
            ExternalObservation(
                "observation_v2",
                "versioned",
                "Versioned Source",
                "https://example.com/versioned",
                "Version two",
                "version-hash-2",
                "2026-07-12T00:00:00+00:00",
                "fixture:version-2",
            )
        )
        second_brief = self.repository.save_brief(
            ResearchBriefDraft(
                "draft_v2",
                "Brief v2",
                "Uses version two",
                (refreshed_source.url,),
                "fixture:brief-v2",
                utc_now_iso(),
            )
        )

        refs = self.conn.execute(
            """SELECT brief_id, snapshot_id FROM research_brief_sources
               WHERE brief_id IN (?, ?) ORDER BY brief_id""",
            (first_brief.brief_id, second_brief.brief_id),
        ).fetchall()
        self.assertEqual(first_source.source_id, refreshed_source.source_id)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM research_sources").fetchone()[0], 1
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM research_source_snapshots"
            ).fetchone()[0],
            2,
        )
        self.assertNotEqual(refs[0]["snapshot_id"], refs[1]["snapshot_id"])


if __name__ == "__main__":
    unittest.main()
