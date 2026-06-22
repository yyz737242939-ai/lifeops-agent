from dataclasses import dataclass

from app.prompts.system_prompt import CORE_PROMPT, CONTEXT_REF_PROMPT
from app.skills.skill_loader import SkillMetadata, load_skill
from app.skills.skill_router import RoutingDecision, route_skills


@dataclass(frozen=True)
class PromptBuildResult:
    instructions: str
    routing: RoutingDecision
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
    user_input: str,
    available_skills: dict[str, SkillMetadata],
) -> PromptBuildResult:
    routing = route_skills(user_input, available_skills)
    prompt_parts = [CORE_PROMPT, CONTEXT_REF_PROMPT, _skill_catalog(available_skills)]
    loaded_skills: list[str] = []

    for skill_name in routing.selected:
        skill = load_skill(available_skills[skill_name])
        prompt_parts.append(
            f"Loaded skill: {skill.metadata.name}\n\n{skill.instructions}"
        )
        loaded_skills.append(skill_name)

    instructions = "\n\n".join(prompt_parts)
    return PromptBuildResult(
        instructions=instructions,
        routing=routing,
        loaded_skills=tuple(loaded_skills),
        prompt_chars=len(instructions),
    )
