from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.utils.json_file import load_model_list, save_model_list
from app.utils.time import now_iso


TODO_STATUS = "todo"
DONE_STATUS = "done"
TodoStatus = Literal["todo", "done"]
TodoPriority = Literal["low", "medium", "high"]

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
TODOS_FILE = DATA_DIR / "todos.json"


class Todo(BaseModel):
    id: int
    title: str
    status: TodoStatus = TODO_STATUS
    priority: TodoPriority = "medium"
    due_date: str | None = None
    created_at: str = Field(default_factory=now_iso)
    completed_at: str | None = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_empty(cls, value: str) -> str:
        clean_value = value.strip()
        if not clean_value:
            raise ValueError("Todo title cannot be empty")
        return clean_value

    @field_validator("due_date")
    @classmethod
    def due_date_must_be_iso_date(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        try:
            date.fromisoformat(value)
        except ValueError as e:
            raise ValueError("due_date must use YYYY-MM-DD format") from e
        return value


def _load_todos() -> list[Todo]:
    return load_model_list(TODOS_FILE, Todo)


def _save_todos(todos: list[Todo]) -> None:
    save_model_list(TODOS_FILE, todos)


def add_todo(
    title: str,
    due_date: str | None = None,
    priority: TodoPriority = "medium",
) -> Todo:
    todos = _load_todos()
    next_id = max((todo.id for todo in todos), default=0) + 1
    todo = Todo(
        id=next_id,
        title=title,
        status=TODO_STATUS,
        priority=priority,
        due_date=due_date,
    )

    todos.append(todo)
    _save_todos(todos)
    return todo


def list_todos() -> list[Todo]:
    return _load_todos()


def complete_todo(todo_id: int) -> Todo | None:
    todos = _load_todos()

    for todo in todos:
        if todo.id == todo_id:
            todo.status = DONE_STATUS
            todo.completed_at = now_iso()
            _save_todos(todos)
            return todo

    return None


def update_todo(
    todo_id: int,
    title: str | None = None,
    due_date: str | None = None,
    priority: TodoPriority | None = None,
) -> Todo | None:
    todos = _load_todos()

    for index, todo in enumerate(todos):
        if todo.id != todo_id:
            continue

        update_data = todo.model_dump()
        if title is not None:
            update_data["title"] = title
        if due_date is not None:
            update_data["due_date"] = due_date
        if priority is not None:
            update_data["priority"] = priority

        updated_todo = Todo.model_validate(update_data)
        todos[index] = updated_todo
        _save_todos(todos)
        return updated_todo

    return None


def delete_todo(todo_id: int) -> Todo | None:
    todos = _load_todos()

    for index, todo in enumerate(todos):
        if todo.id == todo_id:
            deleted_todo = todos.pop(index)
            _save_todos(todos)
            return deleted_todo

    return None
