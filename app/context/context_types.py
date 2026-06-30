import math
from dataclasses import dataclass, field
from typing import Any, Literal


ContextUnitKind = Literal[
    "user",
    "assistant",
    "tool",
    "turn",
    "summary",
    "system_note",
]


@dataclass(frozen=True)
class ContextUnit:
    unit_id: str
    kind: ContextUnitKind
    messages: list[Any]
    protected: bool = False
    token_estimate: int = 0
    char_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContextAssembly:
    input_messages: list[Any]
    report: dict[str, Any] = field(default_factory=dict)


def estimate_tokens_from_chars(char_count: int) -> int:
    return math.ceil(char_count / 4)
