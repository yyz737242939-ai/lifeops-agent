from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from app.common.time import utc_now_iso
from app.domains.research.models import FetchedSourceDocument
from app.domains.research.ports import FixtureResearchSourcePort
from app.domains.research.repository import ResearchRepository
from app.domains.research.service import ResearchService
from app.domains.research.tools import (
    FETCH_BRIEFING_SOURCE_TOOL,
    FETCH_SOURCE_TOOL,
    SAVE_SOURCE_TOOL,
    build_research_tools,
)
from app.domains.travel.adapters import FixturePlaceSearchAdapter
from app.domains.travel.repository import TravelRepository
from app.domains.travel.service import TravelService
from app.domains.travel.tools import (
    SAVE_ITINERARY_TOOL,
    SEARCH_PLACES_TOOL,
    build_travel_tools,
)
from app.intent.models import IntentDecision, IntentType
from app.orchestration.graph import RuntimeOrchestrator
from app.policy.models import PolicyAction, PolicyDecision
from app.runtime.models import RuntimeRequest, RuntimeStatus
from app.skills.loader import discover_skills
from app.skills.models import SkillDefinition
from app.skills.registry import SkillRegistry
from app.skills.service import SkillService
from app.tools.models import ToolCall
from app.tools.registry import ToolRegistry
from app.tools.runtime import ToolRuntime
from tests.helpers import create_test_connection


class Stage5GraphE2ETest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = create_test_connection()
        self.trace = RecordingTraceSink()

    def tearDown(self) -> None:
        self.conn.close()

    def test_graph_executes_authorized_domain_tool_through_guardrails(self) -> None:
        orchestrator = self._orchestrator(
            ToolCall("call_fetch", FETCH_SOURCE_TOOL, {"source_key": "hf-daily"})
        )

        state = orchestrator.invoke(_request(), trace=self.trace)

        self.assertEqual(
            state["graph_path"],
            [
                "classify_intent",
                "decide_policy",
                "prepare_skills",
                "execute_tool",
                "finalize",
            ],
        )
        self.assertEqual(state["result"].status, RuntimeStatus.OK)
        self.assertEqual(
            state["result"].tool_result["tool_name"], FETCH_SOURCE_TOOL
        )
        self.assertEqual(
            state["result"].tool_result["output"]["source_key"], "hf-daily"
        )
        self.assertEqual(
            [event for event, _ in self.trace.events][-4:],
            [
                "tool.call.requested",
                "tool.guardrail.decided",
                "tool.guardrail.decided",
                "tool.call.completed",
            ],
        )

    def test_graph_guardrail_rejects_call_hidden_by_policy(self) -> None:
        orchestrator = self._orchestrator(
            ToolCall("call_save", SAVE_SOURCE_TOOL, {"observation_id": "forged"})
        )

        state = orchestrator.invoke(_request(), trace=self.trace)

        self.assertEqual(state["result"].status, RuntimeStatus.UNSUPPORTED)
        self.assertEqual(
            state["result"].tool_result["error"]["code"], "tool_not_allowed"
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM research_sources").fetchone()[0],
            0,
        )
        guardrail_events = [
            payload
            for event, payload in self.trace.events
            if event == "tool.guardrail.decided"
        ]
        self.assertEqual(len(guardrail_events), 1)
        self.assertEqual(guardrail_events[0]["action"], "deny")
        self.assertEqual(guardrail_events[0]["reason_code"], "tool_not_allowed")

    def test_graph_executes_real_briefing_handler_without_exposing_raw_html(self) -> None:
        orchestrator = self._orchestrator(
            ToolCall(
                "call_briefing_fetch",
                FETCH_BRIEFING_SOURCE_TOOL,
                {"source_key": "hf_daily_papers"},
            )
        )

        state = orchestrator.invoke(_request(), trace=self.trace)

        result = state["result"].tool_result
        self.assertEqual(state["result"].status, RuntimeStatus.OK)
        self.assertEqual(result["tool_name"], FETCH_BRIEFING_SOURCE_TOOL)
        self.assertEqual(result["output"]["source_key"], "hf_daily_papers")
        self.assertIn("document_id", result["output"])
        self.assertIn("observation_id", result["output"])
        self.assertNotIn("content", result["output"])
        self.assertNotIn("Agent fixture body", repr(result))

    def test_graph_executes_real_travel_handler_with_typed_observation(self) -> None:
        orchestrator = self._travel_orchestrator(
            ToolCall(
                "call_places",
                SEARCH_PLACES_TOOL,
                {"destination": "Tokyo", "query": "historic places"},
            )
        )

        state = orchestrator.invoke(_request(), trace=self.trace)

        result = state["result"].tool_result
        self.assertEqual(state["result"].status, RuntimeStatus.OK)
        self.assertEqual(result["tool_name"], SEARCH_PLACES_TOOL)
        self.assertEqual(result["output"]["status"], "success")
        self.assertTrue(result["output"]["candidates"])
        self.assertIn("provenance", result["output"]["observation"])
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM travel_itineraries").fetchone()[0],
            0,
        )

    def test_graph_rejects_travel_write_hidden_by_external_read_policy(self) -> None:
        orchestrator = self._travel_orchestrator(
            ToolCall(
                "call_save_travel",
                SAVE_ITINERARY_TOOL,
                {"draft_id": "forged", "idempotency_key": "forged"},
            )
        )

        state = orchestrator.invoke(_request(), trace=self.trace)

        self.assertEqual(state["result"].status, RuntimeStatus.UNSUPPORTED)
        self.assertEqual(
            state["result"].tool_result["error"]["code"], "tool_not_allowed"
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM travel_itineraries").fetchone()[0],
            0,
        )

    def _orchestrator(self, call: ToolCall) -> RuntimeOrchestrator:
        skill_registry = SkillRegistry(discover_skills(Path("app/skills")))
        return RuntimeOrchestrator(
            skill_service=SkillService(skill_registry, ResearchSkillSelectionClient()),
            intent_service=ReadIntentService(),
            policy_service=ExternalReadPolicyService(),
            tool_runtime_factory=self._tool_runtime,
            tool_call_selection_client=FixedToolCallSelectionClient(call),
        )

    def _tool_runtime(self) -> ToolRuntime:
        service = ResearchService(
            FixtureResearchSourcePort(
                {
                    "hf-daily": {
                        "title": "HF Daily",
                        "url": "https://huggingface.co/papers",
                        "summary": "Fixture research summary.",
                    }
                }
            ),
            ResearchRepository(self.conn),
            content_port=_FixtureBriefingContentPort(),
        )
        return ToolRuntime.from_registry(ToolRegistry(build_research_tools(service)))

    def _travel_orchestrator(self, call: ToolCall) -> RuntimeOrchestrator:
        skill_registry = SkillRegistry(discover_skills(Path("app/skills")))
        return RuntimeOrchestrator(
            skill_service=SkillService(skill_registry, TravelSkillSelectionClient()),
            intent_service=ReadIntentService(),
            policy_service=ExternalReadPolicyService(),
            tool_runtime_factory=self._travel_tool_runtime,
            tool_call_selection_client=FixedToolCallSelectionClient(call),
        )

    def _travel_tool_runtime(self) -> ToolRuntime:
        root = Path("tests/fixtures/travel")
        service = TravelService(
            TravelRepository(self.conn),
            place_port=FixturePlaceSearchAdapter(
                root / "places_tokyo.json", root / "provider_failures.json"
            ),
        )
        return ToolRuntime.from_registry(ToolRegistry(build_travel_tools(service)))


class ResearchSkillSelectionClient:
    def select(
        self,
        request: RuntimeRequest,
        skill_metadata: tuple[SkillDefinition, ...],
    ) -> dict[str, Any]:
        return {"selected_skill_ids": ["research"], "reason": "Research applies."}


class TravelSkillSelectionClient:
    def select(
        self,
        request: RuntimeRequest,
        skill_metadata: tuple[SkillDefinition, ...],
    ) -> dict[str, Any]:
        return {"selected_skill_ids": ["travel"], "reason": "Travel applies."}


class _FixtureBriefingContentPort:
    def fetch(self, source_key: str) -> FetchedSourceDocument:
        return FetchedSourceDocument(
            document_id="document_graph_briefing",
            observation_id="observation_graph_briefing",
            source_key=source_key,
            title="Hugging Face Daily Papers",
            url="https://huggingface.co/papers",
            content_type="text/html",
            content='<a href="/papers/1">Agent fixture body</a>',
            content_hash="graph-briefing-hash",
            fetched_at=utc_now_iso(),
            provenance="fixture:graph-briefing",
        )


class FixedToolCallSelectionClient:
    def __init__(self, call: ToolCall) -> None:
        self._call = call

    def select(self, request, prompt_contributions, tool_catalog):
        return self._call


class ReadIntentService:
    def classify(self, request: RuntimeRequest) -> IntentDecision:
        return IntentDecision(intent_type=IntentType.READ, confidence=1.0)


class ExternalReadPolicyService:
    def evaluate(
        self,
        request: RuntimeRequest,
        intent: IntentDecision,
    ) -> PolicyDecision:
        return PolicyDecision(
            action=PolicyAction.ALLOW,
            allowed_effects=["external_read"],
        )


class RecordingTraceSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any] | None]] = []

    def append(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        self.events.append((event_type, payload))


def _request() -> RuntimeRequest:
    return RuntimeRequest(
        user_input="Fetch the declared research source.",
        session_id="session_stage5_e2e",
    )


if __name__ == "__main__":
    unittest.main()
