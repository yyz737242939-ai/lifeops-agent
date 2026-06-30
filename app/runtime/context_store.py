from typing import Any


class ContextStore:
    """In-memory source-of-truth holder for the full conversation history."""

    def __init__(self) -> None:
        self.full_messages: list[Any] = []
        self.summary_message: dict[str, Any] | None = None

    def replace_full_messages(self, messages: list[Any]) -> None:
        self.full_messages = list(messages)
