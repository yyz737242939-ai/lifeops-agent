import json
from copy import deepcopy
from typing import Any

from app.runtime.context_types import ContextUnit
from app.utils.json_file import parse_json_object
from app.utils.serialization import json_safe


SUMMARY_VERSION = 1
MAX_ITEMS_PER_SECTION = 20
MAX_TEXT_PREVIEW_CHARS = 180


def empty_summary() -> dict[str, Any]:
    return {
        "summary_version": SUMMARY_VERSION,
        "source_unit_ids": [],
        "covered_until_unit_id": None,
        "user_goals": [],
        "successful_actions": [],
        "failed_actions": [],
        "pending_confirmations": [],
        "important_entities": [],
        "open_questions": [],
        "notes": [],
    }


def compact_units(
    previous_summary: dict[str, Any] | None,
    evicted_units: list[ContextUnit],
) -> dict[str, Any]:
    summary = _normalized_summary(previous_summary)
    for unit in evicted_units:
        if unit.unit_id not in summary["source_unit_ids"]:
            summary["source_unit_ids"].append(unit.unit_id)
        summary["covered_until_unit_id"] = unit.unit_id
        _compact_unit(summary, unit)

    for key in (
        "user_goals",
        "successful_actions",
        "failed_actions",
        "pending_confirmations",
        "important_entities",
        "open_questions",
        "notes",
    ):
        summary[key] = summary[key][-MAX_ITEMS_PER_SECTION:]
    return summary


def summary_to_message(summary: dict[str, Any]) -> dict[str, str]:
    return {
        "role": "system",
        "content": (
            "[Context summary]\n"
            + json.dumps(json_safe(summary), ensure_ascii=False, sort_keys=True)
        ),
    }


def _normalized_summary(previous_summary: dict[str, Any] | None) -> dict[str, Any]:
    summary = empty_summary()
    if not previous_summary:
        return summary
    copied = deepcopy(previous_summary)
    for key in summary:
        if key in copied:
            summary[key] = copied[key]
    summary["summary_version"] = SUMMARY_VERSION
    return summary


def _compact_unit(summary: dict[str, Any], unit: ContextUnit) -> None:
    if unit.kind == "user":
        _append_unique(
            summary["user_goals"],
            {
                "unit_id": unit.unit_id,
                "text": _message_text(unit.messages[0]),
            },
        )
        return

    if unit.kind == "tool":
        _compact_tool_unit(summary, unit)
        return

    if unit.protected:
        _append_unique(
            summary["pending_confirmations"],
            {
                "unit_id": unit.unit_id,
                "reason": "protected_context_unit",
                "metadata": unit.metadata,
            },
        )


def _compact_tool_unit(summary: dict[str, Any], unit: ContextUnit) -> None:
    tool_name = unit.metadata.get("tool_name")
    call_id = unit.metadata.get("call_id")
    result = _tool_result(unit)
    base = {
        "unit_id": unit.unit_id,
        "tool_name": tool_name,
        "call_id": call_id,
    }
    if result is None:
        _append_unique(summary["notes"], {**base, "note": "tool_result_unparsed"})
        return

    ok = result.get("ok")
    action = result.get("action") or tool_name
    record = {**base, "action": action}
    if ok is True:
        _append_unique(summary["successful_actions"], record)
    elif ok is False:
        _append_unique(
            summary["failed_actions"],
            {
                **record,
                "error": result.get("error"),
            },
        )

    for key in ("id", "todo_id", "expense_id", "ref_id"):
        if key in result:
            _append_unique(
                summary["important_entities"],
                {
                    "unit_id": unit.unit_id,
                    "type": key,
                    "value": result[key],
                },
            )


def _tool_result(unit: ContextUnit) -> dict[str, Any] | None:
    for message in unit.messages:
        if _message_field(message, "type") != "function_call_output":
            continue
        output = _message_field(message, "output")
        if isinstance(output, dict):
            return output
        if isinstance(output, str):
            return parse_json_object(output)
    return None


def _message_text(message: Any) -> str:
    content = _message_field(message, "content")
    if isinstance(content, str):
        text = content
    else:
        text = json.dumps(json_safe(content), ensure_ascii=False)
    if len(text) <= MAX_TEXT_PREVIEW_CHARS:
        return text
    return f"{text[:MAX_TEXT_PREVIEW_CHARS]}..."


def _message_field(message: Any, field: str) -> Any:
    if isinstance(message, dict):
        return message.get(field)
    return getattr(message, field, None)


def _append_unique(items: list[Any], item: Any) -> None:
    if item not in items:
        items.append(item)
