from __future__ import annotations

import unittest
import sys
from pathlib import Path
from typing import Any, Callable

from app.common.time import utc_now_iso
from app.domains.research.models import FetchedSourceDocument
from app.domains.research.ports import FixtureResearchSourcePort
from app.domains.research.repository import ResearchRepository
from app.domains.research.service import ResearchService
from app.domains.research.tools import (
    BUILD_BRIEF_TOOL,
    CREATE_NOTE_TOOL,
    SEARCH_KNOWLEDGE_TOOL,
    SEARCH_PAPERS_TOOL,
    build_research_tools,
)
from app.integrations.mcp.models import McpServerConfig
from app.integrations.research_mcp.adapter import HuggingFaceMcpPaperSearchAdapter
from app.domains.travel.adapters import FixturePlaceSearchAdapter
from app.domains.travel.repository import TravelRepository
from app.domains.travel.service import TravelService
from app.domains.travel.tools import (
    BUILD_ITINERARY_DRAFT_TOOL,
    COMPARE_OPTIONS_TOOL,
    CREATE_TRIP_TOOL,
    SAVE_ITINERARY_TOOL,
    SEARCH_PLACES_TOOL,
    build_travel_tools,
)
from app.executor.models import (
    ExecutionLimits,
    ExecutorModelInput,
    FinalAnswerDecision,
    ToolActionDecision,
)
from app.executor.service import ReactExecutor
from app.intent.models import IntentDecision, IntentType
from app.orchestration.graph import RuntimeOrchestrator
from app.policy.models import PolicyAction, PolicyDecision
from app.runtime.models import RuntimeRequest, RuntimeStatus
from app.skills.loader import discover_skills
from app.skills.models import SkillDefinition
from app.skills.registry import SkillRegistry
from app.skills.service import SkillService
from app.storage.unit_of_work import SqliteUnitOfWork
from app.tools.models import ConfirmedAction, ToolCall, ToolCallStatus
from app.tools.registry import ToolRegistry
from app.tools.runtime import ToolRuntime
from tests.helpers import create_test_connection


DecisionFactory = Callable[[ExecutorModelInput], ToolActionDecision | FinalAnswerDecision]


class ExecutorCrossDomainCompiledE2ETest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = create_test_connection()
        self.trace = _RecordingTraceSink()

    def tearDown(self) -> None:
        self.conn.close()

    def test_research_build_brief_runs_in_one_compiled_scope(self) -> None:
        def decide(model_input: ExecutorModelInput):
            observations = model_input.observations
            if not observations:
                return _action(
                    "research_brief",
                    BUILD_BRIEF_TOOL,
                    {
                        "source_keys": ["hf_daily_papers"],
                        "limit": 5,
                        "topic_filter": "agent",
                    },
                )
            return FinalAnswerDecision("Research draft completed.")

        state, model = self._invoke(decide, effects=("read", "external_read"))

        self.assertEqual(state["result"].status, RuntimeStatus.OK)
        self.assertEqual(len(model.inputs[-1].observations), 1)
        draft = model.inputs[-1].observations[-1]
        self.assertEqual(draft.status, ToolCallStatus.SUCCEEDED)
        self.assertIn("基于 Hugging Face 列表页可见信息", draft.output["body"])
        self.assertEqual(self._count("research_briefs"), 0)

    def test_travel_search_compare_and_draft_run_in_one_compiled_scope(self) -> None:
        runtime, trip_id = self._runtime_with_seeded_trip()

        def decide(model_input: ExecutorModelInput):
            observations = model_input.observations
            if not observations:
                return _action(
                    "travel_search",
                    SEARCH_PLACES_TOOL,
                    {"destination": "Tokyo", "query": "historic places"},
                )
            output = observations[-1].output or {}
            if len(observations) == 1:
                return _action(
                    "travel_compare",
                    COMPARE_OPTIONS_TOOL,
                    {
                        "trip_id": trip_id,
                        "observation_ids": [output["observation"]["observation_id"]],
                    },
                )
            if len(observations) == 2:
                return _action(
                    "travel_draft",
                    BUILD_ITINERARY_DRAFT_TOOL,
                    {
                        "comparison_id": output["comparison_id"],
                        "candidate_ids": [output["assessments"][0]["candidate_id"]],
                        "summary": "Tokyo planning draft.",
                    },
                )
            return FinalAnswerDecision("Travel draft completed.")

        state, model = self._invoke(
            decide,
            effects=("read", "external_read"),
            runtime=runtime,
        )

        self.assertEqual(state["result"].status, RuntimeStatus.OK)
        self.assertEqual(len(model.inputs[-1].observations), 3)
        self.assertEqual(
            model.inputs[-1].observations[-1].tool_name,
            BUILD_ITINERARY_DRAFT_TOOL,
        )
        self.assertEqual(self._count("travel_itineraries"), 0)

    def test_same_run_can_sequence_research_read_then_travel_read(self) -> None:
        def decide(model_input: ExecutorModelInput):
            if not model_input.observations:
                return _action(
                    "cross_research",
                    SEARCH_PAPERS_TOOL,
                    {"query": "agent", "limit": 3},
                )
            if len(model_input.observations) == 1:
                return _action(
                    "cross_travel",
                    SEARCH_PLACES_TOOL,
                    {"destination": "Tokyo", "query": "historic places"},
                )
            return FinalAnswerDecision("Cross-domain reads completed.")

        state, model = self._invoke(decide, effects=("external_read",))

        observations = model.inputs[-1].observations
        self.assertEqual(state["result"].status, RuntimeStatus.OK)
        self.assertEqual(
            [item.tool_name for item in observations],
            [SEARCH_PAPERS_TOOL, SEARCH_PLACES_TOOL],
        )
        self.assertEqual(self._count("research_sources"), 0)
        self.assertEqual(self._count("travel_itineraries"), 0)

    def test_two_domain_writes_each_require_an_exact_confirmation(self) -> None:
        confirmation = _ConfirmEveryWrite()

        def decide(model_input: ExecutorModelInput):
            if not model_input.observations:
                return _action(
                    "write_research",
                    CREATE_NOTE_TOOL,
                    {"title": "Confirmed note", "body": "Evidence-backed body."},
                )
            if len(model_input.observations) == 1:
                return _action(
                    "write_travel",
                    CREATE_TRIP_TOOL,
                    {"title": "Confirmed trip"},
                )
            return FinalAnswerDecision("Both writes completed.")

        state, model = self._invoke(
            decide,
            effects=("write",),
            confirmation_provider=confirmation,
        )

        self.assertEqual(state["result"].status, RuntimeStatus.OK)
        self.assertEqual(confirmation.call_ids, ["write_research", "write_travel"])
        self.assertTrue(
            all(item.evidence for item in model.inputs[-1].observations)
        )
        self.assertEqual(self._count("research_notes"), 1)
        self.assertEqual(self._count("trips"), 1)

    def test_unconfirmed_write_stops_with_zero_domain_writes(self) -> None:
        state, _ = self._invoke(
            lambda _: _action(
                "unconfirmed_note",
                CREATE_NOTE_TOOL,
                {"title": "Must not persist", "body": "No confirmation."},
            ),
            effects=("write",),
        )

        self.assertEqual(state["result"].status, RuntimeStatus.REQUIRES_CONFIRMATION)
        self.assertEqual(self._count("research_notes"), 0)
        self.assertEqual(self._count("trips"), 0)

    def test_failed_temporary_id_can_be_observed_before_alternate_action(self) -> None:
        def decide(model_input: ExecutorModelInput):
            if not model_input.observations:
                return _action(
                    "empty_brief",
                    BUILD_BRIEF_TOOL,
                    {
                        "source_keys": ["hf_daily_papers"],
                        "limit": 5,
                        "topic_filter": "does-not-match",
                    },
                )
            if len(model_input.observations) == 1:
                self.assertEqual(
                    model_input.observations[0].status, ToolCallStatus.FAILED
                )
                return _action(
                    "fallback_search",
                    SEARCH_PAPERS_TOOL,
                    {"query": "agent", "limit": 3},
                )
            return FinalAnswerDecision("Recovered with an alternate read.")

        state, model = self._invoke(decide, effects=("read", "external_read"))

        self.assertEqual(state["result"].status, RuntimeStatus.OK)
        self.assertEqual(
            [item.status for item in model.inputs[-1].observations],
            [ToolCallStatus.FAILED, ToolCallStatus.SUCCEEDED],
        )
        self.assertEqual(self._count("research_sources"), 0)

    def test_catalog_denial_and_step_limit_fail_closed(self) -> None:
        denied, _ = self._invoke(
            lambda _: _action(
                "hidden_write",
                CREATE_NOTE_TOOL,
                {"title": "Hidden", "body": "Must not run."},
            ),
            effects=("read",),
        )
        self.assertEqual(denied["result"].status, RuntimeStatus.UNSUPPORTED)

        def always_read(model_input: ExecutorModelInput):
            return _action(
                f"bounded_{model_input.step_index}",
                SEARCH_KNOWLEDGE_TOOL,
                {"query": "none", "item_kinds": ["note"], "limit": 1, "offset": 0},
            )

        limited, model = self._invoke(
            always_read,
            effects=("read",),
            limits=ExecutionLimits(max_steps=2),
        )
        self.assertEqual(limited["result"].status, RuntimeStatus.ERROR)
        self.assertEqual(limited["result"].error_code, "executor.limit_reached")
        self.assertEqual(len(model.inputs), 2)
        self.assertEqual(self._count("research_notes"), 0)

    def test_partial_and_expired_travel_results_remain_read_only(self) -> None:
        for scenario, expected_status in (
            ("partial_failure", "partial_failure"),
            ("expired", "failed"),
        ):
            with self.subTest(scenario=scenario):
                runtime = self._combined_runtime(place_scenario=scenario)

                def decide(model_input: ExecutorModelInput):
                    if not model_input.observations:
                        return _action(
                            f"places_{scenario}",
                            SEARCH_PLACES_TOOL,
                            {"destination": "Tokyo", "query": "historic places"},
                        )
                    return FinalAnswerDecision(f"Observed {scenario} safely.")

                state, model = self._invoke(
                    decide,
                    effects=("external_read",),
                    runtime=runtime,
                )
                self.assertEqual(state["result"].status, RuntimeStatus.OK)
                self.assertEqual(
                    model.inputs[-1].observations[0].output["status"],
                    expected_status,
                )
                self.assertEqual(self._count("travel_itineraries"), 0)

    def test_confirmed_itinerary_save_is_idempotent_inside_compiled_loop(self) -> None:
        runtime, trip_id = self._runtime_with_seeded_trip()
        confirmation = _ConfirmEveryWrite()

        def decide(model_input: ExecutorModelInput):
            observations = model_input.observations
            if not observations:
                return _action(
                    "idem_search",
                    SEARCH_PLACES_TOOL,
                    {"destination": "Tokyo", "query": "historic places"},
                )
            output = observations[-1].output or {}
            if len(observations) == 1:
                return _action(
                    "idem_compare",
                    COMPARE_OPTIONS_TOOL,
                    {
                        "trip_id": trip_id,
                        "observation_ids": [output["observation"]["observation_id"]],
                    },
                )
            if len(observations) == 2:
                return _action(
                    "idem_draft",
                    BUILD_ITINERARY_DRAFT_TOOL,
                    {
                        "comparison_id": output["comparison_id"],
                        "candidate_ids": [output["assessments"][0]["candidate_id"]],
                        "summary": "Idempotent Tokyo draft.",
                    },
                )
            if len(observations) in (3, 4):
                draft_id = (
                    output["draft_id"]
                    if len(observations) == 3
                    else observations[2].output["draft_id"]
                )
                return _action(
                    f"idem_save_{len(observations) - 2}",
                    SAVE_ITINERARY_TOOL,
                    {"draft_id": draft_id, "idempotency_key": "compiled-idem-v1"},
                )
            return FinalAnswerDecision("Idempotent save completed.")

        state, model = self._invoke(
            decide,
            effects=("read", "external_read", "write"),
            runtime=runtime,
            confirmation_provider=confirmation,
        )

        self.assertEqual(state["result"].status, RuntimeStatus.OK)
        saves = model.inputs[-1].observations[-2:]
        self.assertEqual(saves[0].output, saves[1].output)
        self.assertEqual(confirmation.call_ids, ["idem_save_1", "idem_save_2"])
        self.assertEqual(self._count("travel_itineraries"), 1)
        self.assertEqual(self._count("travel_decisions"), 1)

    def _invoke(
        self,
        decision_factory: DecisionFactory,
        *,
        effects: tuple[str, ...],
        runtime: ToolRuntime | None = None,
        confirmation_provider=None,
        limits: ExecutionLimits | None = None,
    ):
        model = _WorkflowModelClient(decision_factory)
        runtime = runtime or self._combined_runtime()
        skills = SkillRegistry(discover_skills(Path("app/skills")))
        orchestrator = RuntimeOrchestrator(
            skill_service=SkillService(skills, _BothDomainSkillSelectionClient()),
            intent_service=_ReadIntentService(),
            policy_service=_FixedPolicyService(effects),
            execution_scope_factory=lambda: runtime,
            executor=ReactExecutor(
                model,
                limits=limits,
                confirmation_provider=confirmation_provider,
            ),
        )
        state = orchestrator.invoke(
            RuntimeRequest(
                user_input="Run the deterministic compiled workflow.",
                session_id="session_executor_cross_domain",
            ),
            trace=self.trace,
        )
        return state, model

    def _combined_runtime(self, *, place_scenario: str | None = None) -> ToolRuntime:
        research = ResearchService(
            FixtureResearchSourcePort(
                {
                    "hf-daily": {
                        "title": "HF Daily",
                        "url": "https://huggingface.co/papers",
                        "summary": "Deterministic Research fixture.",
                    }
                }
            ),
            ResearchRepository(self.conn),
            content_port=_FixtureBriefingContentPort(),
            paper_search_port=HuggingFaceMcpPaperSearchAdapter(
                McpServerConfig(
                    server_id="cross-domain-hf-fixture",
                    command=sys.executable,
                    args=(
                        "-m",
                        "app.integrations.research_mcp.server",
                        "--fixture",
                        str(Path("tests/fixtures/research/hf_papers.json").resolve()),
                    ),
                    cwd=Path.cwd(),
                    timeout_seconds=5.0,
                )
            ),
        )
        root = Path("tests/fixtures/travel")
        place_options = (
            {"scenario": place_scenario} if place_scenario is not None else {}
        )
        travel = TravelService(
            TravelRepository(self.conn),
            place_port=FixturePlaceSearchAdapter(
                root / "places_tokyo.json",
                root / "provider_failures.json",
                **place_options,
            ),
        )
        registry = ToolRegistry(
            (*build_research_tools(research), *build_travel_tools(travel))
        )
        return ToolRuntime.from_registry(registry)

    def _runtime_with_seeded_trip(self) -> tuple[ToolRuntime, str]:
        runtime = self._combined_runtime()
        travel_handler = runtime.registry.resolve(CREATE_TRIP_TOOL).handler
        with SqliteUnitOfWork(self.conn):
            result = travel_handler(
                ToolCall("seed_trip", CREATE_TRIP_TOOL, {"title": "Tokyo planning"})
            )
        return runtime, result.output["trip_id"]

    def _count(self, table: str) -> int:
        return self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class _WorkflowModelClient:
    def __init__(self, decision_factory: DecisionFactory) -> None:
        self._decision_factory = decision_factory
        self.inputs: list[ExecutorModelInput] = []

    def decide(self, model_input: ExecutorModelInput):
        self.inputs.append(model_input)
        return self._decision_factory(model_input)


class _BothDomainSkillSelectionClient:
    def select(
        self,
        request: RuntimeRequest,
        skill_metadata: tuple[SkillDefinition, ...],
    ) -> dict[str, Any]:
        return {
            "selected_skill_ids": ["research", "travel"],
            "reason": "Both fixture-backed domains apply.",
        }


class _ReadIntentService:
    def classify(self, request: RuntimeRequest) -> IntentDecision:
        return IntentDecision(IntentType.READ, 1.0)


class _FixedPolicyService:
    def __init__(self, effects: tuple[str, ...]) -> None:
        self._effects = effects

    def evaluate(
        self,
        request: RuntimeRequest,
        intent: IntentDecision,
    ) -> PolicyDecision:
        return PolicyDecision(PolicyAction.ALLOW, allowed_effects=list(self._effects))


class _ConfirmEveryWrite:
    def __init__(self) -> None:
        self.call_ids: list[str] = []

    def confirm(self, run_id: str, call: ToolCall, tool_definition):
        self.call_ids.append(call.call_id)
        return ConfirmedAction.for_call(
            run_id,
            call,
            expires_at="2100-01-01T00:00:00+00:00",
        )


class _FixtureBriefingContentPort:
    def fetch(self, source_key: str) -> FetchedSourceDocument:
        return FetchedSourceDocument(
            document_id="document_executor_e2e",
            observation_id="observation_executor_e2e",
            source_key=source_key,
            title="Daily Papers",
            url="https://huggingface.co/papers",
            content_type="text/html",
            content=(
                '<a href="/papers/1">Agent workflow research</a>'
                '<a href="/papers/2">Multimodal vision research</a>'
            ),
            content_hash="executor-e2e-fixture-hash",
            fetched_at=utc_now_iso(),
            provenance="fixture:executor-cross-domain",
        )


class _RecordingTraceSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any] | None]] = []

    def append(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        self.events.append((event_type, payload))


def _action(call_id: str, tool_name: str, arguments: dict[str, Any]):
    return ToolActionDecision(ToolCall(call_id, tool_name, arguments))


if __name__ == "__main__":
    unittest.main()
