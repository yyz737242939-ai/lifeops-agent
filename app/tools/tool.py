import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from app.memory import activity_catalog, daily_log_store, expense_store, todo_store
from app.memory.activity_catalog import ActivityGoal, CostLevel, Energy, Location, Mood
from app.memory.daily_log_store import Energy as DailyEnergy
from app.memory.daily_log_store import Mood as DailyMood
from app.memory.expense_store import BudgetPeriod
from app.memory.todo_store import Todo, TodoPriority
from app.runtime.context_ref_store import read_context_ref as load_context_ref
from app.runtime.errors import classify_tool_exception, normalize_tool_result
from app.runtime.idempotency_store import get_result as get_idempotent_result
from app.runtime.idempotency_store import save_result as save_idempotent_result


ToolParameters = dict[str, Any]
ToolResult = dict[str, Any]


class ToolEffect(StrEnum):
    READ = "read"
    WRITE = "write"


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: ToolParameters
    function: Callable[..., ToolResult]
    effect: ToolEffect
    idempotent: bool
    retryable: bool
    timeout_seconds: float

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    def metadata(self) -> dict[str, Any]:
        return {
            "effect": self.effect.value,
            "idempotent": self.idempotent,
            "retryable": self.retryable,
            "timeout_seconds": self.timeout_seconds,
        }


TOOLS: dict[str, ToolDefinition] = {}
_TOOL_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="lifeops-tool")


def register_tool(
    name: str,
    description: str,
    parameters: ToolParameters,
    *,
    effect: ToolEffect = ToolEffect.READ,
    idempotent: bool = True,
    retryable: bool = True,
    timeout_seconds: float = 10.0,
) -> Callable[[Callable[..., ToolResult]], Callable[..., ToolResult]]:
    def decorator(function: Callable[..., ToolResult]) -> Callable[..., ToolResult]:
        TOOLS[name] = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            function=function,
            effect=effect,
            idempotent=idempotent,
            retryable=retryable,
            timeout_seconds=timeout_seconds,
        )
        return function

    return decorator


def _json_safe(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _empty_parameters() -> ToolParameters:
    return {
        "type": "object",
        "properties": {},
        "required": [],
    }


def _todo_parameters(required: list[str]) -> ToolParameters:
    return {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Todo task title, for example: review Agent notes.",
            },
            "due_date": {
                "type": "string",
                "description": (
                    "Optional due date in YYYY-MM-DD format. Use an empty string "
                    "to clear the due date when updating a todo."
                ),
            },
            "priority": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "description": "Task priority. Use medium when the user does not specify it.",
            },
        },
        "required": required,
    }


def _todo_id_parameters() -> ToolParameters:
    return {
        "type": "object",
        "properties": {
            "todo_id": {
                "type": "integer",
                "description": "The id of the todo task.",
            }
        },
        "required": ["todo_id"],
    }


def _update_todo_parameters() -> ToolParameters:
    parameters = _todo_parameters(required=[])
    parameters["properties"] = {
        "todo_id": {
            "type": "integer",
            "description": "The id of the todo task to update.",
        },
        **parameters["properties"],
    }
    parameters["required"] = ["todo_id"]
    return parameters


def _todo_to_dict(todo: Todo) -> dict[str, Any]:
    return todo.model_dump(mode="json")


def _model_to_dict(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json")


@register_tool(
    name="get_current_time",
    description="Get the current local system time.",
    parameters=_empty_parameters(),
)
def get_current_time() -> ToolResult:
    now = datetime.now()
    return {
        "ok": True,
        "action": "get_current_time",
        "current_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "current_date": now.date().isoformat(),
    }


@register_tool(
    name="add_todo",
    description=(
        "Add a todo task. Use this when the user wants to remember, add, "
        "schedule, or track something they need to do."
    ),
    parameters=_todo_parameters(required=["title"]),
    effect=ToolEffect.WRITE,
    idempotent=False,
    retryable=False,
)
def add_todo(
    title: str,
    due_date: str | None = None,
    priority: TodoPriority = "medium",
) -> ToolResult:
    todo = todo_store.add_todo(title=title, due_date=due_date, priority=priority)
    return {
        "ok": True,
        "action": "add_todo",
        "todo": _todo_to_dict(todo),
    }


@register_tool(
    name="list_todos",
    description="List all todo tasks with their ids, status, priority, and due dates.",
    parameters=_empty_parameters(),
)
def list_todos() -> ToolResult:
    todos = todo_store.list_todos()
    return {
        "ok": True,
        "action": "list_todos",
        "count": len(todos),
        "todos": [_todo_to_dict(todo) for todo in todos],
    }


@register_tool(
    name="record_daily_state",
    description=(
        "Record or update the user's daily wellbeing state, including sleep, "
        "mood, energy, or a short note."
    ),
    parameters={
        "type": "object",
        "properties": {
            "log_date": {
                "type": "string",
                "description": "Optional date in YYYY-MM-DD format. Defaults to today.",
            },
            "sleep_hours": {
                "type": "number",
                "description": "Optional sleep duration in hours, from 0 to 24.",
            },
            "mood": {
                "type": "string",
                "enum": ["bad", "neutral", "good"],
                "description": "Optional mood for the day.",
            },
            "energy": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "description": "Optional energy level for the day.",
            },
            "note": {
                "type": "string",
                "description": "Optional short note about the user's state.",
            },
        },
        "required": [],
    },
    effect=ToolEffect.WRITE,
    idempotent=True,
    retryable=True,
)
def record_daily_state(
    log_date: str | None = None,
    sleep_hours: float | None = None,
    mood: DailyMood | None = None,
    energy: DailyEnergy | None = None,
    note: str | None = None,
) -> ToolResult:
    log = daily_log_store.upsert_daily_log(
        log_date=log_date,
        sleep_hours=sleep_hours,
        mood=mood,
        energy=energy,
        note=note,
    )
    return {
        "ok": True,
        "action": "record_daily_state",
        "daily_log": _model_to_dict(log),
    }


@register_tool(
    name="get_daily_state",
    description="Get the user's wellbeing state for a specific date or today.",
    parameters={
        "type": "object",
        "properties": {
            "log_date": {
                "type": "string",
                "description": "Optional date in YYYY-MM-DD format. Defaults to today.",
            }
        },
        "required": [],
    },
)
def get_daily_state(log_date: str | None = None) -> ToolResult:
    log = daily_log_store.get_daily_log(log_date=log_date)
    return {
        "ok": True,
        "action": "get_daily_state",
        "daily_log": _model_to_dict(log) if log is not None else None,
    }


@register_tool(
    name="list_daily_logs",
    description="List recent daily wellbeing logs for trend-aware planning.",
    parameters={
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": "Number of recent days to list. Defaults to 7.",
            },
            "end_date": {
                "type": "string",
                "description": "Optional end date in YYYY-MM-DD format. Defaults to today.",
            },
        },
        "required": [],
    },
)
def list_daily_logs(days: int = 7, end_date: str | None = None) -> ToolResult:
    logs = daily_log_store.list_daily_logs(days=days, end_date=end_date)
    return {
        "ok": True,
        "action": "list_daily_logs",
        "count": len(logs),
        "daily_logs": [_model_to_dict(log) for log in logs],
    }


@register_tool(
    name="record_expense",
    description="Record a spending item when the user reports a concrete expense.",
    parameters={
        "type": "object",
        "properties": {
            "amount": {
                "type": "number",
                "description": "Expense amount as a positive number.",
            },
            "category": {
                "type": "string",
                "description": "Expense category, for example food, transport, rent.",
            },
            "description": {
                "type": "string",
                "description": "Short description of what was purchased.",
            },
            "spent_date": {
                "type": "string",
                "description": "Optional date in YYYY-MM-DD format. Defaults to today.",
            },
        },
        "required": ["amount", "category", "description"],
    },
    effect=ToolEffect.WRITE,
    idempotent=False,
    retryable=False,
)
def record_expense(
    amount: float,
    category: str,
    description: str,
    spent_date: str | None = None,
) -> ToolResult:
    expense = expense_store.add_expense(
        amount=amount,
        category=category,
        description=description,
        spent_date=spent_date,
    )
    return {
        "ok": True,
        "action": "record_expense",
        "expense": _model_to_dict(expense),
    }


@register_tool(
    name="list_expenses",
    description="List expense records, optionally filtered by date range or category.",
    parameters={
        "type": "object",
        "properties": {
            "start_date": {
                "type": "string",
                "description": "Optional start date in YYYY-MM-DD format.",
            },
            "end_date": {
                "type": "string",
                "description": "Optional end date in YYYY-MM-DD format.",
            },
            "category": {
                "type": "string",
                "description": "Optional category filter.",
            },
            "limit": {
                "type": "integer",
                "description": "Optional maximum number of records to return.",
            },
        },
        "required": [],
    },
)
def list_expenses(
    start_date: str | None = None,
    end_date: str | None = None,
    category: str | None = None,
    limit: int | None = None,
) -> ToolResult:
    expenses = expense_store.list_expenses(
        start_date=start_date,
        end_date=end_date,
        category=category,
        limit=limit,
    )
    return {
        "ok": True,
        "action": "list_expenses",
        "count": len(expenses),
        "expenses": [_model_to_dict(expense) for expense in expenses],
    }


@register_tool(
    name="summarize_spending",
    description="Summarize spending totals and category totals for a date range.",
    parameters={
        "type": "object",
        "properties": {
            "start_date": {
                "type": "string",
                "description": "Optional start date in YYYY-MM-DD format.",
            },
            "end_date": {
                "type": "string",
                "description": "Optional end date in YYYY-MM-DD format.",
            },
            "category": {
                "type": "string",
                "description": "Optional category filter.",
            },
        },
        "required": [],
    },
)
def summarize_spending(
    start_date: str | None = None,
    end_date: str | None = None,
    category: str | None = None,
) -> ToolResult:
    summary = expense_store.summarize_expenses(
        start_date=start_date,
        end_date=end_date,
        category=category,
    )
    return {
        "ok": True,
        "action": "summarize_spending",
        "summary": summary,
    }


@register_tool(
    name="set_budget",
    description="Set a budget for a category and period.",
    parameters={
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "Budget category, for example food or transport.",
            },
            "amount": {
                "type": "number",
                "description": "Budget amount as a positive number.",
            },
            "period": {
                "type": "string",
                "enum": ["daily", "weekly", "monthly"],
                "description": "Budget period. Defaults to weekly.",
            },
        },
        "required": ["category", "amount"],
    },
    effect=ToolEffect.WRITE,
    idempotent=True,
    retryable=True,
)
def set_budget(
    category: str,
    amount: float,
    period: BudgetPeriod = "weekly",
) -> ToolResult:
    budget = expense_store.set_budget(
        category=category,
        amount=amount,
        period=period,
    )
    return {
        "ok": True,
        "action": "set_budget",
        "budget": _model_to_dict(budget),
    }


@register_tool(
    name="check_budget",
    description="Check spending against a stored budget for a category and period.",
    parameters={
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "Budget category to check.",
            },
            "period": {
                "type": "string",
                "enum": ["daily", "weekly", "monthly"],
                "description": "Budget period. Defaults to weekly.",
            },
            "anchor_date": {
                "type": "string",
                "description": "Optional date in YYYY-MM-DD format used to choose the period.",
            },
        },
        "required": ["category"],
    },
)
def check_budget(
    category: str,
    period: BudgetPeriod = "weekly",
    anchor_date: str | None = None,
) -> ToolResult:
    budget = expense_store.get_budget(category=category, period=period)
    start_date, end_date = expense_store.period_range(
        period=period,
        anchor_date=anchor_date,
    )
    summary = expense_store.summarize_expenses(
        start_date=start_date,
        end_date=end_date,
        category=category,
    )
    if budget is None:
        return {
            "ok": False,
            "action": "check_budget",
            "error": "budget_not_found",
            "category": category,
            "period": period,
            "start_date": start_date,
            "end_date": end_date,
            "spending_summary": summary,
        }

    spent = float(summary["total_amount"])
    remaining = round(budget.amount - spent, 2)
    return {
        "ok": True,
        "action": "check_budget",
        "category": category,
        "period": period,
        "start_date": start_date,
        "end_date": end_date,
        "budget": _model_to_dict(budget),
        "spent": spent,
        "remaining": remaining,
        "is_over_budget": remaining < 0,
        "spending_summary": summary,
    }


@register_tool(
    name="recommend_activities",
    description=(
        "Recommend life activities or breaks that fit energy, mood, time, budget, "
        "location, and goal constraints."
    ),
    parameters={
        "type": "object",
        "properties": {
            "energy": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "description": "Optional current energy level.",
            },
            "mood": {
                "type": "string",
                "enum": ["bad", "neutral", "good"],
                "description": "Optional current mood.",
            },
            "available_minutes": {
                "type": "integer",
                "description": "Optional maximum activity duration.",
            },
            "budget_level": {
                "type": "string",
                "enum": ["free", "low", "medium"],
                "description": "Optional maximum cost level.",
            },
            "location": {
                "type": "string",
                "enum": ["home", "nearby", "outside"],
                "description": "Optional location constraint.",
            },
            "goal": {
                "type": "string",
                "enum": ["recover", "focus", "socialize", "health", "fun"],
                "description": "Optional activity goal.",
            },
            "limit": {
                "type": "integer",
                "description": "Optional number of recommendations. Defaults to 3.",
            },
        },
        "required": [],
    },
)
def recommend_activities(
    energy: Energy | None = None,
    mood: Mood | None = None,
    available_minutes: int | None = None,
    budget_level: CostLevel | None = None,
    location: Location | None = None,
    goal: ActivityGoal | None = None,
    limit: int = 3,
) -> ToolResult:
    activities = activity_catalog.recommend_activities(
        energy=energy,
        mood=mood,
        available_minutes=available_minutes,
        budget_level=budget_level,
        location=location,
        goal=goal,
        limit=limit,
    )
    return {
        "ok": True,
        "action": "recommend_activities",
        "count": len(activities),
        "activities": [_model_to_dict(activity) for activity in activities],
    }


@register_tool(
    name="complete_todo",
    description="Mark a todo task as done by id.",
    parameters=_todo_id_parameters(),
    effect=ToolEffect.WRITE,
    idempotent=False,
    retryable=False,
)
def complete_todo(todo_id: int) -> ToolResult:
    todo = todo_store.complete_todo(todo_id)
    if todo is None:
        return {
            "ok": False,
            "action": "complete_todo",
            "error": "todo_not_found",
            "todo_id": todo_id,
        }

    return {
        "ok": True,
        "action": "complete_todo",
        "todo": _todo_to_dict(todo),
    }


@register_tool(
    name="update_todo",
    description=(
        "Update an existing todo task by id. Use this when the user wants to "
        "change a task title, due date, or priority."
    ),
    parameters=_update_todo_parameters(),
    effect=ToolEffect.WRITE,
    idempotent=True,
    retryable=True,
)
def update_todo(
    todo_id: int,
    title: str | None = None,
    due_date: str | None = None,
    priority: TodoPriority | None = None,
) -> ToolResult:
    todo = todo_store.update_todo(
        todo_id=todo_id,
        title=title,
        due_date=due_date,
        priority=priority,
    )
    if todo is None:
        return {
            "ok": False,
            "action": "update_todo",
            "error": "todo_not_found",
            "todo_id": todo_id,
        }

    return {
        "ok": True,
        "action": "update_todo",
        "todo": _todo_to_dict(todo),
    }


@register_tool(
    name="delete_todo",
    description="Delete a todo task by id.",
    parameters=_todo_id_parameters(),
    effect=ToolEffect.WRITE,
    idempotent=False,
    retryable=False,
)
def delete_todo(todo_id: int) -> ToolResult:
    todo = todo_store.delete_todo(todo_id)
    if todo is None:
        return {
            "ok": False,
            "action": "delete_todo",
            "error": "todo_not_found",
            "todo_id": todo_id,
        }

    return {
        "ok": True,
        "action": "delete_todo",
        "todo": _todo_to_dict(todo),
    }


@register_tool(
    name="plan_day",
    description=(
        "Create a practical day plan from open todo tasks. Use this when the "
        "user asks what to do today, how to arrange the day, or how to plan tasks."
    ),
    parameters={
        "type": "object",
        "properties": {
            "for_date": {
                "type": "string",
                "description": "Optional target date in YYYY-MM-DD format. Defaults to today.",
            }
        },
        "required": [],
    },
)
def plan_day(for_date: str | None = None) -> ToolResult:
    target_date = for_date or date.today().isoformat()
    try:
        date.fromisoformat(target_date)
    except ValueError:
        return {
            "ok": False,
            "action": "plan_day",
            "error": "invalid_date",
            "message": "for_date must use YYYY-MM-DD format.",
            "for_date": for_date,
        }

    todos = [todo for todo in todo_store.list_todos() if todo.status == "todo"]
    if not todos:
        return {
            "ok": True,
            "action": "plan_day",
            "for_date": target_date,
            "focus_tasks": [],
            "remaining_open_todos": 0,
            "suggested_rhythm": None,
        }

    due_or_overdue = [
        todo for todo in todos if todo.due_date is not None and todo.due_date <= target_date
    ]
    unscheduled = [todo for todo in todos if todo not in due_or_overdue]

    priority_rank = {"high": 0, "medium": 1, "low": 2}
    due_or_overdue.sort(key=lambda todo: (priority_rank[todo.priority], todo.due_date or ""))
    unscheduled.sort(key=lambda todo: (priority_rank[todo.priority], todo.created_at))

    ordered = due_or_overdue + unscheduled
    top_tasks = ordered[:5]

    return {
        "ok": True,
        "action": "plan_day",
        "for_date": target_date,
        "focus_tasks": [_todo_to_dict(todo) for todo in top_tasks],
        "remaining_open_todos": max(len(ordered) - len(top_tasks), 0),
        "suggested_rhythm": (
            "Start with due or high-priority tasks, then batch small items."
        ),
    }


@register_tool(
    name="read_context_ref",
    description=(
        "Read a full referenced context result when a compacted tool output says "
        "exact records are needed."
    ),
    parameters={
        "type": "object",
        "properties": {
            "ref_id": {
                "type": "string",
                "description": "Reference id returned by a compacted tool output.",
            }
        },
        "required": ["ref_id"],
    },
)
def read_context_ref(ref_id: str) -> ToolResult:
    payload = load_context_ref(ref_id)
    if payload is None:
        return {
            "ok": False,
            "action": "read_context_ref",
            "error": "context_ref_not_found",
            "ref_id": ref_id,
        }

    return {
        "ok": True,
        "action": "read_context_ref",
        "ref_id": ref_id,
        "tool_name": payload.get("tool_name"),
        "summary": payload.get("summary"),
        "full_result": payload.get("full_result"),
    }


def get_tool_schemas() -> list[dict[str, Any]]:
    return [tool.schema() for tool in TOOLS.values()]


TOOL_SCHEMAS = get_tool_schemas()


def call_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    allowed_tool_names: frozenset[str],
    idempotency_key: str | None = None,
) -> str:
    tool = TOOLS.get(name)

    if tool is None:
        result: ToolResult = normalize_tool_result(
            name,
            {"ok": False, "action": name, "error": "tool_not_found"},
        )
        return json.dumps(result, ensure_ascii=False)

    if name not in allowed_tool_names:
        result = normalize_tool_result(
            name,
            {
                "ok": False,
                "action": name,
                "error": "tool_not_allowed",
                "allowed_tools": [
                    tool_name for tool_name in TOOLS if tool_name in allowed_tool_names
                ],
            },
        )
        return json.dumps(result, ensure_ascii=False)

    if tool.effect == ToolEffect.WRITE and idempotency_key:
        cached_result = get_idempotent_result(idempotency_key)
        if cached_result is not None:
            replayed = dict(cached_result)
            replayed["idempotency"] = {
                "key": idempotency_key,
                "replayed": True,
            }
            return json.dumps(_json_safe(replayed), ensure_ascii=False)

    try:
        future = _TOOL_EXECUTOR.submit(tool.function, **arguments)
        result = future.result(timeout=tool.timeout_seconds)
    except FutureTimeoutError:
        future.cancel()
        result = classify_tool_exception(
            name,
            TimeoutError(f"{name} exceeded {tool.timeout_seconds} seconds"),
        )
    except Exception as error:
        result = classify_tool_exception(name, error)

    result = normalize_tool_result(name, result)

    if (
        tool.effect == ToolEffect.WRITE
        and idempotency_key
        and result.get("ok") is True
    ):
        stored_result = dict(result)
        stored_result["idempotency"] = {
            "key": idempotency_key,
            "replayed": False,
        }
        save_idempotent_result(idempotency_key, stored_result)
        result = stored_result

    return json.dumps(_json_safe(result), ensure_ascii=False)
