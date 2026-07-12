from __future__ import annotations

import unittest

from app.policy.models import PolicyAction, PolicyDecision
from app.tools.authorization import resolve_allowed_tools
from app.tools.errors import ToolAuthorizationError
from app.tools.models import (
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
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"Tool {name}.",
        input_schema=_SCHEMA,
        output_schema=_SCHEMA,
        effect=effect,
        risk=ToolRisk.LOW,
    )


def _handler(arguments: dict[str, object]) -> ToolResult:
    return ToolResult(
        call_id="call_test",
        tool_name="test.tool",
        status=ToolCallStatus.SUCCEEDED,
        output={},
    )


class ToolAuthorizationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ToolRegistry(
            [
                (_definition("research.sources_read"), _handler),
                (
                    _definition(
                        "travel.itinerary_write",
                        effect=ToolEffect.WRITE,
                    ),
                    _handler,
                ),
            ]
        )

    def test_policy_allowed_read_tool_is_selected(self) -> None:
        allowed = resolve_allowed_tools(
            PolicyDecision(
                action=PolicyAction.ALLOW,
                allowed_tools=["research.sources_read"],
            ),
            self.registry,
        )

        self.assertEqual(allowed.tool_names, ("research.sources_read",))

    def test_policy_allowed_write_tool_is_selected_without_secondary_scope(self) -> None:
        allowed = resolve_allowed_tools(
            PolicyDecision(
                action=PolicyAction.ALLOW,
                allowed_tools=["travel.itinerary_write"],
            ),
            self.registry,
        )

        self.assertEqual(allowed.tool_names, ("travel.itinerary_write",))

    def test_empty_allowed_tools_and_non_allow_policy_fail_closed(self) -> None:
        self.assertEqual(
            resolve_allowed_tools(
                PolicyDecision(action=PolicyAction.ALLOW), self.registry
            ).tool_names,
            (),
        )
        self.assertEqual(
            resolve_allowed_tools(
                PolicyDecision(action=PolicyAction.DENY), self.registry
            ).tool_names,
            (),
        )

    def test_unknown_policy_tool_is_rejected(self) -> None:
        policy = PolicyDecision(
            action=PolicyAction.ALLOW,
            allowed_tools=["unknown.tool"],
        )

        with self.assertRaises(ToolAuthorizationError) as caught:
            resolve_allowed_tools(policy, self.registry)

        self.assertEqual(
            caught.exception.code, "tool_authorization_unknown_allowed_tool"
        )

    def test_allowed_tool_set_filters_model_catalog(self) -> None:
        allowed = resolve_allowed_tools(
            PolicyDecision(
                action=PolicyAction.ALLOW,
                allowed_tools=["research.sources_read"],
            ),
            self.registry,
        )

        catalog = self.registry.model_catalog(allowed.tool_names)

        self.assertEqual(tuple(item["name"] for item in catalog), allowed.tool_names)


if __name__ == "__main__":
    unittest.main()
