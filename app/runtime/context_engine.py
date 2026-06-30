import json
from collections import Counter
from typing import Any, cast

from app.runtime.context_types import (
    ContextAssembly,
    ContextUnit,
    ContextUnitKind,
    estimate_tokens_from_chars,
)
from app.utils.serialization import json_safe


class ContextEngine:
    """Build model input from full conversation history.

    The first implementation is intentionally pass-through: it reports units and
    budget estimates but does not crop, summarize, or reorder messages.
    """

    def assemble(
        self,
        messages: list[Any],
        *,
        instructions: str | None = None,
        tools: list[Any] | tuple[Any, ...] | None = None,
    ) -> ContextAssembly:
        units = self._build_units(messages)
        serialized = json_safe(messages)
        json_char_count = len(json.dumps(serialized, ensure_ascii=False))
        report = {
            "mode": "pass_through_with_units",
            "message_count": len(messages),
            "unit_count": len(units),
            "estimated_input_tokens": estimate_tokens_from_chars(json_char_count),
            "json_char_count": json_char_count,
            "instruction_chars": len(instructions or ""),
            "tool_schema_count": len(tools or ()),
            "tool_schema_chars": len(
                json.dumps(json_safe(list(tools or ())), ensure_ascii=False)
            ),
            "unit_breakdown": dict(Counter(unit.kind for unit in units)),
            "protected_unit_count": sum(1 for unit in units if unit.protected),
            "units": [self._unit_report(unit) for unit in units],
        }
        return ContextAssembly(input_messages=list(messages), report=report)

    def after_turn(self, messages: list[Any]) -> dict[str, Any]:
        return {
            "compacted": False,
            "reason": "pass_through",
            "message_count": len(messages),
        }

    def _build_units(self, messages: list[Any]) -> list[ContextUnit]:
        units: list[ContextUnit] = []
        index = 0
        while index < len(messages):
            message = messages[index]
            message_type = _message_type(message)
            call_id = _message_call_id(message)

            if message_type == "function_call":
                unit_messages = [message]
                protected = True
                metadata = {
                    "type": "function_call_pair",
                    "call_id": call_id,
                    "tool_name": _message_name(message),
                    "paired_observation": False,
                }
                if (
                    index + 1 < len(messages)
                    and _message_type(messages[index + 1]) == "function_call_output"
                    and _message_call_id(messages[index + 1]) == call_id
                ):
                    unit_messages.append(messages[index + 1])
                    protected = False
                    metadata["paired_observation"] = True
                    index += 1
                units.append(
                    self._new_unit(
                        len(units),
                        "tool",
                        unit_messages,
                        protected=protected,
                        metadata=metadata,
                    )
                )
            elif message_type == "function_call_output":
                units.append(
                    self._new_unit(
                        len(units),
                        "tool",
                        [message],
                        protected=True,
                        metadata={
                            "type": "orphan_function_call_output",
                            "call_id": call_id,
                        },
                    )
                )
            elif _message_role(message) == "user":
                units.append(self._new_unit(len(units), "user", [message]))
            elif _message_role(message) == "assistant" or message_type == "message":
                units.append(self._new_unit(len(units), "assistant", [message]))
            else:
                units.append(
                    self._new_unit(
                        len(units),
                        "system_note",
                        [message],
                        protected=True,
                        metadata={"type": message_type or type(message).__name__},
                    )
                )
            index += 1
        return units

    def _new_unit(
        self,
        index: int,
        kind: ContextUnitKind,
        messages: list[Any],
        *,
        protected: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> ContextUnit:
        serialized = json_safe(messages)
        char_count = len(json.dumps(serialized, ensure_ascii=False))
        return ContextUnit(
            unit_id=f"u_{index + 1:04d}",
            kind=cast(ContextUnitKind, kind),
            messages=list(messages),
            protected=protected,
            token_estimate=estimate_tokens_from_chars(char_count),
            char_count=char_count,
            metadata=metadata or {},
        )

    @staticmethod
    def _unit_report(unit: ContextUnit) -> dict[str, Any]:
        return {
            "unit_id": unit.unit_id,
            "kind": unit.kind,
            "message_count": len(unit.messages),
            "protected": unit.protected,
            "token_estimate": unit.token_estimate,
            "char_count": unit.char_count,
            "metadata": unit.metadata,
        }


def _message_field(message: Any, field: str) -> Any:
    if isinstance(message, dict):
        return message.get(field)
    return getattr(message, field, None)


def _message_type(message: Any) -> str | None:
    return _message_field(message, "type")


def _message_role(message: Any) -> str | None:
    return _message_field(message, "role")


def _message_call_id(message: Any) -> str | None:
    return _message_field(message, "call_id")


def _message_name(message: Any) -> str | None:
    return _message_field(message, "name")
