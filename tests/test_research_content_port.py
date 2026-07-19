from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.domains.research.ports import (
    HuggingFaceResearchContentPort,
    MAX_RESEARCH_SOURCE_BYTES,
    ResearchExternalSourceError,
)


class ResearchContentPortTest(unittest.TestCase):
    @patch("app.domains.research.ports.urlopen")
    def test_fetches_declared_html_as_typed_request_local_document(
        self, urlopen_mock: MagicMock
    ) -> None:
        response = self._response(
            b"<html><a href='/papers/1'>Agent paper</a></html>",
            final_url="https://huggingface.co/papers",
        )
        urlopen_mock.return_value = response
        port = HuggingFaceResearchContentPort(self._skill_root())

        document = port.fetch("hf_daily_papers")

        self.assertEqual(document.source_key, "hf_daily_papers")
        self.assertTrue(document.observation_id)
        self.assertEqual(document.url, "https://huggingface.co/papers")
        self.assertEqual(document.content_type, "text/html")
        self.assertIn("Agent paper", document.content)
        request = urlopen_mock.call_args.args[0]
        self.assertEqual(request.full_url, "https://huggingface.co/papers")
        self.assertIn("LifeOps-Agent", request.headers["User-agent"])

    @patch("app.domains.research.ports.urlopen")
    def test_rejects_non_html_and_oversized_responses(
        self, urlopen_mock: MagicMock
    ) -> None:
        port = HuggingFaceResearchContentPort(self._skill_root(), max_bytes=4)
        urlopen_mock.return_value = self._response(b"text", content_type="text/plain")

        with self.assertRaises(ResearchExternalSourceError) as non_html:
            port.fetch("hf_blog")

        urlopen_mock.return_value = self._response(b"12345")
        with self.assertRaises(ResearchExternalSourceError) as oversized:
            port.fetch("hf_blog")

        self.assertEqual(non_html.exception.code, "research_source_content_type_invalid")
        self.assertEqual(oversized.exception.code, "research_source_too_large")

    @patch("app.domains.research.ports.urlopen")
    def test_default_limit_accepts_current_page_scale_and_remains_bounded(
        self, urlopen_mock: MagicMock
    ) -> None:
        current_page_scale = b"x" * 230_000
        urlopen_mock.return_value = self._response(
            current_page_scale,
            final_url="https://huggingface.co/papers",
        )

        document = HuggingFaceResearchContentPort(self._skill_root()).fetch(
            "hf_daily_papers"
        )

        self.assertEqual(len(document.content), len(current_page_scale))
        self.assertEqual(MAX_RESEARCH_SOURCE_BYTES, 500_000)

        urlopen_mock.return_value = self._response(b"x" * (MAX_RESEARCH_SOURCE_BYTES + 1))
        with self.assertRaises(ResearchExternalSourceError) as oversized:
            HuggingFaceResearchContentPort(self._skill_root()).fetch("hf_blog")
        self.assertEqual(oversized.exception.code, "research_source_too_large")

    @patch("app.domains.research.ports.urlopen")
    def test_rejects_redirect_away_from_declared_url(
        self, urlopen_mock: MagicMock
    ) -> None:
        response = self._response(b"<html>redirected</html>")
        response.geturl.return_value = "https://example.com/captured"
        urlopen_mock.return_value = response

        with self.assertRaises(ResearchExternalSourceError) as caught:
            HuggingFaceResearchContentPort(self._skill_root()).fetch("hf_blog")

        self.assertEqual(caught.exception.code, "research_source_redirect_forbidden")

    @staticmethod
    def _response(
        raw: bytes,
        *,
        content_type: str = "text/html; charset=utf-8",
        final_url: str = "https://huggingface.co/blog",
    ) -> MagicMock:
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.headers.get.return_value = content_type
        response.headers.get_content_charset.return_value = "utf-8"
        response.read.return_value = raw
        response.geturl.return_value = final_url
        return response

    @staticmethod
    def _skill_root():
        from pathlib import Path

        return Path("app/skills/research")


if __name__ == "__main__":
    unittest.main()
