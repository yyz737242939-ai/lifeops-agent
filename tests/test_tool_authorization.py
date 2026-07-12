from __future__ import annotations

import unittest

from app.policy.models import PolicyAction, PolicyDecision
from app.tools.authorization import resolve_allowed_tools
from app.tools.errors import ToolAuthorizationError
from app.tools.models import (
    ToolCall,
    ToolCallStatus,
    ToolDefinition,
    ToolEffect,
    ToolResult,
    ToolRisk,
)
from app.tools.registry import ToolRegistry


_SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}


def _definition(
    name: str,
    *,
    effect: ToolEffect = ToolEffect.READ,
    skill_ids: tuple[str, ...] = (),
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"Tool {name}.",
        input_schema=_SCHEMA,
        output_schema=_SCHEMA,
        effect=effect,
        risk=ToolRisk.LOW,
        skill_ids=skill_ids,
    )


def _handler(call: ToolCall) -> ToolResult:
    return ToolResult(
        call_id=call.call_id,
        tool_name=call.tool_name,
        status=ToolCallStatus.SUCCEEDED,
        output={},
    )


class ToolAuthorizationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ToolRegistry(
            [
                (_definition("runtime.help"), _handler),
                (
                    _definition(
                        "research.sources_read",
                        effect=ToolEffect.EXTERNAL_READ,
                        skill_ids=("research",),
                    ),
                    _handler,
                ),
                (
                    _definition(
                        "travel.itinerary_write",
                        effect=ToolEffect.WRITE,
                        skill_ids=("travel",),
                    ),
                    _handler,
                ),
            ]
        )

    def test_skill_candidates_and_common_tools_are_filtered_by_effect(self) -> None:
        allowed = resolve_allowed_tools(
            ("research",),
            PolicyDecision(
                action=PolicyAction.ALLOW,
                allowed_effects=["read", "external_read"],
            ),
            self.registry,
        )

        self.assertEqual(
            allowed.tool_names,
            ("research.sources_read", "runtime.help"),
        )

    def test_policy_effect_prevents_skill_candidate_write_exposure(self) -> None:
        allowed = resolve_allowed_tools(
            ("travel",),
            PolicyDecision(
                action=PolicyAction.ALLOW,
                allowed_effects=["read", "external_read"],
            ),
            self.registry,
        )

        self.assertEqual(allowed.tool_names, ("runtime.help",))

    def test_write_effect_exposes_matching_skill_write_tool(self) -> None:
        allowed = resolve_allowed_tools(
            ("travel",),
            PolicyDecision(
                action=PolicyAction.ALLOW,
                allowed_effects=["write"],
            ),
            self.registry,
        )

        self.assertEqual(allowed.tool_names, ("travel.itinerary_write",))

    def test_empty_effects_and_non_allow_policy_fail_closed(self) -> None:
        self.assertEqual(
            resolve_allowed_tools(
                ("research",), PolicyDecision(action=PolicyAction.ALLOW), self.registry
            ).tool_names,
            (),
        )
        self.assertEqual(
            resolve_allowed_tools(
                ("research",), PolicyDecision(action=PolicyAction.DENY), self.registry
            ).tool_names,
            (),
        )

    def test_invalid_skill_ids_are_rejected(self) -> None:
        with self.assertRaises(ToolAuthorizationError) as caught:
            resolve_allowed_tools(
                ("",), PolicyDecision(action=PolicyAction.ALLOW), self.registry
            )

        self.assertEqual(caught.exception.code, "tool_authorization_invalid_skill_id")

    def test_allowed_tool_set_filters_model_catalog(self) -> None:
        allowed = resolve_allowed_tools(
            ("research",),
            PolicyDecision(
                action=PolicyAction.ALLOW,
                allowed_effects=["external_read"],
            ),
            self.registry,
        )

        catalog = self.registry.model_catalog(allowed.tool_names)

        self.assertEqual(tuple(item["name"] for item in catalog), allowed.tool_names)


if __name__ == "__main__":
    unittest.main()
