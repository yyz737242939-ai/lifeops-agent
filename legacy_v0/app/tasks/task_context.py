"""Request-local Task State context selection and formatting."""

import re
from dataclasses import dataclass
from typing import Any

from app.tasks.task_store import TaskStore
from app.tasks.task_types import TaskBlocker, TaskItem, TaskNote, TaskStep


TASK_CONTEXT_TITLE = "Current task context (read-only)"
TASK_CANDIDATES_TITLE = "Task candidates (read-only)"
ACTIVE_TASK_STATUSES = {"active", "paused", "blocked"}


@dataclass(frozen=True)
class TaskContextResult:
    """Task context selected for one model request."""

    tasks: tuple[TaskItem, ...]
    reason: str | None
    ambiguous: bool = False

    @property
    def injected(self) -> bool:
        return bool(self.tasks)

    def message(self) -> dict[str, str] | None:
        if not self.tasks:
            return None
        if self.ambiguous:
            return {"role": "system", "content": _format_candidates(self.tasks)}
        return {"role": "system", "content": _format_current_task(self.tasks[0])}

    def report(self, message: dict[str, str] | None) -> dict[str, Any]:
        return {
            "task_context_injected": message is not None,
            "task_context_reason": self.reason,
            "task_context_ambiguous": self.ambiguous,
            "task_context_task_ids": [task.id for task in self.tasks],
            "task_context_statuses": [task.status for task in self.tasks],
            "task_context_current_step_ids": [
                task.current_step_id for task in self.tasks
            ],
            "task_context_chars": len(message["content"]) if message else 0,
        }


class TaskContextBuilder:
    """Build read-only Task Context from the persistent TaskStore."""

    def __init__(self, store: TaskStore | None = None) -> None:
        self.store = store or TaskStore()

    def build(self, user_input: str) -> TaskContextResult:
        text = user_input.strip()
        task_id = _extract_task_id(text)
        if task_id is not None:
            task = self.store.get_task(task_id)
            return TaskContextResult(
                tasks=(task,) if task is not None else (),
                reason="task_id" if task is not None else "task_id_not_found",
            )

        active_tasks = self.store.list_tasks(statuses=ACTIVE_TASK_STATUSES)
        if not active_tasks:
            return TaskContextResult(tasks=(), reason="no_active_tasks")

        if _has_current_task_cue(text):
            latest = _latest_updated(active_tasks)
            return TaskContextResult(tasks=(latest,), reason="latest_active_task")

        matches = _keyword_matches(text, active_tasks)
        if len(matches) == 1:
            return TaskContextResult(tasks=(matches[0],), reason="keyword_match")
        if len(matches) > 1:
            return TaskContextResult(
                tasks=tuple(matches),
                reason="multiple_keyword_matches",
                ambiguous=True,
            )

        return TaskContextResult(tasks=(), reason="no_task_context_cue")


def _extract_task_id(text: str) -> str | None:
    match = re.search(r"\btask_[0-9]{8}_[0-9]{6}_[0-9]+\b", text)
    return match.group(0) if match else None


def _has_current_task_cue(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(
            r"继续.{0,12}(?:上次|当前|这个)?任务"
            r"|查看.{0,12}(?:当前|这个|上次)?任务"
            r"|当前任务|上次任务|这个任务.{0,12}下一步"
            r"|continue .{0,16}(?:current|last)? ?task"
            r"|current task|last task",
            lowered,
        )
    )


def _keyword_matches(text: str, tasks: list[TaskItem]) -> list[TaskItem]:
    lowered = text.lower()
    matches: list[TaskItem] = []
    for task in tasks:
        if task.title.lower() in lowered or task.goal.lower() in lowered:
            matches.append(task)
            continue
        if any(tag and tag.lower() in lowered for tag in task.tags):
            matches.append(task)
    return matches


def _latest_updated(tasks: list[TaskItem]) -> TaskItem:
    return max(tasks, key=lambda task: (task.updated_at, task.id))


def _format_current_task(task: TaskItem) -> str:
    lines = [
        f"{TASK_CONTEXT_TITLE}:",
        f"- id: {task.id}",
        f"- title: {task.title}",
        f"- goal: {task.goal}",
        f"- status: {task.status}",
    ]

    current_step = task.current_step
    lines.append(f"- current step: {_format_step(current_step)}")
    open_blockers = task.open_blockers
    lines.append(f"- open blockers: {_format_blockers(open_blockers)}")
    notes = task.progress_notes[-3:]
    lines.append(f"- recent notes: {_format_notes(notes)}")
    if task.tags:
        lines.append(f"- tags: {', '.join(task.tags)}")
    lines.extend(
        [
            "",
            "Rules:",
            "- This context is read-only and request-local.",
            "- Do not claim the task was updated unless a Task WRITE tool succeeds.",
            "- Resuming a task does not authorize risky actions or writes by itself.",
        ]
    )
    return "\n".join(lines)


def _format_candidates(tasks: tuple[TaskItem, ...]) -> str:
    lines = [
        f"{TASK_CANDIDATES_TITLE}:",
        "Multiple tasks match the user's request. Ask the user to choose one by id before acting.",
    ]
    for task in tasks[:5]:
        current_step = task.current_step
        current_step_title = current_step.title if current_step is not None else "none"
        lines.append(
            f"- id: {task.id}; title: {task.title}; status: {task.status}; "
            f"current step: {current_step_title}"
        )
    return "\n".join(lines)


def _format_step(step: TaskStep | None) -> str:
    if step is None:
        return "none"
    summary = f"; summary: {step.summary}" if step.summary else ""
    return f"[{step.id}] {step.title} ({step.status}){summary}"


def _format_blockers(blockers: list[TaskBlocker]) -> str:
    if not blockers:
        return "none"
    return "; ".join(
        f"[{blocker.id}] {blocker.reason}"
        + (f" (step={blocker.related_step_id})" if blocker.related_step_id else "")
        for blocker in blockers[:3]
    )


def _format_notes(notes: list[TaskNote]) -> str:
    if not notes:
        return "none"
    return "; ".join(f"[{note.id}] {note.content}" for note in notes)
