from __future__ import annotations

import unittest

from app.policy.models import PolicyAction, PolicyDecision
from app.domains.research.ports import FixtureResearchSourcePort
from app.domains.research.repository import ResearchRepository
from app.domains.research.service import ResearchService
from app.domains.research.tools import (
    FETCH_SOURCE_TOOL,
    SAVE_SOURCE_TOOL,
    build_research_tools,
)
from app.storage.unit_of_work import SqliteUnitOfWork
from app.tools.authorization import resolve_allowed_tools
from app.tools.gateway import ToolGateway
from app.tools.models import AllowedToolSet, ToolCall, ToolCallStatus
from app.tools.registry import ToolRegistry
from tests.helpers import create_test_connection


class ResearchToolsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = create_test_connection()
        service = ResearchService(
            FixtureResearchSourcePort(
                {
                    "hf-daily": {
                        "title": "Daily Papers",
                        "url": "https://huggingface.co/papers",
                        "summary": "A deterministic fixture summary.",
                    }
                }
            ),
            ResearchRepository(self.conn),
        )
        self.registry = ToolRegistry(build_research_tools(service))
        self.gateway = ToolGateway(self.registry)

    def tearDown(self) -> None:
        self.conn.close()

    def test_fetch_is_temporary_then_confirmed_save_persists_with_evidence(self) -> None:
        fetch_result = self.gateway.execute(
            ToolCall("call_fetch", FETCH_SOURCE_TOOL, {"source_key": "hf-daily"}),
            self._allowed("external_read"),
        )

        self.assertEqual(fetch_result.status, ToolCallStatus.SUCCEEDED)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM research_sources").fetchone()[0],
            0,
        )
        observation_id = str(fetch_result.output["observation_id"])
        save_call = ToolCall(
            "call_save",
            SAVE_SOURCE_TOOL,
            {"observation_id": observation_id},
        )

        confirmation = self.gateway.execute(
            save_call,
            self._allowed("write"),
        )
        self.assertEqual(
            confirmation.status, ToolCallStatus.REQUIRES_CONFIRMATION
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM research_sources").fetchone()[0],
            0,
        )

        with SqliteUnitOfWork(self.conn):
            saved = self.gateway.execute(
                save_call,
                self._allowed("write"),
                confirmed_tool_name=SAVE_SOURCE_TOOL,
            )

        self.assertEqual(saved.status, ToolCallStatus.SUCCEEDED)
        self.assertEqual(saved.evidence[0].evidence_type, "research_source_saved")
        row = self.conn.execute(
            "SELECT url, provenance, summary FROM research_sources"
        ).fetchone()
        self.assertEqual(row["url"], "https://huggingface.co/papers")
        self.assertEqual(row["provenance"], "fixture:hf-daily")
        self.assertEqual(row["summary"], "A deterministic fixture summary.")

    def test_undeclared_source_and_unknown_observation_fail_closed(self) -> None:
        missing_source = self.gateway.execute(
            ToolCall("call_fetch", FETCH_SOURCE_TOOL, {"source_key": "unknown"}),
            self._allowed("external_read"),
        )
        missing_observation = self.gateway.execute(
            ToolCall(
                "call_save",
                SAVE_SOURCE_TOOL,
                {"observation_id": "observation_unknown"},
            ),
            self._allowed("write"),
            confirmed_tool_name=SAVE_SOURCE_TOOL,
        )

        self.assertEqual(missing_source.status, ToolCallStatus.FAILED)
        self.assertEqual(missing_observation.status, ToolCallStatus.FAILED)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM research_sources").fetchone()[0],
            0,
        )

    def _allowed(self, effect: str) -> AllowedToolSet:
        return resolve_allowed_tools(
            ("research",),
            PolicyDecision(
                action=PolicyAction.ALLOW,
                allowed_effects=[effect],
            ),
            self.registry,
        )


if __name__ == "__main__":
    unittest.main()
