"""Build framework-independent prompt contributions from loaded Skills."""

from __future__ import annotations

from collections.abc import Sequence

from app.skills.errors import SkillPromptError
from app.skills.models import LoadedSkill, PromptContribution


def build_prompt_contributions(
    loaded_skills: Sequence[LoadedSkill],
) -> list[PromptContribution]:
    """Convert only selected-and-loaded Skills into prompt contributions.

    Selection order is preserved. Core rules, tool descriptions, context budget,
    and final prompt ordering remain responsibilities of future callers.
    """

    if isinstance(loaded_skills, (str, bytes)) or not isinstance(loaded_skills, Sequence):
        raise SkillPromptError(
            "loaded_skills must be a sequence of LoadedSkill values.",
            code="skill_prompt_invalid_loaded_skills",
        )
    if any(not isinstance(skill, LoadedSkill) for skill in loaded_skills):
        raise SkillPromptError(
            "loaded_skills must contain LoadedSkill values.",
            code="skill_prompt_invalid_loaded_skills",
        )

    skill_ids = [skill.definition.skill_id for skill in loaded_skills]
    if len(set(skill_ids)) != len(skill_ids):
        raise SkillPromptError(
            "loaded_skills must not contain duplicate Skill IDs.",
            code="skill_prompt_duplicate_skill_id",
        )

    return [
        PromptContribution(
            skill_id=skill.definition.skill_id,
            instructions=skill.body,
        )
        for skill in loaded_skills
    ]
