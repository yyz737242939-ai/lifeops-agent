import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.skills.source_loader import (
    SkillSourceError,
    fetch_skill_source,
    load_skill_source,
)


class NewsSourceManifestTests(unittest.TestCase):
    def test_loads_declared_hugging_face_sources(self) -> None:
        papers = load_skill_source("news", "hf_daily_papers")
        blog = load_skill_source("news", "hf_blog")

        self.assertEqual(papers.url, "https://huggingface.co/papers")
        self.assertEqual(blog.url, "https://huggingface.co/blog")
        self.assertEqual(papers.kind, "html")
        self.assertTrue(papers.allowed)

    def test_rejects_undeclared_source_id(self) -> None:
        with self.assertRaises(SkillSourceError) as context:
            load_skill_source("news", "https://example.com")

        self.assertEqual(context.exception.code, "skill_source_not_found")

    def test_rejects_non_allowlisted_manifest_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sources_dir = Path(temp_dir) / "news" / "sources"
            sources_dir.mkdir(parents=True)
            (sources_dir / "bad.yaml").write_text(
                "\n".join(
                    [
                        "id: bad",
                        "name: Bad",
                        "url: https://example.com/news",
                        "kind: html",
                        "allowed: true",
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaises(SkillSourceError) as context:
                load_skill_source("news", "bad", skills_dir=Path(temp_dir))

            self.assertEqual(context.exception.code, "skill_source_forbidden")

    @patch("app.skills.source_loader.urlopen")
    def test_fetch_reads_declared_source_with_size_limit(self, urlopen_mock) -> None:
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.headers.get.return_value = "text/html; charset=utf-8"
        response.headers.get_content_charset.return_value = "utf-8"
        response.read.return_value = b"<html>ok</html>"
        urlopen_mock.return_value = response

        result = fetch_skill_source("news", "hf_daily_papers")

        self.assertTrue(result["ok"])
        self.assertEqual(result["source_id"], "hf_daily_papers")
        self.assertEqual(result["url"], "https://huggingface.co/papers")
        self.assertEqual(result["content"], "<html>ok</html>")
        request = urlopen_mock.call_args.args[0]
        self.assertEqual(request.full_url, "https://huggingface.co/papers")
        self.assertIn("LifeOps-Agent", request.headers["User-agent"])


if __name__ == "__main__":
    unittest.main()
