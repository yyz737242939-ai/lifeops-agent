from __future__ import annotations

import unittest

from app.common.time import utc_now_iso
from app.domains.contracts import (
    DomainContextProvider,
    DomainMemoryCandidateProvider,
    DomainPlanningReadModel,
)
from app.domains.research.models import (
    ExternalObservation,
    ResearchContextCandidate,
    ResearchBriefDraft,
    ResearchMemoryCandidate,
    ResearchPlanningSnapshot,
)
from app.domains.research.read_models import ResearchReadService
from app.domains.research.repository import ResearchRepository
from tests.helpers import create_test_connection


def _planner_consumer(
    read_model: DomainPlanningReadModel[ResearchPlanningSnapshot], topic_id: str
) -> tuple[int, int, int]:
    snapshot = read_model.get_planning_snapshot(topic_id)
    return snapshot.source_count, snapshot.note_count, snapshot.brief_count


def _context_consumer(
    provider: DomainContextProvider[ResearchContextCandidate], query: str, budget: int
) -> tuple[str, ...]:
    return tuple(
        item.item_kind for item in provider.query_context_candidates(query, budget)
    )


def _memory_consumer(
    provider: DomainMemoryCandidateProvider[ResearchMemoryCandidate], query: str
) -> tuple[str, ...]:
    return tuple(
        item.item_kind for item in provider.query_memory_candidates(query, 10)
    )


class ResearchReadModelsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = create_test_connection()
        self.repository = ResearchRepository(self.conn)
        self.read_service = ResearchReadService(self.repository)
        self.topic = self.repository.create_topic("Agent Runtime", "Agent systems")
        self.source = self.repository.save_source(
            ExternalObservation(
                "observation_read",
                "fixture-read",
                "Agent Source",
                "https://example.com/agent-source",
                "Agent runtime source summary",
                "read-hash",
                utc_now_iso(),
                "fixture:read-model",
            )
        )
        self.note = self.repository.create_note(
            "Agent Note", "User-confirmed Agent context note"
        )
        self.brief = self.repository.save_brief(
            ResearchBriefDraft(
                "draft_read",
                "Agent Brief",
                "Agent briefing body",
                (self.source.url,),
                "fixture:brief",
                utc_now_iso(),
            )
        )
        for item_kind, item_id in (
            ("source", self.source.source_id),
            ("note", self.note.note_id),
            ("brief", self.brief.brief_id),
        ):
            relation = "unresolved_question" if item_kind == "note" else "belongs_to"
            self.repository.link_items(
                item_kind, item_id, "topic", self.topic.topic_id, relation
            )

    def tearDown(self) -> None:
        self.conn.close()

    def test_fake_planner_consumer_reads_compact_topic_coverage(self) -> None:
        counts = _planner_consumer(self.read_service, self.topic.topic_id)

        self.assertEqual(counts, (1, 1, 1))
        snapshot = self.read_service.get_planning_snapshot(self.topic.topic_id)
        self.assertEqual(snapshot.recent_brief_titles, ("Agent Brief",))
        self.assertEqual(snapshot.unresolved_questions, ("Agent Note",))

    def test_fake_context_consumer_respects_budget_and_provenance(self) -> None:
        candidates = self.read_service.query_context_candidates("Agent", 120)

        self.assertLessEqual(sum(item.estimated_chars for item in candidates), 120)
        self.assertTrue(all(item.provenance for item in candidates))
        self.assertEqual(
            _context_consumer(self.read_service, "Agent", 120),
            tuple(item.item_kind for item in candidates),
        )

    def test_fake_memory_consumer_exposes_only_confirmed_notes_and_briefs(self) -> None:
        kinds = _memory_consumer(self.read_service, "Agent")

        self.assertIn("note", kinds)
        self.assertIn("brief", kinds)
        self.assertNotIn("source", kinds)

    def test_invalid_read_limits_fail_before_repository_query(self) -> None:
        with self.assertRaises(ValueError):
            self.read_service.query_context_candidates("Agent", 0)
        with self.assertRaises(ValueError):
            self.read_service.query_memory_candidates("Agent", 51)
        with self.assertRaises(ValueError):
            self.read_service.query_context_candidates(
                "Agent", 120, scope_id=self.topic.topic_id
            )


if __name__ == "__main__":
    unittest.main()
