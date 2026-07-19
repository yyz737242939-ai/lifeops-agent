"""In-memory registry for lightweight Skill metadata."""

from __future__ import annotations

from collections.abc import Iterable

from app.skills.errors import SkillNotFoundError, SkillRegistryError
from app.skills.models import SkillDefinition


class SkillRegistry:
    """Read-only lookup boundary for Skill definitions discovered at startup."""

    def __init__(self, definitions: Iterable[SkillDefinition] = ()) -> None:
        by_id: dict[str, SkillDefinition] = {}
        for definition in definitions:
            if not isinstance(definition, SkillDefinition):
                raise SkillRegistryError(
                    "Skill registry only accepts SkillDefinition values.",
                    code="skill_registry_invalid_definition",
                )
            if definition.skill_id in by_id:
                raise SkillRegistryError(
                    f"Duplicate Skill ID: {definition.skill_id}",
                    code="skill_registry_duplicate_id",
                    details={"skill_id": definition.skill_id},
                )
            by_id[definition.skill_id] = definition
        self._by_id = by_id

    def list_definitions(self) -> tuple[SkillDefinition, ...]:
        """Return definitions in deterministic Skill ID order."""

        return tuple(self._by_id[skill_id] for skill_id in sorted(self._by_id))

    def get(self, skill_id: str) -> SkillDefinition:
        """Return one registered definition or raise a typed expected error."""

        if not isinstance(skill_id, str) or not skill_id.strip():
            raise SkillRegistryError(
                "skill_id must be a non-empty string.",
                code="skill_registry_invalid_id",
            )
        try:
            return self._by_id[skill_id]
        except KeyError as exc:
            raise SkillNotFoundError(
                f"Skill is not registered: {skill_id}",
                code="skill_not_found",
                details={"skill_id": skill_id},
            ) from exc

    def contains(self, skill_id: str) -> bool:
        """Report whether a Skill ID is registered."""

        return skill_id in self._by_id

    def __len__(self) -> int:
        return len(self._by_id)
