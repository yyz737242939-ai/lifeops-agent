import json
from collections import Counter
from datetime import date
from typing import Any

from app.context.context_ref_store import save_context_ref
from app.utils.json_file import parse_json_object


SUMMARY_CHAR_THRESHOLD = 1500
REFERENCE_CHAR_THRESHOLD = 4000
REFERENCE_LIST_THRESHOLD = 30
SUMMARY_LIST_THRESHOLDS = {
    "list_todos": 8,
    "list_expenses": 8,
    "list_daily_logs": 8,
    "recommend_activities": 3,
}
DEFAULT_SUMMARY_ITEM_LIMIT = 5


def _safe_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _top_items(
    items: list[dict[str, Any]], limit: int = DEFAULT_SUMMARY_ITEM_LIMIT
) -> list[dict[str, Any]]:
    return items[:limit]


def _summary_item_limit(requested_count: int | None) -> int:
    if requested_count is None:
        return DEFAULT_SUMMARY_ITEM_LIMIT
    return max(DEFAULT_SUMMARY_ITEM_LIMIT, requested_count)


def _summarize_todos(
    result: dict[str, Any],
    *,
    requested_count: int | None = None,
) -> dict[str, Any]:
    todos = result.get("todos", [])
    if not isinstance(todos, list):
        return {"count": result.get("count", 0)}

    today = date.today()
    open_todos = [todo for todo in todos if todo.get("status") == "todo"]
    done_todos = [todo for todo in todos if todo.get("status") == "done"]
    high_open = [
        todo for todo in open_todos if todo.get("priority") == "high"
    ]
    due_today = [
        todo
        for todo in open_todos
        if _safe_date(todo.get("due_date")) == today
    ]
    overdue = [
        todo
        for todo in open_todos
        if (due_date := _safe_date(todo.get("due_date"))) is not None
        and due_date < today
    ]
    priority_rank = {"high": 0, "medium": 1, "low": 2}
    open_todos.sort(
        key=lambda todo: (
            priority_rank.get(todo.get("priority", "medium"), 1),
            todo.get("due_date") or "9999-99-99",
            todo.get("id", 0),
        )
    )

    return {
        "count": len(todos),
        "open": len(open_todos),
        "done": len(done_todos),
        "high_priority_open": len(high_open),
        "due_today": len(due_today),
        "overdue": len(overdue),
        "top_open_items": _top_items(
            open_todos,
            limit=_summary_item_limit(requested_count),
        ),
    }


def _summarize_daily_logs(result: dict[str, Any]) -> dict[str, Any]:
    logs = result.get("daily_logs", [])
    if not isinstance(logs, list):
        return {"count": result.get("count", 0)}

    energy_counts = Counter(log.get("energy") for log in logs if log.get("energy"))
    mood_counts = Counter(log.get("mood") for log in logs if log.get("mood"))
    sleep_values = [
        log.get("sleep_hours")
        for log in logs
        if isinstance(log.get("sleep_hours"), (int, float))
    ]
    average_sleep = (
        round(sum(sleep_values) / len(sleep_values), 1) if sleep_values else None
    )

    return {
        "count": len(logs),
        "average_sleep_hours": average_sleep,
        "energy_counts": dict(energy_counts),
        "mood_counts": dict(mood_counts),
        "recent_logs": _top_items(list(reversed(logs)), limit=3),
    }


def _summarize_expenses(
    result: dict[str, Any],
    *,
    requested_count: int | None = None,
) -> dict[str, Any]:
    expenses = result.get("expenses", [])
    if isinstance(expenses, list):
        category_totals: dict[str, float] = {}
        for expense in expenses:
            category = str(expense.get("category", "uncategorized"))
            amount = expense.get("amount", 0)
            if isinstance(amount, (int, float)):
                category_totals[category] = round(
                    category_totals.get(category, 0) + amount,
                    2,
                )
        return {
            "count": len(expenses),
            "total_amount": round(
                sum(
                    expense.get("amount", 0)
                    for expense in expenses
                    if isinstance(expense.get("amount", 0), (int, float))
                ),
                2,
            ),
            "category_totals": category_totals,
            "recent_expenses": _top_items(
                expenses,
                limit=_summary_item_limit(requested_count),
            ),
        }

    summary = result.get("summary")
    if isinstance(summary, dict):
        return summary
    return {"count": result.get("count", 0)}


def _summarize_activities(result: dict[str, Any]) -> dict[str, Any]:
    activities = result.get("activities", [])
    if not isinstance(activities, list):
        return {"count": result.get("count", 0)}
    return {
        "count": len(activities),
        "top_activities": _top_items(activities, limit=3),
    }


def _summarize_generic(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in result.items()
        if key not in {"todos", "expenses", "daily_logs", "activities"}
    }


def summarize_tool_result(
    tool_name: str,
    result: dict[str, Any],
    *,
    requested_count: int | None = None,
) -> dict[str, Any]:
    """Build a domain-aware summary while preserving action-relevant fields."""
    summarizers = {
        "list_todos": _summarize_todos,
        "list_daily_logs": _summarize_daily_logs,
        "list_expenses": _summarize_expenses,
        "summarize_spending": _summarize_expenses,
        "recommend_activities": _summarize_activities,
    }
    summarizer = summarizers.get(tool_name, _summarize_generic)
    if summarizer in {_summarize_todos, _summarize_expenses}:
        return summarizer(result, requested_count=requested_count)
    return summarizer(result)


def _primary_list_count(result: dict[str, Any]) -> int:
    for key in ("todos", "expenses", "daily_logs", "activities"):
        value = result.get(key)
        if isinstance(value, list):
            return len(value)
    return 0


def _select_compaction_strategy(
    tool_name: str,
    *,
    original_chars: int,
    list_count: int,
) -> str:
    """Choose a strategy using stable size thresholds, independent of I/O."""
    if (
        original_chars >= REFERENCE_CHAR_THRESHOLD
        or list_count >= REFERENCE_LIST_THRESHOLD
    ):
        return "reference"

    list_threshold = SUMMARY_LIST_THRESHOLDS.get(tool_name)
    if original_chars >= SUMMARY_CHAR_THRESHOLD or (
        list_threshold is not None and list_count > list_threshold
    ):
        return "summary"
    return "none"


def _base_compaction_metadata(tool_name: str, original_chars: int) -> dict[str, Any]:
    return {
        "tool_name": tool_name,
        "strategy": "none",
        "original_chars": original_chars,
        "compacted_chars": original_chars,
        "ref_id": None,
    }


def _build_compacted_payload(
    tool_name: str,
    result: dict[str, Any],
    summary: dict[str, Any],
    *,
    strategy: str,
    ref_id: str | None = None,
) -> dict[str, Any]:
    payload = {
        "ok": True,
        "action": result.get("action", tool_name),
        "compacted": True,
        "compaction_strategy": strategy,
        "summary": summary,
    }
    if ref_id is not None:
        payload.update(
            {
                "ref_id": ref_id,
                "hint": "Use read_context_ref if exact records are needed.",
            }
        )
    return payload


def _summary_truncates_result(summary: dict[str, Any], list_count: int) -> bool:
    for key in ("top_open_items", "recent_expenses", "recent_logs", "top_activities"):
        value = summary.get(key)
        if isinstance(value, list):
            return len(value) < list_count
    return False


def _finish_compaction(
    payload: dict[str, Any],
    metadata: dict[str, Any],
    *,
    strategy: str,
    summary: dict[str, Any],
    ref_id: str | None = None,
) -> tuple[str, dict[str, Any]]:
    compacted_json = json.dumps(payload, ensure_ascii=False)
    metadata.update(
        {
            "strategy": strategy,
            "compacted_chars": len(compacted_json),
            "summary": summary,
        }
    )
    if ref_id is not None:
        metadata["ref_id"] = ref_id
    return compacted_json, metadata


def compact_tool_output(
    tool_name: str,
    result_json: str,
    *,
    requested_count: int | None = None,
) -> tuple[str, dict[str, Any]]:
    """Compact a successful tool result without losing later-action essentials."""
    parsed_result = parse_json_object(result_json)
    original_chars = len(result_json)
    metadata = _base_compaction_metadata(tool_name, original_chars)

    if not isinstance(parsed_result, dict):
        return result_json, metadata

    if tool_name == "read_context_ref":
        return result_json, metadata

    if parsed_result.get("ok") is False:
        return result_json, metadata

    summary = summarize_tool_result(
        tool_name,
        parsed_result,
        requested_count=requested_count,
    )
    list_count = _primary_list_count(parsed_result)
    strategy = _select_compaction_strategy(
        tool_name,
        original_chars=original_chars,
        list_count=list_count,
    )

    if strategy == "reference":
        ref_id = save_context_ref(
            tool_name=tool_name,
            full_result=parsed_result,
            summary=summary,
        )
        payload = _build_compacted_payload(
            tool_name,
            parsed_result,
            summary,
            strategy=strategy,
            ref_id=ref_id,
        )
        return _finish_compaction(
            payload,
            metadata,
            strategy=strategy,
            summary=summary,
            ref_id=ref_id,
        )

    if strategy == "summary":
        ref_id = None
        effective_strategy = strategy
        if _summary_truncates_result(summary, list_count):
            ref_id = save_context_ref(
                tool_name=tool_name,
                full_result=parsed_result,
                summary=summary,
            )
            effective_strategy = "summary_reference"
        payload = _build_compacted_payload(
            tool_name,
            parsed_result,
            summary,
            strategy=effective_strategy,
            ref_id=ref_id,
        )
        return _finish_compaction(
            payload,
            metadata,
            strategy=effective_strategy,
            summary=summary,
            ref_id=ref_id,
        )

    return result_json, metadata


def summarize_context_messages(messages: list[Any]) -> dict[str, Any]:
    """Describe current message composition without copying full context into Event."""
    type_counts: Counter[str] = Counter()
    tool_outputs: list[dict[str, Any]] = []

    for message in messages:
        if not isinstance(message, dict):
            type_counts[type(message).__name__] += 1
            continue

        message_type = str(message.get("type") or message.get("role") or "unknown")
        type_counts[message_type] += 1
        if message.get("type") == "function_call_output":
            output = message.get("output", "")
            output_text = str(output)
            parsed = parse_json_object(output_text)
            tool_outputs.append(
                {
                    "call_id": message.get("call_id"),
                    "chars": len(output_text),
                    "compaction_strategy": (
                        parsed.get("compaction_strategy")
                        if isinstance(parsed, dict)
                        else None
                    ),
                    "preview": output_text[:160],
                }
            )

    return {
        "message_count": len(messages),
        "message_type_counts": dict(type_counts),
        "tool_output_count": len(tool_outputs),
        "tool_outputs": tool_outputs[-5:],
    }
