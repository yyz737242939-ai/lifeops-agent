"""Intent classification service."""

from __future__ import annotations

from collections.abc import Sequence

from app.intent.classifiers import (
    IntentClassifier,
    LlmIntentClassifier,
    RuleBasedIntentClassifier,
)
from app.intent.models import ClassifierResult, IntentDecision, IntentType
from app.runtime.models import RuntimeRequest


class IntentService:
    """Coordinates intent classifiers and produces one final decision."""

    def __init__(self, classifiers: Sequence[IntentClassifier] | None = None) -> None:
        self._classifiers: tuple[IntentClassifier, ...] = tuple(
            classifiers
            if classifiers is not None
            else (RuleBasedIntentClassifier(), LlmIntentClassifier())
        )
        if not self._classifiers:
            raise ValueError("classifiers must be non-empty.")

    def classify(self, request: RuntimeRequest) -> IntentDecision:
        """Classify one runtime request with all configured classifiers."""

        results = [classifier.classify(request) for classifier in self._classifiers]
        primary = _select_primary_result(results)
        return IntentDecision(
            intent_type=primary.intent_type,
            confidence=primary.confidence,
            needs_clarification=primary.intent_type == IntentType.CLARIFICATION_NEEDED,
            write_candidate=primary.intent_type == IntentType.WRITE_REQUEST,
            reason=primary.reason,
            classifier_results=results,
        )


def _select_primary_result(results: list[ClassifierResult]) -> ClassifierResult:
    for result in results:
        if result.status == "matched":
            return result
    for result in results:
        if result.status == "low_confidence":
            return ClassifierResult(
                classifier_name="intent_service",
                status="synthesized",
                intent_type=IntentType.CLARIFICATION_NEEDED,
                confidence=result.confidence,
                reason=result.reason,
            )
    return ClassifierResult(
        classifier_name="intent_service",
        status="synthesized",
        intent_type=IntentType.CLARIFICATION_NEEDED,
        confidence=0.0,
        reason="No classifier produced a usable intent signal.",
    )
