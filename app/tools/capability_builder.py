import json
from dataclasses import dataclass
from typing import Any

from app.tools.tool import TOOLS, ToolEffect


COMMON_TOOL_NAMES = frozenset(
    {
        "get_current_time",
        "list_memories",
        "read_context_ref",
        "save_memory",
        "delete_memory",
    }
)

SKILL_TOOL_NAMES: dict[str, frozenset[str]] = {
    "todo": frozenset(
        {
            "add_todo",
            "list_todos",
            "complete_todo",
            "update_todo",
            "delete_todo",
            "plan_day",
        }
    ),
    "wellbeing": frozenset(
        {
            "record_daily_state",
            "get_daily_state",
            "list_daily_logs",
        }
    ),
    "finance": frozenset(
        {
            "record_expense",
            "list_expenses",
            "summarize_spending",
            "set_budget",
            "check_budget",
        }
    ),
    "activity": frozenset({"recommend_activities"}),
    "news": frozenset(
        {
            "read_skill_reference",
            "fetch_news_source",
            "run_news_helper",
        }
    ),
}


@dataclass(frozen=True)
class CapabilityBuildResult:
    """Tool visibility and authorization snapshot for one Agent turn."""

    loaded_skills: tuple[str, ...]
    tool_schemas: tuple[dict[str, Any], ...]
    allowed_tool_names: frozenset[str]
    capability_sources: dict[str, tuple[str, ...]]
    schema_count: int
    schema_chars: int
    fallback_used: bool


def _validate_configuration() -> None:
    registered = set(TOOLS)
    configured = set(COMMON_TOOL_NAMES)
    for tool_names in SKILL_TOOL_NAMES.values():
        configured.update(tool_names)

    unknown = configured - registered
    if unknown:
        raise ValueError(f"Capability map contains unknown tools: {sorted(unknown)}")

    unmapped = registered - configured
    if unmapped:
        raise ValueError(f"Registered tools lack a capability owner: {sorted(unmapped)}")


def build_capabilities(
    loaded_skills: tuple[str, ...] | list[str],
    *,
    authorized_write_tool_names: frozenset[str] | None = None,
) -> CapabilityBuildResult:
    """Map loaded Skills to visible schemas and allowed tool names."""
    _validate_configuration()
    authorized_writes = authorized_write_tool_names or frozenset()

    unknown_skills = set(loaded_skills) - set(SKILL_TOOL_NAMES)
    if unknown_skills:
        raise ValueError(f"Unknown skills in capability request: {sorted(unknown_skills)}")

    sources: dict[str, list[str]] = {}
    allowed: set[str] = set()

    for tool_name in COMMON_TOOL_NAMES:
        tool = TOOLS[tool_name]
        if (
            tool.effect == ToolEffect.WRITE
            and tool_name not in authorized_writes
        ):
            continue
        allowed.add(tool_name)
        sources.setdefault(tool_name, []).append("common")

    for skill_name in dict.fromkeys(loaded_skills):
        for tool_name in SKILL_TOOL_NAMES[skill_name]:
            tool = TOOLS[tool_name]
            if (
                tool.effect == ToolEffect.WRITE
                and tool_name not in authorized_writes
            ):
                continue
            allowed.add(tool_name)
            sources.setdefault(tool_name, []).append(skill_name)

    # Registry order is stable and makes logs and tests easy to compare.
    tool_schemas = tuple(
        tool.schema() for name, tool in TOOLS.items() if name in allowed
    )
    serialized_schemas = json.dumps(
        tool_schemas,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    return CapabilityBuildResult(
        loaded_skills=tuple(dict.fromkeys(loaded_skills)),
        tool_schemas=tool_schemas,
        allowed_tool_names=frozenset(allowed),
        capability_sources={
            name: tuple(sources[name]) for name in TOOLS if name in sources
        },
        schema_count=len(tool_schemas),
        schema_chars=len(serialized_schemas),
        fallback_used=not loaded_skills,
    )
