"""Runtime service bootstrap helpers."""

from __future__ import annotations

from pathlib import Path

from app.common.config import load_app_config
from app.domains.research.ports import HuggingFaceResearchContentPort
from app.domains.research.repository import ResearchRepository
from app.domains.research.service import ResearchService
from app.domains.research.tools import build_research_tools
from app.domains.travel.repository import TravelRepository
from app.domains.travel.service import TravelService
from app.domains.travel.tools import build_travel_tools
from app.intent.service import IntentService
from app.policy.service import PolicyService
from app.runtime.service import RuntimeService
from app.skills.loader import discover_skills
from app.skills.registry import SkillRegistry
from app.skills.selector import SkillSelectionClient
from app.skills.service import SkillService
from app.storage.migrations import migrate
from app.storage.sqlite import connect_sqlite
from app.tools.calling import OpenAIToolCallSelectionClient
from app.tools.registry import ToolRegistry
from app.tools.runtime import ToolRuntime


def build_runtime_service(
    config_path: str | Path = "config/default.json",
) -> RuntimeService:
    """Build a RuntimeService with configured storage and file logging."""

    config = load_app_config(config_path)

    skill_service = _build_skill_service(
        skill_root=config.skill_root,
    )

    conn = connect_sqlite(config.database_path)
    migrate(conn)

    return RuntimeService(
        intent_service=IntentService(),
        policy_service=PolicyService(),
        skill_service=skill_service,
        conn=conn,
        log_root=config.log_root,
        execution_scope_factory=lambda: _build_tool_runtime(conn, config.skill_root),
        tool_call_selection_client=OpenAIToolCallSelectionClient(),
    )


def _build_skill_service(
    *,
    skill_root: str | Path,
) -> SkillService:
    """Build the SkillService and its dependencies."""

    registry = SkillRegistry(discover_skills(skill_root))
    return SkillService(registry, SkillSelectionClient())


def _build_tool_runtime(conn, skill_root: Path) -> ToolRuntime:
    """Build request-local domain services and one shared registry/Gateway pair."""

    research_service = ResearchService(
        _UnavailableResearchSourcePort(),
        ResearchRepository(conn),
        content_port=HuggingFaceResearchContentPort(skill_root / "research"),
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
    registry = ToolRegistry(
        (*build_research_tools(research_service), *build_travel_tools(travel_service))
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
