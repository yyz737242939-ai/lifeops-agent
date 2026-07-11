"""Application service for one request-local Skill preparation stage."""

from __future__ import annotations

from app.observability.logger import TraceSink
from app.runtime.models import RuntimeRequest
from app.skills.loader import load_skill
from app.skills.models import SkillPreparation
from app.skills.prompt_assembler import build_prompt_contributions
from app.skills.registry import SkillRegistry
from app.skills.selector import SkillSelectionClient, select_skills


class SkillService:
    """Own selection, lazy loading, and contribution assembly dependencies."""

    def __init__(
        self,
        registry: SkillRegistry,
        selection_client: SkillSelectionClient,
    ) -> None:
        if not isinstance(registry, SkillRegistry):
            raise ValueError("registry must be a SkillRegistry.")
        self._registry = registry
        self._selection_client = selection_client

    def prepare(
        self,
        request: RuntimeRequest,
        *,
        trace: TraceSink | None = None,
    ) -> SkillPreparation:
        """Select and load Skills for one request without executing tools."""

        selection = select_skills(
            request,
            self._registry.list_definitions(),
            self._selection_client,
            trace=trace,
        )
        loaded_skills = tuple(
            load_skill(self._registry.get(skill_id), trace=trace)
            for skill_id in selection.selected_skill_ids
        )
        contributions = tuple(build_prompt_contributions(loaded_skills))
        return SkillPreparation(
            selection=selection,
            loaded_skill_ids=tuple(
                loaded.definition.skill_id for loaded in loaded_skills
            ),
            prompt_contributions=contributions,
        )
