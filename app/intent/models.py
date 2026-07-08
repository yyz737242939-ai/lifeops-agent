"""Intent decision models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class IntentType(StrEnum):
    """Supported high-level user intent types for the runtime."""

    CHAT = "chat"
    READ = "read"
    WRITE_REQUEST = "write_request"
    PLAN_REQUEST = "plan_request"
    CLARIFICATION_NEEDED = "clarification_needed"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class ClassifierResult:
    """Decision signal returned by one intent classifier."""

    classifier_name: str
    status: str
    intent_type: IntentType
    confidence: float
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.classifier_name.strip():
            raise ValueError("classifier_name must be non-empty.")
        if not self.status.strip():
            raise ValueError("status must be non-empty.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0.")
        if self.reason is not None and not self.reason.strip():
            raise ValueError("reason must be non-empty when provided.")


@dataclass(frozen=True)
class IntentDecision:
    """Final request-local intent decision for one runtime request."""

    intent_type: IntentType
    confidence: float
    needs_clarification: bool = False
    write_candidate: bool = False
    reason: str | None = None
    classifier_results: list[ClassifierResult] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0.")
        if self.reason is not None and not self.reason.strip():
            raise ValueError("reason must be non-empty when provided.")
        if not isinstance(self.classifier_results, list):
            raise ValueError("classifier_results must be a list.")
        for result in self.classifier_results:
            if not isinstance(result, ClassifierResult):
                raise ValueError("classifier_results must contain ClassifierResult values.")
