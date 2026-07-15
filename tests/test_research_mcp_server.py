from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from app.integrations.mcp.client import OneShotStdioMcpClient
from app.integrations.mcp.models import McpServerConfig
from app.integrations.research_mcp.provider import (
    FixturePaperProvider,
    HuggingFacePaperProvider,
    ResearchPaperProviderError,
    validate_search_request,
)
from app.integrations.research_mcp.contracts import SEARCH_PAPERS_INPUT_SCHEMA


FIXTURE_PATH = Path("tests/fixtures/research/hf_papers.json").resolve()


class ResearchMcpProviderTest(unittest.TestCase):
    def test_fixture_provider_filters_and_limits_results(self) -> None:
        provider = FixturePaperProvider(FIXTURE_PATH)

        result = provider.search_papers("MCP", 1)

        self.assertEqual(len(result.papers), 1)
        self.assertEqual(result.papers[0].paper_id, "2601.00002")
        self.assertEqual(result.invalid_count, 0)

    def test_hugging_face_provider_uses_public_read_and_bounds_output(self) -> None:
        class FakeApi:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            def list_papers(self, **kwargs: object) -> list[object]:
                self.calls.append(kwargs)
                return [
                    SimpleNamespace(
                        id="2601.12345",
                        title="  A   Paper  ",
                        authors=[SimpleNamespace(name="Ada")],
                        summary=" summary ",
                        published_at=datetime(2026, 1, 2, tzinfo=UTC),
                    )
                ]

        api = FakeApi()
        provider = HuggingFacePaperProvider(api)

        result = provider.search_papers("agents", 3)

        self.assertEqual(
            api.calls,
            [{"query": "agents", "limit": 3, "token": False}],
        )
        self.assertEqual(result.papers[0].title, "A Paper")
        self.assertEqual(result.papers[0].authors, ["Ada"])
        self.assertEqual(
            result.papers[0].url, "https://huggingface.co/papers/2601.12345"
        )
        self.assertEqual(result.invalid_count, 0)

    def test_hugging_face_provider_keeps_valid_items_and_counts_invalid_items(self) -> None:
        class MixedApi:
            def list_papers(self, **kwargs: object) -> list[object]:
                del kwargs
                return [
                    SimpleNamespace(id=None, title="invalid"),
                    SimpleNamespace(
                        id="2601.12345",
                        title="Valid",
                        authors=[],
                        summary="summary",
                        published_at=None,
                    ),
                ]

        result = HuggingFacePaperProvider(MixedApi()).search_papers("agents", 2)

        self.assertEqual([paper.paper_id for paper in result.papers], ["2601.12345"])
        self.assertEqual(result.invalid_count, 1)

    def test_request_bounds_are_enforced(self) -> None:
        self.assertEqual(validate_search_request(" agents ", 2), ("agents", 2))
        for query, limit in (("", 2), ("x" * 201, 2), ("agents", 0), ("agents", 11)):
            with self.subTest(query=query[:10], limit=limit):
                with self.assertRaises(ValueError):
                    validate_search_request(query, limit)

    def test_provider_network_failure_has_safe_retryable_code(self) -> None:
        class FailingApi:
            def list_papers(self, **kwargs: object) -> list[object]:
                del kwargs
                import httpx

                raise httpx.ConnectError("private endpoint details")

        provider = HuggingFacePaperProvider(FailingApi())
        with self.assertRaises(ResearchPaperProviderError) as caught:
            provider.search_papers("agents", 3)

        self.assertEqual(
            caught.exception.code,
            "research_paper_provider_unavailable",
        )
        self.assertTrue(caught.exception.retryable)
        self.assertNotIn("private", str(caught.exception))


class ResearchMcpServerTransportTest(unittest.TestCase):
    def test_server_exposes_only_search_papers_with_structured_result(self) -> None:
        config = McpServerConfig(
            server_id="research-fixture",
            command=sys.executable,
            args=(
                "-m",
                "app.integrations.research_mcp.server",
                "--fixture",
                str(FIXTURE_PATH),
            ),
            cwd=Path.cwd(),
            timeout_seconds=5.0,
        )

        result = OneShotStdioMcpClient().call_tool(
            config,
            tool_name="search_papers",
            arguments={"query": "agent", "limit": 5},
            expected_input_schema=SEARCH_PAPERS_INPUT_SCHEMA,
        )

        self.assertFalse(result.is_error)
        self.assertEqual(len(result.structured_content["papers"]), 1)
        self.assertEqual(result.structured_content["invalid_count"], 0)
        self.assertEqual(
            result.structured_content["papers"][0]["paper_id"],
            "2601.00001",
        )


if __name__ == "__main__":
    unittest.main()
