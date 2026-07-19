from __future__ import annotations

import unittest

from app.tools.errors import ToolNotFoundError, ToolRegistryError, ToolSchemaError
from app.tools.models import (
    ToolCall,
    ToolCallStatus,
    ToolDefinition,
    ToolEffect,
    ToolResult,
    ToolRisk,
)
from app.tools.registry import ToolRegistry


def _definition(name: str = "research.sources_read") -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description="Read one approved research source.",
        input_schema={
            "type": "object",
            "properties": {
                "source_id": {"type": "string", "minLength": 1},
            },
            "required": ["source_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"content": {"type": "string"}},
            "required": ["content"],
            "additionalProperties": False,
        },
        effect=ToolEffect.EXTERNAL_READ,
        risk=ToolRisk.LOW,
    )


def _handler(call: ToolCall) -> ToolResult:
    return ToolResult(
        call_id=call.call_id,
        tool_name=call.tool_name,
        status=ToolCallStatus.SUCCEEDED,
        output={"content": str(call.arguments["source_id"])},
    )


class ToolRegistryTest(unittest.TestCase):
    def test_registry_binds_handler_and_lists_stably(self) -> None:
        registry = ToolRegistry()
        registry.register(_definition("travel.fixture_read"), _handler)
        registry.register(_definition(), _handler)

        self.assertEqual(
            tuple(item.name for item in registry.list_definitions()),
            ("research.sources_read", "travel.fixture_read"),
        )
        self.assertIs(registry.resolve("research.sources_read").handler, _handler)

    def test_registry_rejects_duplicate_names(self) -> None:
        registry = ToolRegistry([(_definition(), _handler)])

        with self.assertRaises(ToolRegistryError) as caught:
            registry.register(_definition(), _handler)

        self.assertEqual(caught.exception.code, "tool_registry_duplicate_name")

    def test_registry_reports_unknown_tool(self) -> None:
        with self.assertRaises(ToolNotFoundError) as caught:
            ToolRegistry().get("missing.tool")

        self.assertEqual(caught.exception.code, "tool_not_found")

    def test_registry_recursively_validates_schema(self) -> None:
        definition = _definition()
        definition.input_schema["properties"]["source_id"] = {"type": "unknown"}

        with self.assertRaises(ToolSchemaError) as caught:
            ToolRegistry([(definition, _handler)])

        self.assertEqual(caught.exception.code, "tool_schema_invalid")
        self.assertEqual(
            caught.exception.details["path"], "input_schema.properties.source_id"
        )

    def test_model_catalog_excludes_handler_and_returns_schema_copy(self) -> None:
        definition = _definition()
        registry = ToolRegistry([(definition, _handler)])

        catalog = registry.model_catalog()
        catalog[0]["input_schema"]["properties"].clear()

        self.assertNotIn("handler", catalog[0])
        self.assertIn("source_id", registry.get(definition.name).input_schema["properties"])


if __name__ == "__main__":
    unittest.main()
