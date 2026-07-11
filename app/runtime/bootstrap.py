"""Runtime service bootstrap helpers."""

from __future__ import annotations

from pathlib import Path

from app.common.config import load_app_config
from app.intent.service import IntentService
from app.policy.service import PolicyService
from app.runtime.service import RuntimeService
from app.skills.loader import discover_skills
from app.skills.registry import SkillRegistry
from app.skills.selector import SkillSelectionClient
from app.skills.service import SkillService
from app.storage.migrations import migrate
from app.storage.sqlite import connect_sqlite


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
    )


def _build_skill_service(
    *,
    skill_root: str | Path,
) -> SkillService:
    """Build the SkillService and its dependencies."""

    registry = SkillRegistry(discover_skills(skill_root))
    return SkillService(registry, SkillSelectionClient())
