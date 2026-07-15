from __future__ import annotations

import sys
import unittest
from pathlib import Path

from app.domains.research.ports import FixtureResearchSourcePort
from app.domains.research.repository import ResearchRepository
from app.domains.research.service import ResearchService
from app.domains.research.tools import SEARCH_PAPERS_TOOL, build_research_tools
from app.integrations.mcp.models import McpServerConfig
from app.integrations.research_mcp.adapter import HuggingFaceMcpPaperSearchAdapter
from app.policy.models import PolicyAction, PolicyDecision
from app.tools.authorization import resolve_allowed_tools
from app.tools.gateway import ToolGateway
from app.tools.models import ToolCall, ToolCallStatus
from app.tools.registry import ToolRegistry
from tests.helpers import create_test_connection


class ResearchMcpFailureBoundaryTest(unittest.TestCase):
    def test_real_mcp_provider_failure_is_typed_and_writes_nothing(self) -> None:
        conn = create_test_connection()
        try:
            adapter = HuggingFaceMcpPaperSearchAdapter(
                McpServerConfig(
                    server_id="hf-failure-fixture",
                    command=sys.executable,
                    args=(
                        "-m",
                        "app.integrations.research_mcp.server",
                        "--fixture-error",
                        "research_paper_rate_limited",
                    ),
                    cwd=Path.cwd(),
                    timeout_seconds=5.0,
                )
            )
            service = ResearchService(
                FixtureResearchSourcePort({}),
                ResearchRepository(conn),
                paper_search_port=adapter,
            )
            registry = ToolRegistry(build_research_tools(service))
            result = ToolGateway(registry).execute(
                ToolCall(
                    "call_provider_failure",
                    SEARCH_PAPERS_TOOL,
                    {"query": "private query", "limit": 3},
                ),
                resolve_allowed_tools(
                    ("research",),
                    PolicyDecision(
                        action=PolicyAction.ALLOW,
                        allowed_effects=["external_read"],
                    ),
                    registry,
                ),
            )

            self.assertEqual(result.status, ToolCallStatus.FAILED)
            self.assertEqual(result.error.code, "research_paper_rate_limited")
            for table in (
                "research_sources",
                "research_source_snapshots",
                "research_links",
                "research_revisions",
            ):
                with self.subTest(table=table):
                    count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    self.assertEqual(count, 0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
