"""Runtime service bootstrap helpers."""

from __future__ import annotations

from pathlib import Path

from app.common.config import load_app_config
from app.domains.research.ports import FixtureResearchSourcePort
from app.domains.research.repository import ResearchRepository
from app.domains.research.service import ResearchService
from app.domains.research.tools import build_research_tools
from app.domains.travel.ports import FixtureTravelOptionPort
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
        tool_runtime_factory=lambda: _build_tool_runtime(conn),
        tool_call_selection_client=OpenAIToolCallSelectionClient(),
    )


def _build_skill_service(
    *,
    skill_root: str | Path,
) -> SkillService:
    """Build the SkillService and its dependencies."""

    registry = SkillRegistry(discover_skills(skill_root))
    return SkillService(registry, SkillSelectionClient())


def _build_tool_runtime(conn) -> ToolRuntime:
    """Build request-local domain services and one shared registry/Gateway pair."""

    research_service = ResearchService(
        FixtureResearchSourcePort(
            {
                "hf-daily": {
                    "title": "Hugging Face Daily Papers fixture",
                    "url": "https://huggingface.co/papers",
                    "summary": "Declared fixture for the Research Tool vertical slice.",
                }
            }
        ),
        ResearchRepository(conn),
    )
    travel_service = TravelService(
        FixtureTravelOptionPort(
            {
                "Tokyo": {
                    "transport": "Fixture flight and local rail option",
                    "lodging": "Fixture lodging option in central Tokyo",
                    "summary": "Declared fixture option; this is not a booking.",
                }
            }
        ),
        TravelRepository(conn),
    )
    registry = ToolRegistry(
        (*build_research_tools(research_service), *build_travel_tools(travel_service))
    )
    return ToolRuntime.from_registry(registry)
