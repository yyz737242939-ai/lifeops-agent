"""Persistent Task State store."""

from pathlib import Path
from typing import Any, get_args

from app.tasks.task_types import (
    TaskItem,
    TaskStepStatus,
    TaskStatus,
)
from app.utils.json_file import read_json_file, write_json_file


DATA_DIR = Path(__file__).resolve().parents[2] / "data"
TASKS_DIR = DATA_DIR / "tasks"
TASKS_FILE = TASKS_DIR / "tasks.json"
TASK_STORE_VERSION = 1
TASK_STATUSES = set(get_args(TaskStatus))
TASK_STEP_STATUSES = set(get_args(TaskStepStatus))


class TaskStore:
    """JSON-backed store for user-authorized long-lived tasks."""

    def __init__(self, path: str | Path = TASKS_FILE) -> None:
        self.path = Path(path)

    def create_task(
        self,
        *,
        title: str,
        goal: str,
        steps: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> TaskItem:
        tasks = self._load()
        task = TaskItem(title=title, goal=goal, tags=tags or [])
        for step_title in steps or []:
            task.add_step(step_title)
        tasks.append(task)
        self._save(tasks)
        return task

    def list_tasks(
        self,
        *,
        statuses: set[TaskStatus] | None = None,
        tag: str | None = None,
    ) -> list[TaskItem]:
        tasks = self._load()
        allowed_statuses = statuses or {"active", "paused", "blocked"}
        normalized_tag = tag.strip().lower() if tag else None

        result: list[TaskItem] = []
        for task in tasks:
            if task.status not in allowed_statuses:
                continue
            if normalized_tag is not None and normalized_tag not in task.tags:
                continue
            result.append(task)
        return result

    def get_task(self, task_id: str) -> TaskItem | None:
        return self._find_task(self._load(), task_id)

    def update_task_status(self, task_id: str, status: TaskStatus) -> TaskItem | None:
        if status not in TASK_STATUSES:
            raise ValueError("Unknown task status")
        tasks = self._load()
        task = self._find_task(tasks, task_id)
        if task is None:
            return None

        if status == "active":
            task.resume()
        elif status == "paused":
            task.pause()
        elif status == "blocked":
            task.mark_blocked()
        elif status == "completed":
            task.complete_task()
        elif status == "cancelled":
            task.cancel()
        self._save(tasks)
        return task

    def add_step(
        self,
        task_id: str,
        title: str,
        *,
        summary: str = "",
    ) -> TaskItem | None:
        return self._mutate_task(
            task_id,
            lambda task: task.add_step(title, summary=summary),
        )

    def set_current_step(self, task_id: str, step_id: str) -> TaskItem | None:
        return self._mutate_task(task_id, lambda task: task.set_current_step(step_id))

    def update_step(
        self,
        task_id: str,
        step_id: str,
        *,
        title: str | None = None,
        summary: str | None = None,
        status: TaskStepStatus | None = None,
    ) -> TaskItem | None:
        if status is not None and status not in TASK_STEP_STATUSES:
            raise ValueError("Unknown task step status")
        return self._mutate_task(
            task_id,
            lambda task: task.update_step(
                step_id,
                title=title,
                summary=summary,
                status=status,
            ),
        )

    def complete_step(self, task_id: str, step_id: str) -> TaskItem | None:
        return self._mutate_task(task_id, lambda task: task.complete_step(step_id))

    def skip_step(self, task_id: str, step_id: str) -> TaskItem | None:
        return self._mutate_task(task_id, lambda task: task.skip_step(step_id))

    def add_note(
        self,
        task_id: str,
        content: str,
        *,
        related_step_id: str | None = None,
    ) -> TaskItem | None:
        return self._mutate_task(
            task_id,
            lambda task: task.add_note(
                content,
                related_step_id=related_step_id,
            ),
        )

    def add_blocker(
        self,
        task_id: str,
        reason: str,
        *,
        related_step_id: str | None = None,
    ) -> TaskItem | None:
        return self._mutate_task(
            task_id,
            lambda task: task.add_blocker(
                reason,
                related_step_id=related_step_id,
            ),
        )

    def resolve_blocker(self, task_id: str, blocker_id: str) -> TaskItem | None:
        return self._mutate_task(
            task_id,
            lambda task: task.resolve_blocker(blocker_id),
        )

    def _mutate_task(self, task_id: str, mutator) -> TaskItem | None:
        tasks = self._load()
        task = self._find_task(tasks, task_id)
        if task is None:
            return None
        mutator(task)
        self._save(tasks)
        return task

    def _load(self) -> list[TaskItem]:
        if not self.path.exists():
            return []

        payload = read_json_file(self.path, dict)
        version = payload.get("version")
        if version != TASK_STORE_VERSION:
            raise ValueError(f"Unsupported task store version: {version}")

        raw_tasks = payload.get("tasks")
        if not isinstance(raw_tasks, list):
            raise ValueError(f"{self.path} must contain a JSON tasks list")
        return [TaskItem.model_validate(item) for item in raw_tasks]

    def _save(self, tasks: list[TaskItem]) -> None:
        payload: dict[str, Any] = {
            "version": TASK_STORE_VERSION,
            "tasks": [task.to_dict() for task in tasks],
        }
        write_json_file(self.path, payload)

    @staticmethod
    def _find_task(tasks: list[TaskItem], task_id: str) -> TaskItem | None:
        return next((task for task in tasks if task.id == task_id), None)
