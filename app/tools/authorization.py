"""Request-local Tool authorization from Policy and registered contracts."""

from __future__ import annotations

from collections.abc import Iterable

from app.policy.models import PolicyAction, PolicyDecision
from app.tools.errors import ToolAuthorizationError
from app.tools.models import AllowedToolSet
from app.tools.registry import ToolRegistry


def resolve_allowed_tools(
    selected_skill_ids: Iterable[str],
    policy: PolicyDecision,
    registry: ToolRegistry,
) -> AllowedToolSet:
    """Intersect Skill business candidates with Policy-allowed Tool effects."""

    if isinstance(selected_skill_ids, (str, bytes)) or not isinstance(
        selected_skill_ids, Iterable
    ):
        raise ToolAuthorizationError(
            "selected_skill_ids must be an iterable of Skill IDs.",
            code="tool_authorization_invalid_skill_ids",
        )
    if not isinstance(policy, PolicyDecision):
        raise ToolAuthorizationError(
            "policy must be a PolicyDecision.",
            code="tool_authorization_invalid_policy",
        )
    if not isinstance(registry, ToolRegistry):
        raise ToolAuthorizationError(
            "registry must be a ToolRegistry.",
            code="tool_authorization_invalid_registry",
        )
    normalized_skill_ids: set[str] = set()
    for skill_id in selected_skill_ids:
        if not isinstance(skill_id, str) or not skill_id.strip():
            raise ToolAuthorizationError(
                "selected_skill_ids must contain non-empty strings.",
                code="tool_authorization_invalid_skill_id",
            )
        normalized_skill_ids.add(skill_id)
    if policy.action != PolicyAction.ALLOW:
        return AllowedToolSet()

    selected_tools = tuple(
        definition
        for definition in registry.list_definitions()
        if (not definition.skill_ids or normalized_skill_ids.intersection(definition.skill_ids))
        and definition.effect.value in policy.allowed_effects
    )
    return AllowedToolSet(
        tool_names=tuple(definition.name for definition in selected_tools),
    )
