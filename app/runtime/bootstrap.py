"""Runtime service bootstrap helpers."""

from __future__ import annotations

from pathlib import Path
import sys

from app.context.assembler import ContextAssembler
from app.context.models import ContextBudget
from app.context.repository import JsonlConversationRepository
from app.context.summarizer import OpenAIContextSummarizer
from app.context.summary_service import RollingSummaryService
from app.executor.model_adapter import OpenAIExecutorModelClient
from app.executor.ports import ActionConfirmationProvider
from app.executor.service import ReactExecutor
from app.common.config import load_app_config
from app.domains.research.ports import HuggingFaceResearchContentPort
from app.domains.research.repository import ResearchRepository
from app.domains.research.service import ResearchService
from app.domains.research.tools import build_research_tools
from app.domains.travel.repository import TravelRepository
from app.domains.travel.service import TravelService
from app.domains.travel.tools import build_travel_tools
from app.integrations.mcp.models import McpServerConfig
from app.integrations.research_mcp.adapter import (
    HuggingFaceMcpPaperSearchAdapter,
)
from app.intent.service import IntentService
from app.memory.document_store import MemoryDocumentStore
from app.memory.models import MemoryWriteContext
from app.memory.profile import FileProfileProvider
from app.memory.repository import SqliteMemoryRepository
from app.memory.retriever import DeterministicMemoryRetriever
from app.memory.service import MemoryService
from app.memory.tools import build_memory_tools
from app.policy.service import PolicyService
from app.recovery.collector import RequestExecutionFeedbackCollector
from app.recovery.finalizer import RuntimeOutcomeFinalizer
from app.recovery.repository import SqliteExecutionFeedbackRepository
from app.planning.controller import PlanController
from app.planning.finalizer import OpenAIPlanFinalizerClient
from app.planning.models import PlanningLimits
from app.planning.planner import OpenAIPlannerModelClient
from app.planning.repository import SqlitePlanRepository
from app.planning.router import OpenAIPlanningRouteClient
from app.planning.service import PlanningService
from app.runtime.service import RuntimeService
from app.skills.loader import discover_skills
from app.skills.registry import SkillRegistry
from app.skills.selector import SkillSelectionClient
from app.skills.service import SkillService
from app.storage.migrations import migrate
from app.storage.sqlite import connect_sqlite
from app.tools.registry import ToolRegistry
from app.tools.runtime import ToolRuntime


def build_runtime_service(
    config_path: str | Path = "config/default.json",
    *,
    confirmation_provider: ActionConfirmationProvider | None = None,
) -> RuntimeService:
    """Build a RuntimeService with configured storage and file logging."""

    config = load_app_config(config_path)

    skill_service = _build_skill_service(
        skill_root=config.skill_root,
    )

    conn = connect_sqlite(config.database_path)
    migrate(conn)
    limits = PlanningLimits()
    planner = OpenAIPlannerModelClient()
    repository = SqlitePlanRepository(conn)
    feedback_collector = RequestExecutionFeedbackCollector()
    executor = ReactExecutor(
        OpenAIExecutorModelClient(),
        confirmation_provider=confirmation_provider,
        feedback_sink=feedback_collector,
    )
    conversation_repository = JsonlConversationRepository(
        config.database_path.parent / "conversations"
    )
    memory_root = config.database_path.parent / "memory"
    memory_repository = SqliteMemoryRepository(conn)
    memory_store = MemoryDocumentStore(memory_root)
    context_assembler = ContextAssembler(
        conversation_repository,
        RollingSummaryService(
            conversation_repository,
            OpenAIContextSummarizer(),
        ),
        profile_provider=FileProfileProvider(memory_root),
        memory_retriever=DeterministicMemoryRetriever(
            memory_repository,
            memory_store,
        ),
    )
    planning_service = PlanningService(planner, repository, limits=limits)
    plan_controller = PlanController(
        repository,
        executor,
        limits=limits,
        planner=planner,
        finalizer=OpenAIPlanFinalizerClient(),
    )

    return RuntimeService(
        intent_service=IntentService(),
        policy_service=PolicyService(),
        skill_service=skill_service,
        conn=conn,
        log_root=config.log_root,
        execution_scope_factory=lambda request, trace: _build_tool_runtime(
            conn,
            config.skill_root,
            request=request,
            memory_root=memory_root,
            trace=trace,
        ),
        executor=executor,
        planning_route_client=OpenAIPlanningRouteClient(),
        planning_service=planning_service,
        plan_controller=plan_controller,
        planning_limits=limits,
        conversation_repository=conversation_repository,
        context_assembler=context_assembler,
        context_budget=ContextBudget(4000, 8, 1000, 500, 5, 500, 2000),
        outcome_finalizer=RuntimeOutcomeFinalizer(
            feedback_collector,
            SqliteExecutionFeedbackRepository(conn),
            plan_repository=repository,
        ),
    )


def _build_skill_service(
    *,
    skill_root: str | Path,
) -> SkillService:
    """Build the SkillService and its dependencies."""

    registry = SkillRegistry(discover_skills(skill_root))
    return SkillService(registry, SkillSelectionClient())


def _build_tool_runtime(
    conn,
    skill_root: Path,
    *,
    request=None,
    memory_root: Path | None = None,
    trace=None,
) -> ToolRuntime:
    """Build request-local domain services and one shared registry/Gateway pair."""

    repo_root = Path(__file__).resolve().parents[2]
    research_service = ResearchService(
        _UnavailableResearchSourcePort(),
        ResearchRepository(conn),
        content_port=HuggingFaceResearchContentPort(skill_root / "research"),
        paper_search_port=HuggingFaceMcpPaperSearchAdapter(
            McpServerConfig(
                server_id="huggingface-papers",
                command=sys.executable,
                args=("-m", "app.integrations.research_mcp.server"),
                cwd=repo_root,
                timeout_seconds=15.0,
            )
        ),
    )
    unavailable_travel = _UnavailableTravelPorts()
    travel_service = TravelService(
        TravelRepository(conn),
        calendar_port=unavailable_travel,
        weather_port=unavailable_travel,
        transport_port=unavailable_travel,
        lodging_port=unavailable_travel,
        place_port=unavailable_travel,
    )
    memory_service = MemoryService(
        SqliteMemoryRepository(conn),
        MemoryDocumentStore(memory_root or Path("data/memory")),
    )

    def memory_write_context(call) -> MemoryWriteContext:
        if request is None:
            raise ValueError("Memory WRITE requires a request-bound Tool runtime.")
        return MemoryWriteContext(
            source_session_id=request.session_id,
            source_turn_id=request.turn_id,
            source_run_id=request.run_id,
            source_tool_call_id=call.call_id,
            confirmation_ref=f"confirmation://{request.run_id}/{call.call_id}",
            evidence_ref=f"tool-evidence://{request.run_id}/{call.call_id}",
        )
    registry = ToolRegistry(
        (
            *build_research_tools(research_service),
            *build_travel_tools(travel_service),
            *build_memory_tools(
                memory_service,
                memory_write_context,
                event_sink=trace,
            ),
        )
    )
    return ToolRuntime.from_registry(registry)


class _UnavailableResearchSourcePort:
    def fetch(self, source_key: str):
        raise RuntimeError("Research source provider is not configured.")


class _UnavailableTravelPorts:
    def check_availability(self, query):
        raise RuntimeError("Travel calendar provider is not configured.")

    def get_weather(self, query):
        raise RuntimeError("Travel weather provider is not configured.")

    def search_transport(self, query):
        raise RuntimeError("Travel transport provider is not configured.")

    def search_lodging(self, query):
        raise RuntimeError("Travel lodging provider is not configured.")

    def search_places(self, query):
        raise RuntimeError("Travel place provider is not configured.")
