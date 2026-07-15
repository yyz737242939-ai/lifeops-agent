from __future__ import annotations

import unittest

from app.common.time import utc_now_iso
from app.domains.research.models import (
    ExternalObservation,
    FetchedSourceDocument,
    PaperSearchResult,
)
from app.policy.models import PolicyAction, PolicyDecision
from app.domains.research.ports import FixtureResearchSourcePort
from app.domains.research.repository import ResearchRepository
from app.domains.research.service import ResearchService
from app.domains.research.tools import (
    APPEND_REVISION_TOOL,
    BUILD_BRIEF_TOOL,
    CREATE_NOTE_TOOL,
    CREATE_TOPIC_TOOL,
    LINK_ITEMS_TOOL,
    SEARCH_PAPERS_TOOL,
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


class _FakePaperSearchPort:
    def search_papers(
        self, query: str, limit: int
    ) -> PaperSearchResult:
        del query, limit
        return PaperSearchResult((
            ExternalObservation(
                observation_id="paper_observation_tool_test",
                source_key="hf_paper",
                title="Bounded Research Agents",
                url="https://huggingface.co/papers/2601.00001",
                summary="Authors: Ada\n\nAn agent paper.",
                content_hash="paper-fixture-hash",
                fetched_at=utc_now_iso(),
                provenance="external:mcp:huggingface-papers:2601.00001",
                source_type="paper",
                published_at="2026-01-02T00:00:00+00:00",
                external_id="2601.00001",
                authors=("Ada",),
            ),
        ))


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
            paper_search_port=_FakePaperSearchPort(),
        )
        self.registry = ToolRegistry(build_research_tools(self.service))
        self.gateway = ToolGateway(self.registry)

    def tearDown(self) -> None:
        self.conn.close()

    def test_paper_search_is_temporary_then_uses_existing_confirmed_save_chain(self) -> None:
        searched = self.gateway.execute(
            ToolCall(
                "call_search_paper",
                SEARCH_PAPERS_TOOL,
                {"query": "agents", "limit": 3},
            ),
            self._allowed("external_read"),
        )

        self.assertEqual(searched.status, ToolCallStatus.SUCCEEDED)
        self.assertEqual(searched.output["invalid_count"], 0)
        self.assertEqual(
            searched.output["observations"][0]["paper_id"],
            "2601.00001",
        )
        self.assertEqual(searched.output["observations"][0]["authors"], ["Ada"])
        self.assertEqual(
            searched.output["observations"][0]["published_at"],
            "2026-01-02T00:00:00+00:00",
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM research_sources").fetchone()[0],
            0,
        )
        observation_id = searched.output["observations"][0]["observation_id"]
        save_call = ToolCall(
            "call_save_paper", SAVE_SOURCE_TOOL, {"observation_id": observation_id}
        )
        requires_confirmation = self.gateway.execute(
            save_call,
            self._allowed("write"),
        )
        self.assertEqual(
            requires_confirmation.status, ToolCallStatus.REQUIRES_CONFIRMATION
        )
        with SqliteUnitOfWork(self.conn):
            saved = self.gateway.execute(
                save_call,
                self._allowed("write"),
                confirmation=confirmed_action(save_call),
                run_id="run_test",
            )

        self.assertEqual(saved.status, ToolCallStatus.SUCCEEDED)
        row = self.conn.execute(
            "SELECT source_type, url FROM research_sources"
        ).fetchone()
        self.assertEqual(row["source_type"], "paper")
        self.assertEqual(
            row["url"], "https://huggingface.co/papers/2601.00001"
        )

    def test_unknown_observation_fails_closed(self) -> None:
        missing_call = ToolCall(
            "call_save", SAVE_SOURCE_TOOL, {"observation_id": "observation_unknown"}
        )
        missing_observation = self.gateway.execute(
            missing_call,
            self._allowed("write"),
            confirmation=confirmed_action(missing_call),
            run_id="run_test",
        )

        self.assertEqual(missing_observation.status, ToolCallStatus.FAILED)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM research_sources").fetchone()[0],
            0,
        )

    def test_request_local_observation_cannot_cross_execution_scope(self) -> None:
        fetched = self.gateway.execute(
            ToolCall(
                "call_fetch_scope",
                SEARCH_PAPERS_TOOL,
                {"query": "agents", "limit": 3},
            ),
            self._allowed("external_read"),
        )
        isolated_service = ResearchService(
            FixtureResearchSourcePort({}),
            ResearchRepository(self.conn),
            content_port=_FakeContentPort(),
            paper_search_port=_FakePaperSearchPort(),
        )
        isolated_registry = ToolRegistry(build_research_tools(isolated_service))
        isolated_gateway = ToolGateway(isolated_registry)
        save_call = ToolCall(
            "call_save_cross_scope",
            SAVE_SOURCE_TOOL,
            {"observation_id": fetched.output["observations"][0]["observation_id"]},
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

    def test_build_brief_persists_only_after_confirmed_source_and_brief_writes(self) -> None:
        draft = self.gateway.execute(
            ToolCall(
                "call_build",
                BUILD_BRIEF_TOOL,
                {
                    "source_keys": ["hf_daily_papers"],
                    "limit": 5,
                    "topic_filter": "agent",
                },
            ),
            self._allowed("external_read"),
        )

        self.assertEqual(draft.status, ToolCallStatus.SUCCEEDED)
        self.assertEqual(draft.output["item_count"], 1)
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
                {"observation_id": draft.output["source_observation_ids"][0]},
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

    def test_topic_link_and_revision_interfaces_use_confirmation_and_evidence(self) -> None:
        topic_call = ToolCall(
            "call_topic",
            CREATE_TOPIC_TOOL,
            {"name": "Agent Runtime", "description": "Runtime research"},
        )
        pending_topic = self.gateway.execute(topic_call, self._allowed("write"))
        self.assertEqual(pending_topic.status, ToolCallStatus.REQUIRES_CONFIRMATION)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM research_topics").fetchone()[0],
            0,
        )
        with SqliteUnitOfWork(self.conn):
            created_topic = self.gateway.execute(
                topic_call,
                self._allowed("write"),
                confirmation=confirmed_action(topic_call),
                run_id="run_test",
            )
        self.assertEqual(
            created_topic.evidence[0].evidence_type,
            "research_topic_created",
        )
        topic_id = created_topic.output["topic_id"]
        with SqliteUnitOfWork(self.conn):
            note = self.service.create_note("Guardrails", "Boundary notes")

        link_call = ToolCall(
            "call_link",
            LINK_ITEMS_TOOL,
            {
                "from_kind": "note",
                "from_id": note.note_id,
                "to_kind": "topic",
                "to_id": topic_id,
                "relation": "belongs_to",
            },
        )
        with SqliteUnitOfWork(self.conn):
            linked = self.gateway.execute(
                link_call,
                self._allowed("write"),
                confirmation=confirmed_action(link_call),
                run_id="run_test",
            )
        self.assertEqual(linked.evidence[0].evidence_type, "research_items_linked")

        revision_call = ToolCall(
            "call_revision",
            APPEND_REVISION_TOOL,
            {"item_kind": "note", "item_id": note.note_id, "content": "v1"},
        )
        with SqliteUnitOfWork(self.conn):
            revision = self.gateway.execute(
                revision_call,
                self._allowed("write"),
                confirmation=confirmed_action(revision_call),
                run_id="run_test",
            )
        self.assertEqual(revision.output["version"], 1)
        self.assertEqual(
            revision.evidence[0].evidence_type,
            "research_revision_appended",
        )

        topics = self.gateway.execute(
            ToolCall(
                "call_topics",
                SEARCH_KNOWLEDGE_TOOL,
                {"topic_filter": "Agent", "limit": 10, "offset": 0},
            ),
            self._allowed("read"),
        )
        self.assertEqual(topics.status, ToolCallStatus.SUCCEEDED)
        self.assertEqual(topics.output["items"][0]["item_kind"], "topic")
        self.assertEqual(topics.output["items"][0]["item_id"], topic_id)

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
