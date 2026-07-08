"""Shared Task State v1 data models."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.utils.time import now_iso, timestamp_id


TaskStatus = Literal["active", "paused", "blocked", "completed", "cancelled"]
TaskStepStatus = Literal["pending", "in_progress", "done", "skipped", "blocked"]
TaskBlockerStatus = Literal["open", "resolved"]
TaskSource = Literal["user_authorized"]


def next_task_id() -> str:
    return f"task_{timestamp_id()}"


def next_task_step_id() -> str:
    return f"step_{timestamp_id()}"


def next_task_blocker_id() -> str:
    return f"blocker_{timestamp_id()}"


def next_task_note_id() -> str:
    return f"note_{timestamp_id()}"


class TaskStep(BaseModel):
    """One executable or checkable step inside a long-lived task."""

    id: str = Field(default_factory=next_task_step_id)
    title: str
    status: TaskStepStatus = "pending"
    summary: str = ""
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    completed_at: str | None = None

    @field_validator("id", "title")
    @classmethod
    def required_text_must_not_be_empty(cls, value: str) -> str:
        clean_value = value.strip()
        if not clean_value:
            raise ValueError("Task step id and title cannot be empty")
        return clean_value

    @field_validator("summary")
    @classmethod
    def optional_text_must_be_stripped(cls, value: str) -> str:
        return value.strip()

    def start(self) -> None:
        self._ensure_not_terminal()
        self.status = "in_progress"
        self.updated_at = now_iso()

    def complete(self) -> None:
        self._ensure_not_terminal()
        finished_at = now_iso()
        self.status = "done"
        self.completed_at = finished_at
        self.updated_at = finished_at

    def skip(self) -> None:
        self._ensure_not_terminal()
        finished_at = now_iso()
        self.status = "skipped"
        self.completed_at = finished_at
        self.updated_at = finished_at

    def block(self) -> None:
        self._ensure_not_terminal()
        self.status = "blocked"
        self.updated_at = now_iso()

    def _ensure_not_terminal(self) -> None:
        if self.status in ("done", "skipped"):
            raise RuntimeError("Task step is already terminal")


class TaskBlocker(BaseModel):
    """A reason a task or step cannot currently move forward."""

    id: str = Field(default_factory=next_task_blocker_id)
    reason: str
    status: TaskBlockerStatus = "open"
    created_at: str = Field(default_factory=now_iso)
    resolved_at: str | None = None
    related_step_id: str | None = None

    @field_validator("id", "reason")
    @classmethod
    def required_text_must_not_be_empty(cls, value: str) -> str:
        clean_value = value.strip()
        if not clean_value:
            raise ValueError("Task blocker id and reason cannot be empty")
        return clean_value

    @field_validator("related_step_id")
    @classmethod
    def optional_text_must_be_stripped(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean_value = value.strip()
        return clean_value or None

    @property
    def is_open(self) -> bool:
        return self.status == "open"

    def resolve(self) -> None:
        if self.status == "resolved":
            raise RuntimeError("Task blocker is already resolved")
        self.status = "resolved"
        self.resolved_at = now_iso()


class TaskNote(BaseModel):
    """A concise progress note, not a full chat transcript."""

    id: str = Field(default_factory=next_task_note_id)
    content: str
    created_at: str = Field(default_factory=now_iso)
    related_step_id: str | None = None

    @field_validator("id", "content")
    @classmethod
    def required_text_must_not_be_empty(cls, value: str) -> str:
        clean_value = value.strip()
        if not clean_value:
            raise ValueError("Task note id and content cannot be empty")
        return clean_value

    @field_validator("related_step_id")
    @classmethod
    def optional_text_must_be_stripped(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean_value = value.strip()
        return clean_value or None


class TaskItem(BaseModel):
    """Long-lived user-authorized task state across chats."""

    id: str = Field(default_factory=next_task_id)
    title: str
    goal: str
    status: TaskStatus = "active"
    steps: list[TaskStep] = Field(default_factory=list)
    current_step_id: str | None = None
    progress_notes: list[TaskNote] = Field(default_factory=list)
    blockers: list[TaskBlocker] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    completed_at: str | None = None
    source: TaskSource = "user_authorized"
    tags: list[str] = Field(default_factory=list)

    @field_validator("id", "title", "goal")
    @classmethod
    def required_text_must_not_be_empty(cls, value: str) -> str:
        clean_value = value.strip()
        if not clean_value:
            raise ValueError("Task id, title and goal cannot be empty")
        return clean_value

    @field_validator("current_step_id")
    @classmethod
    def optional_text_must_be_stripped(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean_value = value.strip()
        return clean_value or None

    @field_validator("tags")
    @classmethod
    def tags_must_be_normalized(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for tag in value:
            clean_tag = tag.strip().lower()
            if not clean_tag or clean_tag in seen:
                continue
            normalized.append(clean_tag)
            seen.add(clean_tag)
        return normalized

    @model_validator(mode="after")
    def current_step_must_exist(self) -> "TaskItem":
        if self.current_step_id is None:
            return self
        if self._find_step(self.current_step_id) is None:
            raise ValueError("current_step_id must reference an existing step")
        return self

    @property
    def open_blockers(self) -> list[TaskBlocker]:
        return [blocker for blocker in self.blockers if blocker.is_open]

    @property
    def current_step(self) -> TaskStep | None:
        if self.current_step_id is None:
            return None
        return self._find_step(self.current_step_id)

    def add_step(self, title: str, *, summary: str = "") -> TaskStep:
        self._ensure_task_can_change()
        step = TaskStep(title=title, summary=summary)
        self.steps.append(step)
        if self.current_step_id is None:
            self.current_step_id = step.id
        self._touch()
        return step

    def set_current_step(self, step_id: str) -> TaskStep:
        self._ensure_task_can_change()
        step = self._require_step(step_id)
        self.current_step_id = step.id
        self._touch()
        return step

    def complete_step(self, step_id: str) -> TaskStep:
        self._ensure_task_can_change()
        step = self._require_step(step_id)
        step.complete()
        if self.current_step_id == step.id:
            self.current_step_id = None
        self._touch()
        return step

    def update_step(
        self,
        step_id: str,
        *,
        title: str | None = None,
        summary: str | None = None,
        status: TaskStepStatus | None = None,
    ) -> TaskStep:
        self._ensure_task_can_change()
        step = self._require_step(step_id)
        if title is not None:
            clean_title = title.strip()
            if not clean_title:
                raise ValueError("Task step title cannot be empty")
            step.title = clean_title
        if summary is not None:
            step.summary = summary.strip()
        if status is not None:
            self._apply_step_status(step, status)
        step.updated_at = now_iso()
        self._touch()
        return step

    def skip_step(self, step_id: str) -> TaskStep:
        self._ensure_task_can_change()
        step = self._require_step(step_id)
        step.skip()
        if self.current_step_id == step.id:
            self.current_step_id = None
        self._touch()
        return step

    def add_note(
        self,
        content: str,
        *,
        related_step_id: str | None = None,
    ) -> TaskNote:
        self._ensure_task_can_change()
        if related_step_id is not None:
            self._require_step(related_step_id)
        note = TaskNote(content=content, related_step_id=related_step_id)
        self.progress_notes.append(note)
        self._touch()
        return note

    def add_blocker(
        self,
        reason: str,
        *,
        related_step_id: str | None = None,
    ) -> TaskBlocker:
        self._ensure_task_can_change()
        related_step = None
        if related_step_id is not None:
            related_step = self._require_step(related_step_id)
        blocker = TaskBlocker(reason=reason, related_step_id=related_step_id)
        self.blockers.append(blocker)
        if related_step is not None:
            related_step.block()
        self.status = "blocked"
        self._touch()
        return blocker

    def resolve_blocker(self, blocker_id: str) -> TaskBlocker:
        self._ensure_task_can_change()
        blocker = self._require_blocker(blocker_id)
        blocker.resolve()
        if self.status == "blocked" and not self.open_blockers:
            self.status = "active"
        self._touch()
        return blocker

    def pause(self) -> None:
        self._ensure_task_can_change()
        self.status = "paused"
        self._touch()

    def resume(self) -> None:
        self._ensure_task_can_change()
        self.status = "blocked" if self.open_blockers else "active"
        self._touch()

    def mark_blocked(self) -> None:
        self._ensure_task_can_change()
        self.status = "blocked"
        self._touch()

    def complete_task(self) -> None:
        self._ensure_task_can_change()
        finished_at = now_iso()
        self.status = "completed"
        self.completed_at = finished_at
        self.updated_at = finished_at

    def cancel(self) -> None:
        self._ensure_task_can_change()
        finished_at = now_iso()
        self.status = "cancelled"
        self.completed_at = finished_at
        self.updated_at = finished_at

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")

    def _touch(self) -> None:
        self.updated_at = now_iso()

    def _ensure_task_can_change(self) -> None:
        if self.status in ("completed", "cancelled"):
            raise RuntimeError("Task is already terminal")

    def _find_step(self, step_id: str) -> TaskStep | None:
        return next((step for step in self.steps if step.id == step_id), None)

    def _require_step(self, step_id: str) -> TaskStep:
        step = self._find_step(step_id)
        if step is None:
            raise ValueError("Unknown task step")
        return step

    def _require_blocker(self, blocker_id: str) -> TaskBlocker:
        for blocker in self.blockers:
            if blocker.id == blocker_id:
                return blocker
        raise ValueError("Unknown task blocker")

    @staticmethod
    def _apply_step_status(step: TaskStep, status: TaskStepStatus) -> None:
        if status == "pending":
            step._ensure_not_terminal()
            step.status = "pending"
            step.completed_at = None
        elif status == "in_progress":
            step.start()
        elif status == "done":
            step.complete()
        elif status == "skipped":
            step.skip()
        elif status == "blocked":
            step.block()
