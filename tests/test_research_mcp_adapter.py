from __future__ import annotations

import ast
import unittest
from pathlib import Path

from app.domains.research.ports import ResearchPaperSearchError
from app.integrations.mcp.errors import McpTimeoutError
from app.integrations.mcp.models import McpServerConfig, McpToolCallResult
from app.integrations.research_mcp.adapter import (
    HuggingFaceMcpPaperSearchAdapter,
)


def _paper(**overrides: object) -> dict[str, object]:
    paper: dict[str, object] = {
        "paper_id": "2601.00001",
        "title": "Bounded Agents",
        "authors": ["Ada"],
        "summary": "An agent paper.",
        "published_at": "2026-01-02T00:00:00+00:00",
        "url": "https://huggingface.co/papers/2601.00001",
    }
    paper.update(overrides)
    return paper


class FakeClient:
    def __init__(self, result: McpToolCallResult | Exception) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def call_tool(self, config: McpServerConfig, **kwargs: object) -> McpToolCallResult:
        self.calls.append({"config": config, **kwargs})
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class ResearchMcpAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = McpServerConfig("hf", "python", cwd=Path.cwd())

    def test_maps_and_deduplicates_papers_to_domain_observations(self) -> None:
        result = McpToolCallResult(
            "hf",
            "search_papers",
            {"papers": [_paper(), _paper()], "invalid_count": 0},
        )
        adapter = HuggingFaceMcpPaperSearchAdapter(self.config, FakeClient(result))

        result = adapter.search_papers(" agents ", 3)

        self.assertEqual(result.invalid_count, 0)
        self.assertEqual(len(result.observations), 1)
        observation = result.observations[0]
        self.assertEqual(observation.source_key, "hf_paper")
        self.assertEqual(observation.source_type, "paper")
        self.assertIn("Authors: Ada", observation.summary)
        self.assertEqual(
            observation.provenance,
            "external:mcp:huggingface-papers:2601.00001",
        )
        self.assertEqual(observation.external_id, "2601.00001")
        self.assertEqual(observation.authors, ("Ada",))

    def test_empty_result_is_not_a_failure(self) -> None:
        result = McpToolCallResult(
            "hf", "search_papers", {"papers": [], "invalid_count": 0}
        )
        adapter = HuggingFaceMcpPaperSearchAdapter(self.config, FakeClient(result))

        result = adapter.search_papers("agents", 3)
        self.assertEqual(result.observations, ())
        self.assertEqual(result.invalid_count, 0)

    def test_mixed_valid_and_invalid_papers_return_a_partial_result(self) -> None:
        result = McpToolCallResult(
            "hf",
            "search_papers",
            {"papers": [_paper(), _paper(url="http://bad")], "invalid_count": 1},
        )
        adapter = HuggingFaceMcpPaperSearchAdapter(self.config, FakeClient(result))

        batch = adapter.search_papers("agents", 3)

        self.assertEqual(len(batch.observations), 1)
        self.assertEqual(batch.invalid_count, 2)

    def test_invalid_or_error_result_is_safe_and_typed(self) -> None:
        cases = (
            McpToolCallResult(
                "hf",
                "search_papers",
                {"papers": [_paper(url="http://bad")], "invalid_count": 0},
            ),
            McpToolCallResult("hf", "search_papers", {"papers": [_paper()]}),
            McpToolCallResult("hf", "search_papers", {"papers": []}, is_error=True),
        )
        for result in cases:
            with self.subTest(result=result):
                adapter = HuggingFaceMcpPaperSearchAdapter(
                    self.config, FakeClient(result)
                )
                with self.assertRaises(ResearchPaperSearchError):
                    adapter.search_papers("agents", 3)

    def test_mcp_failure_preserves_code_and_retryability(self) -> None:
        adapter = HuggingFaceMcpPaperSearchAdapter(
            self.config,
            FakeClient(McpTimeoutError("unsafe provider details")),
        )

        with self.assertRaises(ResearchPaperSearchError) as caught:
            adapter.search_papers("agents", 3)

        self.assertEqual(caught.exception.code, "mcp_timeout")
        self.assertTrue(caught.exception.retryable)
        self.assertNotIn("unsafe", str(caught.exception))

    def test_domain_port_does_not_import_mcp_or_hugging_face(self) -> None:
        path = Path("app/domains/research/ports.py")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        self.assertFalse(
            any(name.startswith(("mcp", "huggingface_hub")) for name in imports)
        )


if __name__ == "__main__":
    unittest.main()
