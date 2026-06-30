from typing import Any

from app.runtime.context_compactor import summary_to_message


class ContextStore:
    """In-memory source-of-truth holder for the full conversation history."""

    def __init__(self) -> None:
        self.full_messages: list[Any] = []
        self.summary: dict[str, Any] | None = None
        self.summary_message: dict[str, Any] | None = None

    def replace_full_messages(self, messages: list[Any]) -> None:
        self.full_messages = list(messages)

    def replace_summary(self, summary: dict[str, Any] | None) -> None:
        self.summary = summary
        self.summary_message = summary_to_message(summary) if summary else None
