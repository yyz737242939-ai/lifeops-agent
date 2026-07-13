from __future__ import annotations

import unittest

from app.common.time import utc_now_iso
from app.domains.research.models import FetchedSourceDocument
from app.policy.models import PolicyAction, PolicyDecision
from app.domains.research.ports import FixtureResearchSourcePort
from app.domains.research.repository import ResearchRepository
from app.domains.research.service import ResearchService
from app.domains.research.tools import (
    BUILD_BRIEF_DRAFT_TOOL,
    CREATE_NOTE_TOOL,
    FETCH_BRIEFING_SOURCE_TOOL,
    FETCH_SOURCE_TOOL,
    PARSE_ITEMS_TOOL,
    RANK_ITEMS_TOOL,
    SAVE_BRIEF_TOOL,
    SEARCH_KNOWLEDGE_TOOL,
    SAVE_SOURCE_TOOL,
    build_research_tools,
)
from app.storage.unit_of_work import SqliteUnitOfWork
from app.tools.authorization import resolve_allowed_tools
from app.tools.gateway import ToolGateway
from app.tools.models import AllowedToolSet, ToolCall, ToolCallStatus
from app.tools.registry import ToolRegistry
from tests.helpers import confirmed_action, create_test_connection


class _FakeContentPort:
    def fetch(self, source_key: str) -> FetchedSourceDocument:
        return FetchedSourceDocument(
            document_id="document_tool_test",
            observation_id="observation_tool_test",
            source_key=source_key,
            title="Daily Papers",
            url="https://huggingface.co/papers",
            content_type="text/html",
            content=(
                '<a href="/papers/1">Agent workflow research</a>'
                '<a href="/papers/2">Multimodal vision research</a>'
            ),
            content_hash="fixture-hash",
            fetched_at=utc_now_iso(),
            provenance="fixture:tool-chain",
        )


class ResearchToolsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = create_test_connection()
        self.service = ResearchService(
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
            content_port=_FakeContentPort(),
        )
        self.registry = ToolRegistry(build_research_tools(self.service))
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
                confirmation=confirmed_action(save_call),
                run_id="run_test",
            )

        self.assertEqual(saved.status, ToolCallStatus.SUCCEEDED)
        self.assertEqual(saved.evidence[0].evidence_type, "research_source_saved")
        row = self.conn.execute(
            """SELECT s.url, ss.provenance, ss.summary
               FROM research_sources AS s
               JOIN research_source_snapshots AS ss ON ss.source_id = s.id"""
        ).fetchone()
        self.assertEqual(row["url"], "https://huggingface.co/papers")
        self.assertEqual(row["provenance"], "fixture:hf-daily")
        self.assertEqual(row["summary"], "A deterministic fixture summary.")

    def test_undeclared_source_and_unknown_observation_fail_closed(self) -> None:
        missing_source = self.gateway.execute(
            ToolCall("call_fetch", FETCH_SOURCE_TOOL, {"source_key": "unknown"}),
            self._allowed("external_read"),
        )
        missing_call = ToolCall(
            "call_save", SAVE_SOURCE_TOOL, {"observation_id": "observation_unknown"}
        )
        missing_observation = self.gateway.execute(
            missing_call,
            self._allowed("write"),
            confirmation=confirmed_action(missing_call),
            run_id="run_test",
        )

        self.assertEqual(missing_source.status, ToolCallStatus.FAILED)
        self.assertEqual(missing_observation.status, ToolCallStatus.FAILED)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM research_sources").fetchone()[0],
            0,
        )

    def test_request_local_observation_cannot_cross_execution_scope(self) -> None:
        fetched = self.gateway.execute(
            ToolCall("call_fetch_scope", FETCH_SOURCE_TOOL, {"source_key": "hf-daily"}),
            self._allowed("external_read"),
        )
        isolated_service = ResearchService(
            FixtureResearchSourcePort({}),
            ResearchRepository(self.conn),
            content_port=_FakeContentPort(),
        )
        isolated_registry = ToolRegistry(build_research_tools(isolated_service))
        isolated_gateway = ToolGateway(isolated_registry)
        save_call = ToolCall(
            "call_save_cross_scope",
            SAVE_SOURCE_TOOL,
            {"observation_id": fetched.output["observation_id"]},
        )

        result = isolated_gateway.execute(
            save_call,
            resolve_allowed_tools(
                ("research",),
                PolicyDecision(
                    action=PolicyAction.ALLOW,
                    allowed_effects=["write"],
                ),
                isolated_registry,
            ),
            confirmation=confirmed_action(save_call),
            run_id="run_test",
        )

        self.assertEqual(result.status, ToolCallStatus.FAILED)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM research_sources").fetchone()[0],
            0,
        )

    def test_briefing_chain_persists_only_after_confirmed_source_and_brief_writes(self) -> None:
        fetched = self.gateway.execute(
            ToolCall(
                "call_brief_fetch",
                FETCH_BRIEFING_SOURCE_TOOL,
                {"source_key": "hf_daily_papers"},
            ),
            self._allowed("external_read"),
        )
        parsed = self.gateway.execute(
            ToolCall(
                "call_parse",
                PARSE_ITEMS_TOOL,
                {"document_id": fetched.output["document_id"], "limit": 10},
            ),
            self._allowed("read"),
        )
        ranked = self.gateway.execute(
            ToolCall(
                "call_rank",
                RANK_ITEMS_TOOL,
                {
                    "item_set_id": parsed.output["item_set_id"],
                    "limit": 5,
                    "topic_filter": "agent",
                },
            ),
            self._allowed("read"),
        )
        draft = self.gateway.execute(
            ToolCall(
                "call_build",
                BUILD_BRIEF_DRAFT_TOOL,
                {
                    "item_set_id": ranked.output["item_set_id"],
                    "title": "Hugging Face 简报",
                },
            ),
            self._allowed("read"),
        )

        self.assertEqual(fetched.status, ToolCallStatus.SUCCEEDED)
        self.assertEqual(parsed.status, ToolCallStatus.SUCCEEDED)
        self.assertEqual(ranked.status, ToolCallStatus.SUCCEEDED)
        self.assertEqual(len(ranked.output["items"]), 1)
        self.assertEqual(draft.status, ToolCallStatus.SUCCEEDED)
        self.assertIn("基于 Hugging Face 列表页可见信息", draft.output["body"])
        self.assertIn("https://huggingface.co/papers/1", draft.output["body"])
        self.assertEqual(
            draft.output["source_urls"], ["https://huggingface.co/papers"]
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM research_briefs").fetchone()[0], 0
        )

        save_brief_call = ToolCall(
            "call_save_brief", SAVE_BRIEF_TOOL, {"draft_id": draft.output["draft_id"]}
        )
        confirmation = self.gateway.execute(save_brief_call, self._allowed("write"))
        self.assertEqual(confirmation.status, ToolCallStatus.REQUIRES_CONFIRMATION)

        with SqliteUnitOfWork(self.conn):
            source_call = ToolCall(
                "call_save_brief_source",
                SAVE_SOURCE_TOOL,
                {"observation_id": fetched.output["observation_id"]},
            )
            saved_source = self.gateway.execute(
                source_call,
                self._allowed("write"),
                confirmation=confirmed_action(source_call),
                run_id="run_test",
            )
        with SqliteUnitOfWork(self.conn):
            saved_brief = self.gateway.execute(
                save_brief_call,
                self._allowed("write"),
                confirmation=confirmed_action(save_brief_call),
                run_id="run_test",
            )

        self.assertEqual(saved_source.status, ToolCallStatus.SUCCEEDED)
        self.assertEqual(saved_brief.status, ToolCallStatus.SUCCEEDED)
        self.assertEqual(saved_brief.evidence[0].evidence_type, "research_brief_saved")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM research_briefs").fetchone()[0], 1
        )

    def test_create_note_requires_confirmation_and_returns_evidence(self) -> None:
        call = ToolCall(
            "call_note",
            CREATE_NOTE_TOOL,
            {"title": "Guardrail notes", "body": "WRITE requires confirmation."},
        )

        confirmation = self.gateway.execute(call, self._allowed("write"))
        self.assertEqual(confirmation.status, ToolCallStatus.REQUIRES_CONFIRMATION)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM research_notes").fetchone()[0], 0
        )

        with SqliteUnitOfWork(self.conn):
            saved = self.gateway.execute(
                call,
                self._allowed("write"),
                confirmation=confirmed_action(call),
                run_id="run_test",
            )

        self.assertEqual(saved.status, ToolCallStatus.SUCCEEDED)
        self.assertEqual(saved.evidence[0].evidence_type, "research_note_created")
        row = self.conn.execute("SELECT title, body FROM research_notes").fetchone()
        self.assertEqual(row["title"], "Guardrail notes")

        search = self.gateway.execute(
            ToolCall(
                "call_search",
                SEARCH_KNOWLEDGE_TOOL,
                {
                    "query": "Guardrail",
                    "item_kinds": ["note"],
                    "limit": 10,
                    "offset": 0,
                },
            ),
            self._allowed("read"),
        )
        self.assertEqual(search.status, ToolCallStatus.SUCCEEDED)
        self.assertEqual(search.output["items"][0]["item_kind"], "note")
        self.assertEqual(search.output["next_offset"], 1)

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
