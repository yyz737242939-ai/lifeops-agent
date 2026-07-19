from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.domains.research.source_manifest import (
    ResearchSourceManifestError,
    load_research_source,
)


class ResearchSourceManifestTest(unittest.TestCase):
    def test_loads_declared_hugging_face_sources(self) -> None:
        skill_root = Path("app/skills/research")

        papers = load_research_source(skill_root, "hf_daily_papers")
        blog = load_research_source(skill_root, "hf_blog")

        self.assertEqual(papers.url, "https://huggingface.co/papers")
        self.assertEqual(blog.url, "https://huggingface.co/blog")
        self.assertEqual(papers.content_type, "html")
        self.assertEqual(papers.relative_path, "sources/hf_daily_papers.json")

    def test_rejects_undeclared_source_key(self) -> None:
        with self.assertRaises(ResearchSourceManifestError) as caught:
            load_research_source(Path("app/skills/research"), "https://example.com")

        self.assertEqual(caught.exception.code, "research_source_not_declared")

    def test_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "sources").mkdir()
            self._write_manifest(root, {"bad": {"path": "../bad.json"}})

            with self.assertRaises(ResearchSourceManifestError) as caught:
                load_research_source(root, "bad")

        self.assertEqual(caught.exception.code, "research_source_forbidden")

    def test_rejects_non_allowlisted_hugging_face_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "sources").mkdir()
            self._write_manifest(root, {"bad": {"path": "sources/bad.json"}})
            (root / "sources" / "bad.json").write_text(
                json.dumps(
                    {
                        "source_key": "bad",
                        "name": "Unexpected Hugging Face page",
                        "url": "https://huggingface.co/settings",
                        "content_type": "html",
                        "description": "Must not be fetchable.",
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ResearchSourceManifestError) as caught:
                load_research_source(root, "bad")

        self.assertEqual(caught.exception.code, "research_source_forbidden")

    @staticmethod
    def _write_manifest(root: Path, sources: dict[str, object]) -> None:
        (root / "sources" / "manifest.json").write_text(
            json.dumps({"sources": sources}), encoding="utf-8"
        )


if __name__ == "__main__":
    unittest.main()
