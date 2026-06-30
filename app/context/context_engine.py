import json
from collections import Counter
from typing import Any, cast

from app.context.context_budget import ContextBudgetConfig
from app.context.context_compactor import compact_units
from app.context.context_store import ContextStore
from app.context.context_types import (
    ContextAssembly,
    ContextUnit,
    ContextUnitKind,
    estimate_tokens_from_chars,
)
from app.utils.serialization import json_safe


class ContextEngine:
    """Build model input from full conversation history.

    Full history remains the source of truth; assemble returns the current
    working context that should be sent to the model.
    """

    COMPACTED_HISTORY_NOTE = (
        "[Context note] Earlier conversation exists but has been compacted. "
        "Detailed summary is not available yet."
    )

    def __init__(
        self,
        *,
        budget_config: ContextBudgetConfig | None = None,
        store: ContextStore | None = None,
    ) -> None:
        self.budget_config = budget_config or ContextBudgetConfig()
        self.store = store or ContextStore()

    def assemble(
        self,
        messages: list[Any],
        *,
        instructions: str | None = None,
        tools: list[Any] | tuple[Any, ...] | None = None,
    ) -> ContextAssembly:
        self.store.replace_full_messages(messages)
        units = self._build_units(messages)
        selected_units, evicted_units, recent_token_count = self._select_units(units)
        input_messages = self._messages_from_units(selected_units)
        summary_inserted = bool(evicted_units and self.store.summary_message)
        placeholder_inserted = bool(evicted_units and not self.store.summary_message)
        if summary_inserted and self.store.summary_message is not None:
            input_messages.insert(0, self.store.summary_message)
        elif placeholder_inserted:
            input_messages.insert(0, self._summary_placeholder_message())

        serialized = json_safe(messages)
        json_char_count = len(json.dumps(serialized, ensure_ascii=False))
        assembled_serialized = json_safe(input_messages)
        assembled_json_char_count = len(
            json.dumps(assembled_serialized, ensure_ascii=False)
        )
        report = {
            "mode": (
                "windowed_with_summary"
                if summary_inserted
                else (
                    "windowed_with_placeholder_summary"
                    if evicted_units
                    else "pass_through_with_units"
                )
            ),
            "raw_message_count": len(messages),
            "message_count": len(messages),
            "assembled_message_count": len(input_messages),
            "unit_count": len(units),
            "selected_unit_count": len(selected_units),
            "evicted_unit_count": len(evicted_units),
            "estimated_input_tokens": estimate_tokens_from_chars(json_char_count),
            "assembled_estimated_input_tokens": estimate_tokens_from_chars(
                assembled_json_char_count
            ),
            "json_char_count": json_char_count,
            "assembled_json_char_count": assembled_json_char_count,
            "instruction_chars": len(instructions or ""),
            "tool_schema_count": len(tools or ()),
            "tool_schema_chars": len(
                json.dumps(json_safe(list(tools or ())), ensure_ascii=False)
            ),
            "unit_breakdown": dict(Counter(unit.kind for unit in units)),
            "protected_unit_count": sum(1 for unit in units if unit.protected),
            "selected_unit_ids": [unit.unit_id for unit in selected_units],
            "evicted_unit_ids": [unit.unit_id for unit in evicted_units],
            "recent_window_tokens": recent_token_count,
            "recent_window_budget_tokens": (
                self.budget_config.effective_recent_window_tokens
            ),
            "summary_inserted": summary_inserted,
            "placeholder_summary_inserted": placeholder_inserted,
            "summary_source_unit_count": len(
                self.store.summary.get("source_unit_ids", [])
                if self.store.summary
                else []
            ),
            "units": [self._unit_report(unit) for unit in units],
        }
        return ContextAssembly(input_messages=input_messages, report=report)

    def after_turn(self, messages: list[Any]) -> dict[str, Any]:
        self.store.replace_full_messages(messages)
        units = self._build_units(messages)
        _selected_units, evicted_units, _recent_token_count = self._select_units(units)
        if not evicted_units:
            return {
                "compacted": False,
                "reason": "within_recent_window",
                "message_count": len(messages),
                "evicted_unit_count": 0,
            }

        summary = compact_units(self.store.summary, evicted_units)
        self.store.replace_summary(summary)
        return {
            "compacted": True,
            "reason": "rolling_summary_updated",
            "message_count": len(messages),
            "evicted_unit_count": len(evicted_units),
            "summary_source_unit_count": len(summary["source_unit_ids"]),
            "covered_until_unit_id": summary["covered_until_unit_id"],
        }

    def _select_units(
        self, units: list[ContextUnit]
    ) -> tuple[list[ContextUnit], list[ContextUnit], int]:
        if not units:
            return [], [], 0

        selected_indexes = {
            index for index, unit in enumerate(units) if unit.protected
        }
        recent_token_budget = self.budget_config.effective_recent_window_tokens
        recent_token_count = 0
        newest_index = len(units) - 1

        for index in range(newest_index, -1, -1):
            unit = units[index]
            must_keep_newest = index == newest_index
            if (
                not must_keep_newest
                and recent_token_count + unit.token_estimate > recent_token_budget
            ):
                break
            selected_indexes.add(index)
            recent_token_count += unit.token_estimate

        selected_units = [
            unit for index, unit in enumerate(units) if index in selected_indexes
        ]
        evicted_units = [
            unit for index, unit in enumerate(units) if index not in selected_indexes
        ]
        return selected_units, evicted_units, recent_token_count

    @classmethod
    def _summary_placeholder_message(cls) -> dict[str, str]:
        return {"role": "system", "content": cls.COMPACTED_HISTORY_NOTE}

    @staticmethod
    def _messages_from_units(units: list[ContextUnit]) -> list[Any]:
        messages: list[Any] = []
        for unit in units:
            messages.extend(unit.messages)
        return messages

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
