import tempfile
import unittest
from pathlib import Path

from app.skills.helper_loader import SkillHelperError, load_skill_helper, run_skill_helper
from app.skills.news.helpers.news_helpers import (
    dedupe_news_items,
    parse_hf_blog,
    parse_hf_daily_papers,
    rank_news_items,
)


class NewsHelperTests(unittest.TestCase):
    def test_parse_hf_daily_papers_outputs_structured_items(self) -> None:
        html = """
        <a href="/papers/2501.00001">Agentic Retrieval for LLMs</a>
        <a href="/papers/2501.00002">Multimodal Video Reasoning</a>
        """

        items = parse_hf_daily_papers(html, 5)

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["source_id"], "hf_daily_papers")
        self.assertEqual(items[0]["title"], "Agentic Retrieval for LLMs")
        self.assertEqual(items[0]["url"], "https://huggingface.co/papers/2501.00001")
        self.assertEqual(items[0]["topic_hint"], "agent")

    def test_parse_hf_blog_outputs_structured_items(self) -> None:
        html = """
        <a href="/blog/smolagents">Smolagents: building agent workflows</a>
        <a href="/blog/vlm">Vision language models in practice</a>
        """

        items = parse_hf_blog(html, 1)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["source_id"], "hf_blog")
        self.assertEqual(items[0]["url"], "https://huggingface.co/blog/smolagents")

    def test_rank_and_dedupe_items(self) -> None:
        items = [
            {"title": "A", "url": "https://x/a", "score_or_votes": 1, "raw_position": 1},
            {"title": "B", "url": "https://x/b", "score_or_votes": 5, "raw_position": 2},
            {"title": "A again", "url": "https://x/a", "score_or_votes": 9, "raw_position": 3},
        ]

        self.assertEqual(len(dedupe_news_items(items)), 2)
        self.assertEqual(rank_news_items(items, 1)[0]["title"], "B")

    def test_run_declared_helper_through_manifest(self) -> None:
        result = run_skill_helper(
            "news",
            "parse_hf_blog",
            {
                "html": '<a href="/blog/test">LLM release notes</a>',
                "limit": 3,
            },
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["helper_id"], "parse_hf_blog")
        self.assertEqual(result["result"][0]["title"], "LLM release notes")

    def test_helper_rejects_unknown_arguments(self) -> None:
        result = run_skill_helper(
            "news",
            "parse_hf_blog",
            {"html": "<html></html>", "limit": 3, "path": "../secret"},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "invalid_arguments")

    def test_helper_must_live_under_skill_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            helpers_dir = Path(temp_dir) / "news" / "helpers"
            helpers_dir.mkdir(parents=True)
            (helpers_dir / "manifest.json").write_text(
                """
                {
                  "helpers": {
                    "bad": {
                      "module": "os",
                      "function": "getcwd",
                      "read_only": true,
                      "timeout_seconds": 3,
                      "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                      }
                    }
                  }
                }
                """,
                encoding="utf-8",
            )

            with self.assertRaises(SkillHelperError) as context:
                load_skill_helper("news", "bad", skills_dir=Path(temp_dir))

            self.assertEqual(context.exception.code, "skill_helper_forbidden")


if __name__ == "__main__":
    unittest.main()
