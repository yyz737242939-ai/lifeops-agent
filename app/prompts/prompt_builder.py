from dataclasses import dataclass

from app.prompts.system_prompt import CORE_PROMPT, CONTEXT_REF_PROMPT
from app.skills.skill_loader import SkillMetadata, load_skill


@dataclass(frozen=True)
class PromptBuildResult:
    instructions: str
    loaded_skills: tuple[str, ...]
    prompt_chars: int


def _skill_catalog(skills: dict[str, SkillMetadata]) -> str:
    lines = ["Available skills (metadata only):"]
    lines.extend(
        f"- {metadata.name}: {metadata.description}"
        for metadata in skills.values()
    )
    return "\n".join(lines)


def build_system_prompt(
    available_skills: dict[str, SkillMetadata],
    loaded_skills: tuple[str, ...] | list[str],
) -> PromptBuildResult:
    selected_skills = tuple(dict.fromkeys(loaded_skills))
    unknown_skills = set(selected_skills) - set(available_skills)
    if unknown_skills:
        raise ValueError(f"Unknown skills in prompt request: {sorted(unknown_skills)}")

    prompt_parts = [CORE_PROMPT, CONTEXT_REF_PROMPT, _skill_catalog(available_skills)]
    loaded_skill_names: list[str] = []

    for skill_name in selected_skills:
        skill = load_skill(available_skills[skill_name])
        prompt_parts.append(
            f"Loaded skill: {skill.metadata.name}\n\n{skill.instructions}"
        )
        loaded_skill_names.append(skill_name)

    instructions = "\n\n".join(prompt_parts)
    return PromptBuildResult(
        instructions=instructions,
        loaded_skills=tuple(loaded_skill_names),
        prompt_chars=len(instructions),
    )
