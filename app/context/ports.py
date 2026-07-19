"""Narrow ports owned by the framework-independent Context core."""

from __future__ import annotations

from typing import Protocol

from app.context.models import (
    ContextBudget,
    ContextContribution,
    ContextQuery,
    ContextSummaryOutput,
    ConversationSummary,
    ConversationTurn,
)
from app.observability.logger import LlmInteractionSink


class ConversationRepository(Protocol):
    def append_turn(self, turn: ConversationTurn) -> None:
        ...

    def load_turns(
        self,
        session_id: str,
        before_or_at_sequence: int | None,
        limit: int | None,
    ) -> tuple[ConversationTurn, ...]:
        ...

    def append_summary(self, summary: ConversationSummary) -> None:
        ...

    def load_latest_valid_summary(
        self, session_id: str
    ) -> ConversationSummary | None:
        ...


class ContextSummarizer(Protocol):
    def summarize(
        self,
        previous_summary: ConversationSummary | None,
        contiguous_turns: tuple[ConversationTurn, ...],
        budget: ContextBudget,
        *,
        llm_log: LlmInteractionSink | None = None,
    ) -> ContextSummaryOutput:
        ...


class ProfileProvider(Protocol):
    def load_profile(self) -> ContextContribution | None:
        ...


class MemoryRetriever(Protocol):
    def search(
        self,
        query: ContextQuery,
        max_items: int,
        max_tokens: int,
    ) -> tuple[ContextContribution, ...]:
        ...
