import argparse
import json
import re
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from pydantic import ValidationError

from app.agents import Agent
from app.domains.activity_catalog import recommend_activities
from app.domains.daily_log_store import list_daily_logs, upsert_daily_log
from app.domains.expense_store import (
    add_expense,
    get_budget,
    list_expenses,
    period_range,
    set_budget,
    summarize_expenses,
)
from app.domains.todo_store import (
    add_todo,
    complete_todo,
    delete_todo,
    list_todos,
    update_todo,
)
from app.memory.memory_store import SemanticMemoryStore
from app.memory import memory_store as memory_store_module
from app.runtime.run_state import ActionStatus
from app.utils.time import today_iso


STATIC_DIR = Path(__file__).resolve().parent / "static"
TODO_ID_PATTERN = re.compile(r"^/api/todos/([0-9]+)/(complete|delete)$")
MEMORY_ID_PATTERN = re.compile(r"^/api/memories/([^/]+)/delete$")

_agent_lock = threading.RLock()
_agent: Agent | None = None


def get_product_agent() -> Agent:
    """Return the process-local Agent backing the product chat panel."""
    global _agent
    with _agent_lock:
        if _agent is None:
            _agent = Agent()
        return _agent


def _model_dump(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json")


def memory_store() -> SemanticMemoryStore:
    return SemanticMemoryStore(memory_store_module.SEMANTIC_MEMORIES_FILE)


def _recent_todos(limit: int = 5) -> list[dict[str, Any]]:
    todos = sorted(
        list_todos(),
        key=lambda item: (
            item.status == "done",
            item.due_date or "9999-12-31",
            item.id,
        ),
    )
    return [_model_dump(todo) for todo in todos[:limit]]


def build_dashboard() -> dict[str, Any]:
    todos = list_todos()
    logs = list_daily_logs(days=7)
    expense_summary = summarize_expenses()
    open_todos = [todo for todo in todos if todo.status == "todo"]
    latest_log = logs[-1] if logs else None
    activities = recommend_activities(
        energy=latest_log.energy if latest_log else None,
        mood=latest_log.mood if latest_log else None,
        limit=3,
    )
    return {
        "today": today_iso(),
        "todo_count": len(todos),
        "open_todo_count": len(open_todos),
        "recent_todos": _recent_todos(),
        "latest_wellbeing": _model_dump(latest_log) if latest_log else None,
        "expense_summary": expense_summary,
        "recommended_activities": [_model_dump(activity) for activity in activities],
    }


def build_initial_state() -> dict[str, Any]:
    return {
        "dashboard": build_dashboard(),
        "todos": [_model_dump(todo) for todo in list_todos()],
        "wellbeing": build_wellbeing_state(),
        "finance": build_finance_state(),
        "memories": build_memory_state(),
        "activities": [
            _model_dump(activity) for activity in recommend_activities(limit=4)
        ],
    }


def build_wellbeing_state(days: int = 7, end_date: str | None = None) -> dict[str, Any]:
    logs = list_daily_logs(days=days, end_date=end_date)
    return {
        "logs": [_model_dump(log) for log in logs],
        "filters": {
            "days": days,
            "end_date": end_date,
        },
    }


def build_memory_state(
    *,
    memory_type: str | None = None,
    tag: str | None = None,
) -> dict[str, Any]:
    memories = memory_store().list_memories(memory_type=memory_type, tag=tag)
    return {
        "items": [_model_dump(memory) for memory in memories],
        "filters": {
            "type": memory_type,
            "tag": tag,
        },
    }


def build_finance_state(
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    return {
        "summary": summarize_expenses(
            start_date=start_date,
            end_date=end_date,
            category=category,
        ),
        "recent_expenses": [
            _model_dump(expense)
            for expense in list_expenses(
                start_date=start_date,
                end_date=end_date,
                category=category,
                limit=8,
            )
        ],
        "filters": {
            "start_date": start_date,
            "end_date": end_date,
            "category": category,
        },
    }


def build_budget_status(category: str, period: str) -> dict[str, Any]:
    budget = get_budget(category, period)
    start_date, end_date = period_range(period)
    summary = summarize_expenses(
        start_date=start_date,
        end_date=end_date,
        category=category,
    )
    amount = budget.amount if budget else None
    spent = summary["total_amount"]
    remaining = None if amount is None else round(amount - spent, 2)
    return {
        "category": category,
        "period": period,
        "start_date": start_date,
        "end_date": end_date,
        "budget": _model_dump(budget) if budget else None,
        "spent": spent,
        "remaining": remaining,
        "over_budget": remaining is not None and remaining < 0,
    }


def _run_state_summary(agent: Agent) -> dict[str, Any] | None:
    run_state = agent.last_run_state
    if run_state is None:
        return None
    action_summaries = [
        {
            "tool_name": record.tool_name,
            "status": record.status.value,
            "is_write": record.tool_name.startswith(
                (
                    "add_",
                    "update_",
                    "complete_",
                    "delete_",
                    "record_",
                    "set_",
                    "save_",
                )
            ),
        }
        for record in run_state.action_records
    ]
    return {
        "run_id": run_state.run_id,
        "status": run_state.status.value,
        "stop_reason": run_state.stop_reason.value if run_state.stop_reason else None,
        "llm_rounds": run_state.chat_llm_round_count,
        "llm_requests": run_state.chat_llm_request_count,
        "tool_attempts": run_state.chat_tool_execution_attempt_count,
        "successful_actions": len(
            [
                record
                for record in run_state.action_records
                if record.status == ActionStatus.COMPLETED
            ]
        ),
        "failed_actions": len(
            [
                record
                for record in run_state.action_records
                if record.status == ActionStatus.FAILED
            ]
        ),
        "actions": action_summaries,
        "write_actions": [
            action for action in action_summaries if action["is_write"]
        ],
    }


def _json_error(message: str, status: HTTPStatus) -> tuple[dict[str, Any], HTTPStatus]:
    return {"error": message}, status


def _clean_optional_text(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def handle_api_request(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], HTTPStatus]:
    global _agent
    payload = payload or {}

    try:
        if method == "GET" and path == "/api/state":
            return build_initial_state(), HTTPStatus.OK

        if method == "POST" and path == "/api/todos":
            todo = add_todo(
                title=str(payload.get("title", "")),
                due_date=_clean_optional_text(payload, "due_date"),
                priority=payload.get("priority", "medium"),
            )
            return {"todo": _model_dump(todo), "dashboard": build_dashboard()}, HTTPStatus.CREATED

        match = TODO_ID_PATTERN.fullmatch(path)
        if method == "POST" and match:
            todo_id = int(match.group(1))
            action = match.group(2)
            todo = complete_todo(todo_id) if action == "complete" else delete_todo(todo_id)
            if todo is None:
                return _json_error("Todo not found", HTTPStatus.NOT_FOUND)
            return {"todo": _model_dump(todo), "dashboard": build_dashboard()}, HTTPStatus.OK

        if method == "PATCH" and path.startswith("/api/todos/"):
            todo_id = int(path.removeprefix("/api/todos/"))
            todo = update_todo(
                todo_id=todo_id,
                title=_clean_optional_text(payload, "title"),
                due_date=_clean_optional_text(payload, "due_date"),
                priority=_clean_optional_text(payload, "priority"),
            )
            if todo is None:
                return _json_error("Todo not found", HTTPStatus.NOT_FOUND)
            return {"todo": _model_dump(todo), "dashboard": build_dashboard()}, HTTPStatus.OK

        if method == "POST" and path == "/api/wellbeing":
            log = upsert_daily_log(
                log_date=_clean_optional_text(payload, "log_date"),
                sleep_hours=payload.get("sleep_hours"),
                mood=_clean_optional_text(payload, "mood"),
                energy=_clean_optional_text(payload, "energy"),
                note=_clean_optional_text(payload, "note"),
            )
            return {
                "log": _model_dump(log),
                "wellbeing": build_wellbeing_state(),
                "dashboard": build_dashboard(),
            }, HTTPStatus.CREATED

        if method == "POST" and path == "/api/wellbeing/query":
            days = int(payload.get("days") or 7)
            return {
                "wellbeing": build_wellbeing_state(
                    days=days,
                    end_date=_clean_optional_text(payload, "end_date"),
                )
            }, HTTPStatus.OK

        if method == "POST" and path == "/api/expenses":
            expense = add_expense(
                amount=float(payload.get("amount", 0)),
                category=str(payload.get("category", "")),
                description=str(payload.get("description", "")),
                spent_date=_clean_optional_text(payload, "spent_date"),
            )
            return {
                "expense": _model_dump(expense),
                "finance": build_finance_state(),
                "dashboard": build_dashboard(),
            }, HTTPStatus.CREATED

        if method == "POST" and path == "/api/finance/query":
            finance = build_finance_state(
                start_date=_clean_optional_text(payload, "start_date"),
                end_date=_clean_optional_text(payload, "end_date"),
                category=_clean_optional_text(payload, "category"),
            )
            return {"finance": finance}, HTTPStatus.OK

        if method == "POST" and path == "/api/budgets":
            category = str(payload.get("category", ""))
            period = str(payload.get("period", "weekly"))
            budget = set_budget(
                category=category,
                amount=float(payload.get("amount", 0)),
                period=period,
            )
            return {
                "budget": _model_dump(budget),
                "budget_status": build_budget_status(budget.category, budget.period),
            }, HTTPStatus.CREATED

        if method == "POST" and path == "/api/budgets/check":
            category = _clean_optional_text(payload, "category")
            if category is None:
                return _json_error("Category cannot be empty", HTTPStatus.BAD_REQUEST)
            period = str(payload.get("period", "weekly"))
            return {
                "budget_status": build_budget_status(category, period),
            }, HTTPStatus.OK

        if method == "POST" and path == "/api/activities/recommend":
            activities = recommend_activities(
                energy=_clean_optional_text(payload, "energy"),
                mood=_clean_optional_text(payload, "mood"),
                available_minutes=payload.get("available_minutes"),
                budget_level=_clean_optional_text(payload, "budget_level"),
                location=_clean_optional_text(payload, "location"),
                goal=_clean_optional_text(payload, "goal"),
                limit=4,
            )
            return {"activities": [_model_dump(item) for item in activities]}, HTTPStatus.OK

        if method == "POST" and path == "/api/agent/chat":
            user_input = _clean_optional_text(payload, "message")
            if user_input is None:
                return _json_error("Message cannot be empty", HTTPStatus.BAD_REQUEST)
            with _agent_lock:
                agent = get_product_agent()
                answer = agent.chat(user_input)
                run_state = _run_state_summary(agent)
            return {
                "answer": answer,
                "run_state": run_state,
                "state": build_initial_state(),
            }, HTTPStatus.OK

        if method == "POST" and path == "/api/agent/reset":
            with _agent_lock:
                _agent = Agent()
            return {"reset": True}, HTTPStatus.OK

        if method == "POST" and path == "/api/memories/query":
            return {
                "memories": build_memory_state(
                    memory_type=_clean_optional_text(payload, "type"),
                    tag=_clean_optional_text(payload, "tag"),
                )
            }, HTTPStatus.OK

        match = MEMORY_ID_PATTERN.fullmatch(path)
        if method == "POST" and match:
            memory = memory_store().delete_memory(match.group(1))
            if memory is None:
                return _json_error("Memory not found", HTTPStatus.NOT_FOUND)
            return {
                "memory": _model_dump(memory),
                "memories": build_memory_state(),
            }, HTTPStatus.OK
    except (TypeError, ValueError, ValidationError) as error:
        return _json_error(str(error), HTTPStatus.BAD_REQUEST)
    except Exception as error:
        return _json_error(str(error), HTTPStatus.INTERNAL_SERVER_ERROR)

    return _json_error("Not found", HTTPStatus.NOT_FOUND)


class ProductUiHandler(BaseHTTPRequestHandler):
    """Serve LifeOps product APIs and the bundled local UI."""

    server_version = "LifeOpsProductUI/1.0"

    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path)
        if path.startswith("/api/"):
            self._send_api("GET", path)
            return
        static_path = "index.html" if path == "/" else path.removeprefix("/")
        self._send_static(static_path)

    def do_POST(self) -> None:
        self._send_api("POST", unquote(urlparse(self.path).path))

    def do_PATCH(self) -> None:
        self._send_api("PATCH", unquote(urlparse(self.path).path))

    def _read_payload(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length == 0:
            return {}
        raw_body = self.rfile.read(content_length).decode("utf-8")
        payload = json.loads(raw_body)
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        return payload

    def _send_api(self, method: str, path: str) -> None:
        try:
            payload = self._read_payload() if method in {"POST", "PATCH"} else {}
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            return
        response, status = handle_api_request(method, path, payload)
        self._send_json(response, status)

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def _send_static(self, relative_path: str) -> None:
        allowed_files = {
            "index.html": "text/html; charset=utf-8",
            "styles.css": "text/css; charset=utf-8",
            "app.js": "text/javascript; charset=utf-8",
        }
        content_type = allowed_files.get(relative_path)
        if content_type is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            content = (STATIC_DIR / relative_path).read_bytes()
        except FileNotFoundError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args: object) -> None:
        return


def serve(host: str = "127.0.0.1", port: int = 8787, open_browser: bool = True) -> None:
    server = ThreadingHTTPServer((host, port), ProductUiHandler)
    url = f"http://{host}:{port}"
    print(f"LifeOps product UI: {url}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.4, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nProduct UI stopped.")
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the LifeOps product UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    serve(host=args.host, port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
