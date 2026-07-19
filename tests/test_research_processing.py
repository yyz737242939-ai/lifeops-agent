from __future__ import annotations

import unittest
from pathlib import Path

from app.common.time import utc_now_iso
from app.domains.research.models import FetchedSourceDocument, ResearchItem
from app.domains.research.processing import (
    dedupe_research_items,
    parse_research_items,
    rank_research_items,
)


FIXTURES = Path("tests/fixtures/research")


class ResearchProcessingTest(unittest.TestCase):
    def test_parses_papers_into_typed_items_and_dedupes_links(self) -> None:
        document = self._document("hf_daily_papers", "hf_daily_papers.html")

        items = parse_research_items(document)

        self.assertEqual(len(items), 2)
        self.assertIsInstance(items[0], ResearchItem)
        self.assertEqual(items[0].title, "Agentic Retrieval for LLM Systems")
        self.assertEqual(items[0].url, "https://huggingface.co/papers/2607.00001")
        self.assertEqual(items[0].topic_hint, "agent")

    def test_parses_blog_with_bounded_limit(self) -> None:
        document = self._document("hf_blog", "hf_blog.html")

        items = parse_research_items(document, limit=1)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source_key, "hf_blog")

    def test_dedupe_and_rank_are_deterministic_without_mutation(self) -> None:
        items = (
            ResearchItem("a", "hf_blog", "First", "https://x/a", 1, score=1),
            ResearchItem("b", "hf_blog", "Second", "https://x/b", 2, score=5),
            ResearchItem("c", "hf_blog", "Duplicate", "https://x/a", 3, score=9),
        )

        deduped = dedupe_research_items(items)
        ranked = rank_research_items(items, limit=1)

        self.assertEqual(tuple(item.item_id for item in deduped), ("a", "b"))
        self.assertEqual(ranked[0].item_id, "b")
        self.assertEqual(items[0].item_id, "a")

    def test_rank_applies_topic_filter_before_limit(self) -> None:
        items = (
            ResearchItem(
                "agent", "hf_blog", "Agent workflows", "https://x/agent", 1, "agent"
            ),
            ResearchItem(
                "vision", "hf_blog", "Vision models", "https://x/vision", 2, "multimodal"
            ),
        )

        ranked = rank_research_items(items, limit=20, topic_filter="agent")

        self.assertEqual(tuple(item.item_id for item in ranked), ("agent",))

    def test_multi_word_topic_filter_can_match_deterministic_topic_hint(self) -> None:
        items = (
            ResearchItem(
                "agent", "hf_blog", "Agent workflows", "https://x/agent", 1, "agent"
            ),
            ResearchItem(
                "vision", "hf_blog", "Vision models", "https://x/vision", 2, "multimodal"
            ),
        )

        ranked = rank_research_items(items, topic_filter="Agent Runtime")

        self.assertEqual(tuple(item.item_id for item in ranked), ("agent",))

    @staticmethod
    def _document(source_key: str, fixture_name: str) -> FetchedSourceDocument:
        return FetchedSourceDocument(
            document_id=f"document_{source_key}",
            observation_id=f"observation_{source_key}",
            source_key=source_key,
            title=source_key,
            url=f"https://huggingface.co/{source_key}",
            content_type="text/html",
            content=(FIXTURES / fixture_name).read_text(encoding="utf-8"),
            content_hash="fixture-hash",
            fetched_at=utc_now_iso(),
            provenance=f"fixture:{source_key}",
        )


if __name__ == "__main__":
    unittest.main()
