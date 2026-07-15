from __future__ import annotations

import unittest
import tempfile
import sys
from pathlib import Path

from app.common.time import utc_now_iso
from app.domains.research.models import FetchedSourceDocument
from app.domains.research.ports import FixtureResearchSourcePort
from app.domains.research.repository import ResearchRepository
from app.domains.research.service import ResearchService
from app.domains.research.tools import (
    BUILD_BRIEF_TOOL,
    SAVE_BRIEF_TOOL,
    SAVE_SOURCE_TOOL,
    SEARCH_KNOWLEDGE_TOOL,
    SEARCH_PAPERS_TOOL,
    build_research_tools,
)
from app.integrations.mcp.models import McpServerConfig
from app.integrations.research_mcp.adapter import HuggingFaceMcpPaperSearchAdapter
from app.domains.travel.adapters import FixturePlaceSearchAdapter
from app.domains.travel.repository import TravelRepository
from app.domains.travel.service import TravelService
from app.domains.travel.tools import SEARCH_PLACES_TOOL, build_travel_tools
from app.executor.models import (
    ExecutorModelInput,
    FinalAnswerDecision,
    GoalNotAchievedDecision,
    ToolActionDecision,
)
from app.executor.service import ReactExecutor
from app.intent.models import IntentDecision, IntentType
from app.orchestration.graph import RuntimeOrchestrator
from app.planning.controller import PlanController
from app.planning.finalizer import FakePlanFinalizerClient
from app.planning.errors import PlanRepositoryError, PlanningError
from app.planning.models import (
    PlanCommand,
    PlanCommandAction,
    PlanDraft,
    PlanFinalizerOutput,
    PlanRoute,
    DirectRoute,
    PlanRunStatus,
    PlanStepDraft,
    PlanStepStatus,
    PlanningLimits,
)
from app.planning.planner import FakePlannerModelClient
from app.planning.repository import SqlitePlanRepository
from app.planning.router import FakePlanningRouteClient
from app.planning.service import PlanningService
from app.policy.models import PolicyAction, PolicyDecision
from app.runtime.models import RuntimeRequest, RuntimeStatus
from app.skills.loader import discover_skills
from app.skills.models import SkillDefinition
from app.skills.registry import SkillRegistry
from app.skills.service import SkillService
from app.tools.models import ConfirmedAction, ToolCall
from app.tools.registry import ToolRegistry
from app.tools.runtime import ToolRuntime
from tests.helpers import create_test_connection
from app.storage.migrations import migrate
from app.storage.sqlite import connect_sqlite


class PlanningCompiledE2ETest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = create_test_connection()
        self.repository = SqlitePlanRepository(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_research_preview_confirm_handoff_writes_evidence_and_finalizes(self) -> None:
        confirmation = _ConfirmEveryWrite()
        model = _ResearchPlanModel()
        finalizer = FakePlanFinalizerClient(PlanFinalizerOutput("研究计划完成。"))
        orchestrator = self._orchestrator(
            _research_draft(),
            model,
            effects=("read", "external_read", "write"),
            confirmation=confirmation,
            finalizer=finalizer,
        )

        preview = orchestrator.handle(_request())
        self.assertEqual(preview.status, RuntimeStatus.REQUIRES_CONFIRMATION)
        self.assertEqual(self._count("research_sources"), 0)
        self.assertEqual(self._count("research_briefs"), 0)

        result = orchestrator.invoke_plan_command(
            _request(run_id="run_confirm"), _confirm(preview)
        )["result"]

        self.assertEqual(result.status, RuntimeStatus.OK)
        self.assertEqual(result.message, "研究计划完成。")
        self.assertEqual(self._count("research_sources"), 1)
        self.assertEqual(self._count("research_briefs"), 1)
        self.assertEqual(confirmation.tool_names, [SAVE_SOURCE_TOOL, SAVE_BRIEF_TOOL])
        self.assertTrue(model.request_local_ids_verified)
        final_steps = finalizer.inputs[0].step_results
        self.assertEqual(len(final_steps), 3)
        self.assertEqual(sum(len(step.evidence_refs) for step in final_steps), 2)

    def test_unconfirmed_research_write_stops_with_zero_writes(self) -> None:
        orchestrator = self._orchestrator(
            _research_draft(),
            _ResearchPlanModel(),
            effects=("read", "external_read", "write"),
        )
        preview = orchestrator.handle(_request())
        result = orchestrator.invoke_plan_command(
            _request(run_id="run_unconfirmed"), _confirm(preview)
        )["result"]

        self.assertEqual(result.status, RuntimeStatus.REQUIRES_CONFIRMATION)
        self.assertIsNone(result.error_code)
        self.assertEqual(self._count("research_sources"), 0)
        self.assertEqual(self._count("research_briefs"), 0)

    def test_minimal_research_to_travel_read_plan(self) -> None:
        draft = PlanDraft(
            (
                PlanStepDraft("research", 1, "读取研究资料", "研究资料已读取"),
                PlanStepDraft(
                    "travel", 2, "查询地点", "地点已查询", ("research",)
                ),
            )
        )
        model = _CrossDomainModel()
        orchestrator = self._orchestrator(
            draft,
            model,
            effects=("external_read",),
            finalizer=FakePlanFinalizerClient(PlanFinalizerOutput("跨域读取完成。")),
        )
        preview = orchestrator.handle(_request())
        result = orchestrator.invoke_plan_command(
            _request(run_id="run_cross"), _confirm(preview)
        )["result"]

        self.assertEqual(result.status, RuntimeStatus.OK)
        self.assertTrue(model.saw_declared_research_dependency)
        self.assertEqual(self._count("research_sources"), 0)
        self.assertEqual(self._count("travel_itineraries"), 0)

    def test_finalizer_failure_uses_fallback_after_completed_read(self) -> None:
        draft = PlanDraft(
            (PlanStepDraft("one", 1, "查询知识", "知识查询完成"),)
        )
        orchestrator = self._orchestrator(
            draft,
            _BudgetModel(),
            effects=("read",),
            finalizer=FakePlanFinalizerClient(
                PlanningError("failed", code="plan_finalization_failed")
            ),
        )
        preview = orchestrator.handle(_request())
        result = orchestrator.invoke_plan_command(
            _request(run_id="run_fallback"), _confirm(preview)
        )["result"]

        self.assertEqual(result.status, RuntimeStatus.OK)
        self.assertIn("Completed: 知识查询完成", result.message)
        self.assertEqual(result.tool_result["plan_status"], "completed")

    def test_goal_not_achieved_replans_reconfirms_and_completes(self) -> None:
        initial = PlanDraft((PlanStepDraft("attempt", 1, "尝试", "目标完成"),))
        replacement = PlanDraft((PlanStepDraft("retry", 1, "重试", "目标完成"),))
        planner = FakePlannerModelClient(initial, replacement)
        model = _ReplanModel()
        orchestrator = self._orchestrator(
            initial,
            model,
            effects=("read",),
            planner=planner,
            finalizer=FakePlanFinalizerClient(PlanFinalizerOutput("重规划完成。")),
        )
        initial_preview = orchestrator.handle(_request())
        replan_preview = orchestrator.invoke_plan_command(
            _request(run_id="run_replan_1"), _confirm(initial_preview)
        )["result"]

        self.assertEqual(replan_preview.status, RuntimeStatus.REQUIRES_CONFIRMATION)
        self.assertEqual(replan_preview.tool_result["revision"], 2)
        self.assertEqual(model.calls, ["attempt"])

        completed = orchestrator.invoke_plan_command(
            _request(run_id="run_replan_2"), _confirm(replan_preview)
        )["result"]
        self.assertEqual(completed.status, RuntimeStatus.OK)
        self.assertEqual(model.calls, ["attempt", "retry"])

    def test_second_goal_failure_stops_as_replan_exhausted(self) -> None:
        initial = PlanDraft((PlanStepDraft("attempt", 1, "尝试", "目标完成"),))
        replacement = PlanDraft((PlanStepDraft("retry", 1, "重试", "目标完成"),))
        planner = FakePlannerModelClient(initial, replacement)
        orchestrator = self._orchestrator(
            initial,
            _AlwaysGoalNotAchievedModel(),
            effects=("read",),
            planner=planner,
        )
        initial_preview = orchestrator.handle(_request())
        replan_preview = orchestrator.invoke_plan_command(
            _request(run_id="run_exhausted_1"), _confirm(initial_preview)
        )["result"]
        stopped = orchestrator.invoke_plan_command(
            _request(run_id="run_exhausted_2"), _confirm(replan_preview)
        )["result"]

        self.assertEqual(stopped.status, RuntimeStatus.ERROR)
        self.assertEqual(stopped.error_code, "plan_replan_exhausted")

    def test_simple_research_direct_route_does_not_create_plan(self) -> None:
        planner = FakePlannerModelClient(_research_draft())
        orchestrator = self._orchestrator(
            _research_draft(),
            _DirectResearchModel(),
            effects=("read",),
            planner=planner,
            route_decision=DirectRoute("single_read"),
        )
        result = orchestrator.handle(_request())

        self.assertEqual(result.status, RuntimeStatus.OK)
        self.assertEqual(planner.create_inputs, [])
        self.assertEqual(self._count("plan_runs"), 0)

    def test_total_budget_safety_and_stale_revision_fail_closed(self) -> None:
        limits = PlanningLimits(
            max_plan_steps=2,
            max_replans=1,
            max_executor_steps_per_plan_step=2,
            max_total_executor_steps=1,
        )
        draft = PlanDraft(
            (
                PlanStepDraft("one", 1, "查询", "查询完成"),
                PlanStepDraft("two", 2, "再次查询", "再次完成"),
            )
        )
        orchestrator = self._orchestrator(
            draft,
            _BudgetModel(),
            effects=("read",),
            limits=limits,
        )
        preview = orchestrator.handle(_request())
        stopped = orchestrator.invoke_plan_command(
            _request(run_id="run_budget"), _confirm(preview)
        )["result"]
        self.assertEqual(stopped.error_code, "plan_budget_exhausted")
        run, steps = self.repository.get_plan(
            "session_plan_e2e", preview.tool_result["plan_id"]
        )
        self.assertEqual(run.status, PlanRunStatus.STOPPED)
        self.assertEqual(steps[1].status, PlanStepStatus.PENDING)

        safety_draft = PlanDraft(
            (PlanStepDraft("unsafe", 1, "尝试未授权写入", "不应完成"),)
        )
        safety_orchestrator = self._orchestrator(
            safety_draft,
            _SafetyModel(),
            effects=("read",),
        )
        safety_preview = safety_orchestrator.handle(
            _request(run_id="run_safety_preview")
        )
        denied = safety_orchestrator.invoke_plan_command(
            _request(run_id="run_safety"), _confirm(safety_preview)
        )["result"]
        self.assertEqual(denied.status, RuntimeStatus.ERROR)
        self.assertEqual(denied.error_code, "tool_not_allowed")
        self.assertEqual(self._count("research_sources"), 0)

        stale = PlanCommand(
            "stale",
            preview.tool_result["plan_id"],
            "session_plan_e2e",
            2,
            PlanCommandAction.CONFIRM,
        )
        with self.assertRaises(PlanRepositoryError) as caught:
            orchestrator.invoke_plan_command(_request(run_id="run_stale"), stale)
        self.assertEqual(getattr(caught.exception, "code", None), "plan_revision_stale")

    def test_restart_reads_preview_and_marks_interrupted_run_without_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "planning.db"
            first = connect_sqlite(path)
            migrate(first)
            repo = SqlitePlanRepository(first)
            run, _ = repo.create_initial_plan(
                session_id="restart_session",
                goal="restart goal",
                draft=PlanDraft((PlanStepDraft("one", 1, "执行", "完成"),)),
                limits=PlanningLimits(),
                plan_id="restart_plan",
            )
            repo.apply_command(
                PlanCommand(
                    "confirm_restart",
                    run.plan_id,
                    run.session_id,
                    1,
                    PlanCommandAction.CONFIRM,
                )
            )
            repo.claim_ready_step(run.session_id, run.plan_id, 1)
            first.close()

            second = connect_sqlite(path)
            try:
                recovered, steps = SqlitePlanRepository(second).get_plan(
                    "restart_session", "restart_plan", recover_interrupted=True
                )
                self.assertEqual(recovered.status, PlanRunStatus.STOPPED)
                self.assertEqual(recovered.last_error_code, "plan_execution_interrupted")
                self.assertEqual(steps[0].status, PlanStepStatus.STOPPED)
            finally:
                second.close()

    def _orchestrator(
        self,
        draft: PlanDraft,
        model,
        *,
        effects: tuple[str, ...],
        confirmation=None,
        planner=None,
        finalizer=None,
        limits: PlanningLimits | None = None,
        route_decision=None,
    ) -> RuntimeOrchestrator:
        limits = limits or PlanningLimits(max_plan_steps=6)
        planner = planner or FakePlannerModelClient(draft)
        service = PlanningService(planner, self.repository, limits=limits)
        executor = ReactExecutor(model, confirmation_provider=confirmation)
        controller = PlanController(
            self.repository,
            executor,
            limits=limits,
            planner=planner,
            finalizer=finalizer,
        )
        runtime = self._combined_runtime()
        return RuntimeOrchestrator(
            SkillService(
                SkillRegistry(discover_skills(Path("app/skills"))),
                _BothSkillSelectionClient(),
            ),
            intent_service=_PlanIntent(),
            policy_service=_Policy(effects),
            execution_scope_factory=lambda: runtime,
            executor=executor,
            planning_route_client=FakePlanningRouteClient(
                route_decision or PlanRoute("multi_step")
            ),
            planning_service=service,
            plan_controller=controller,
            planning_limits=limits,
        )

    def _combined_runtime(self) -> ToolRuntime:
        research = ResearchService(
            FixtureResearchSourcePort(
                {
                    "hf-daily": {
                        "title": "HF Daily",
                        "url": "https://huggingface.co/papers",
                        "summary": "Research fixture.",
                    }
                }
            ),
            ResearchRepository(self.conn),
            content_port=_BriefingContentPort(),
            paper_search_port=HuggingFaceMcpPaperSearchAdapter(
                McpServerConfig(
                    server_id="planning-e2e-hf-fixture",
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
        travel = TravelService(
            TravelRepository(self.conn),
            place_port=FixturePlaceSearchAdapter(
                Path("tests/fixtures/travel/places_tokyo.json"),
                Path("tests/fixtures/travel/provider_failures.json"),
            ),
        )
        return ToolRuntime.from_registry(
            ToolRegistry((*build_research_tools(research), *build_travel_tools(travel)))
        )

    def _count(self, table: str) -> int:
        return self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class _ResearchPlanModel:
    def __init__(self) -> None:
        self.request_local_ids_verified = False

    def decide(self, model_input: ExecutorModelInput, *, llm_log=None):
        step = model_input.plan_step
        if model_input.observations:
            return FinalAnswerDecision(f"{step.step_id} completed")
        outputs = _dependency_outputs(model_input)
        if step.step_id == "build_brief":
            return _action(
                "build_brief",
                BUILD_BRIEF_TOOL,
                {
                    "source_keys": ["hf_daily_papers"],
                    "limit": 5,
                    "topic_filter": "agent",
                },
            )
        if step.step_id == "save_source":
            return _action(
                "save_source",
                SAVE_SOURCE_TOOL,
                {"observation_id": outputs["source_observation_ids"][0]},
            )
        if step.step_id == "save_brief":
            self.request_local_ids_verified = "draft_id" in outputs and "source_id" in outputs
            return _action("save_brief", SAVE_BRIEF_TOOL, {"draft_id": outputs["draft_id"]})
        raise AssertionError(step.step_id)


class _CrossDomainModel:
    def __init__(self) -> None:
        self.saw_declared_research_dependency = False

    def decide(self, model_input: ExecutorModelInput, *, llm_log=None):
        step = model_input.plan_step
        if model_input.observations:
            return FinalAnswerDecision("step complete")
        if step.step_id == "research":
            return _action(
                "research",
                SEARCH_PAPERS_TOOL,
                {"query": "agent", "limit": 3},
            )
        self.saw_declared_research_dependency = tuple(
            item.step_id for item in step.dependency_results
        ) == ("research",)
        return _action("travel", SEARCH_PLACES_TOOL, {"destination": "Tokyo", "query": "historic places"})


class _ReplanModel:
    def __init__(self) -> None:
        self.calls = []

    def decide(self, model_input: ExecutorModelInput, *, llm_log=None):
        self.calls.append(model_input.plan_step.step_id)
        if model_input.plan_step.step_id == "attempt":
            return GoalNotAchievedDecision("insufficient_result")
        return FinalAnswerDecision("retry complete")


class _AlwaysGoalNotAchievedModel:
    def decide(self, model_input: ExecutorModelInput, *, llm_log=None):
        return GoalNotAchievedDecision("still_insufficient")


class _DirectResearchModel:
    def decide(self, model_input: ExecutorModelInput, *, llm_log=None):
        if model_input.observations:
            return FinalAnswerDecision("direct research read complete")
        return _action(
            "direct_search",
            SEARCH_KNOWLEDGE_TOOL,
            {"query": "agent", "item_kinds": ["note"], "limit": 1, "offset": 0},
        )


class _SafetyModel:
    def decide(self, model_input: ExecutorModelInput, *, llm_log=None):
        return _action(
            "unsafe_write",
            SAVE_SOURCE_TOOL,
            {"observation_id": "forged"},
        )


class _BudgetModel:
    def decide(self, model_input: ExecutorModelInput, *, llm_log=None):
        if model_input.observations:
            return FinalAnswerDecision("query complete")
        return _action(
            "search",
            SEARCH_KNOWLEDGE_TOOL,
            {"query": "none", "item_kinds": ["note"], "limit": 1, "offset": 0},
        )


class _BothSkillSelectionClient:
    def select(self, request, skill_metadata: tuple[SkillDefinition, ...], *, llm_log=None):
        return {"selected_skill_ids": ["research", "travel"], "reason": "fixture"}


class _PlanIntent:
    def classify(self, request):
        return IntentDecision(IntentType.PLAN_REQUEST, 1.0)


class _Policy:
    def __init__(self, effects: tuple[str, ...]) -> None:
        self.effects = effects

    def evaluate(self, request, intent):
        return PolicyDecision(PolicyAction.ALLOW, allowed_effects=list(self.effects))


class _ConfirmEveryWrite:
    def __init__(self) -> None:
        self.tool_names = []

    def confirm(self, run_id, call, tool_definition):
        self.tool_names.append(call.tool_name)
        return ConfirmedAction.for_call(
            run_id, call, expires_at="2100-01-01T00:00:00+00:00"
        )


class _BriefingContentPort:
    def fetch(self, source_key: str) -> FetchedSourceDocument:
        return FetchedSourceDocument(
            "document_plan_e2e",
            "observation_plan_e2e",
            source_key,
            "Daily Papers",
            "https://huggingface.co/papers",
            "text/html",
            '<a href="/papers/1">Agent workflow research</a>',
            "plan-e2e-hash",
            utc_now_iso(),
            "fixture:planning-e2e",
        )


def _research_draft() -> PlanDraft:
    return PlanDraft(
        (
            PlanStepDraft("build_brief", 1, "生成简报草稿", "草稿已生成"),
            PlanStepDraft(
                "save_source", 2, "保存来源", "来源已保存", ("build_brief",)
            ),
            PlanStepDraft(
                "save_brief",
                3,
                "保存简报",
                "简报已保存",
                ("build_brief", "save_source"),
            ),
        )
    )


def _dependency_outputs(model_input: ExecutorModelInput) -> dict:
    output = {}
    for dependency in model_input.plan_step.dependency_results:
        for observation in dependency.observations:
            output.update(observation.output or {})
    return output


def _action(call_id: str, tool_name: str, arguments: dict) -> ToolActionDecision:
    return ToolActionDecision(ToolCall(call_id, tool_name, arguments))


def _request(*, run_id: str = "run_preview") -> RuntimeRequest:
    return RuntimeRequest(
        "研究 Agent 资料并形成简报",
        "session_plan_e2e",
        run_id=run_id,
    )


def _confirm(result) -> PlanCommand:
    return PlanCommand(
        f"confirm_{result.tool_result['plan_id']}_{result.tool_result['revision']}",
        result.tool_result["plan_id"],
        result.session_id,
        result.tool_result["revision"],
        PlanCommandAction.CONFIRM,
    )


if __name__ == "__main__":
    unittest.main()
