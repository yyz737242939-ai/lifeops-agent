import json
import time
import unittest
from unittest.mock import Mock, patch

from app.runtime.errors import ErrorType, normalize_tool_result
from app.tools.tool import (
    TOOLS,
    ToolDefinition,
    ToolEffect,
    call_tool,
)


def _temporary_tool(
    name: str,
    function,
    *,
    effect: ToolEffect = ToolEffect.READ,
    idempotent: bool = True,
    retryable: bool = True,
    timeout_seconds: float = 1.0,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description="test tool",
        parameters={"type": "object", "properties": {}, "required": []},
        function=function,
        effect=effect,
        idempotent=idempotent,
        retryable=retryable,
        timeout_seconds=timeout_seconds,
    )


class StructuredErrorTests(unittest.TestCase):
    def test_normalizes_business_error(self) -> None:
        result = normalize_tool_result(
            "check_budget",
            {"ok": False, "action": "check_budget", "error": "budget_not_found"},
        )

        self.assertEqual(result["error"]["type"], ErrorType.BUSINESS_ERROR.value)
        self.assertEqual(result["error"]["code"], "budget_not_found")
        self.assertFalse(result["error"]["retryable"])


class ToolReliabilityTests(unittest.TestCase):
    def test_write_idempotency_replays_saved_result(self) -> None:
        function = Mock(return_value={"ok": True, "action": "test_write", "id": 1})
        definition = _temporary_tool(
            "test_write",
            function,
            effect=ToolEffect.WRITE,
            idempotent=False,
            retryable=False,
        )
        cached = {
            "ok": True,
            "action": "test_write",
            "id": 1,
            "idempotency": {"key": "key-1", "replayed": False},
        }

        with (
            patch.dict(TOOLS, {"test_write": definition}),
            patch("app.tools.tool.get_idempotent_result", side_effect=[None, cached]),
            patch("app.tools.tool.save_idempotent_result") as save_result,
        ):
            first = json.loads(
                call_tool(
                    "test_write",
                    {},
                    allowed_tool_names=frozenset({"test_write"}),
                    idempotency_key="key-1",
                )
            )
            second = json.loads(
                call_tool(
                    "test_write",
                    {},
                    allowed_tool_names=frozenset({"test_write"}),
                    idempotency_key="key-1",
                )
            )

        self.assertEqual(function.call_count, 1)
        self.assertFalse(first["idempotency"]["replayed"])
        self.assertTrue(second["idempotency"]["replayed"])
        save_result.assert_called_once()

    def test_tool_timeout_returns_structured_retryable_error(self) -> None:
        def slow_tool() -> dict[str, object]:
            time.sleep(0.05)
            return {"ok": True, "action": "slow_tool"}

        definition = _temporary_tool(
            "slow_tool",
            slow_tool,
            timeout_seconds=0.001,
        )
        with patch.dict(TOOLS, {"slow_tool": definition}):
            result = json.loads(
                call_tool(
                    "slow_tool",
                    {},
                    allowed_tool_names=frozenset({"slow_tool"}),
                )
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["type"], "timeout")
        self.assertEqual(result["error"]["code"], "tool_timeout")
        self.assertTrue(result["error"]["retryable"])


if __name__ == "__main__":
    unittest.main()
