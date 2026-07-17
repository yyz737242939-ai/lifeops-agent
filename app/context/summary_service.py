"""Incremental rolling-summary lifecycle owned by the Context module."""

from __future__ import annotations

from collections.abc import Callable

from app.common.ids import new_id
from app.common.time import utc_now_iso
from app.context.budget import estimate_tokens
from app.context.errors import ContextContractError, ContextErrorCode
from app.context.models import (
    ContextBudget,
    ContextSummaryOutput,
    ConversationSummary,
    ConversationTurn,
)
from app.context.ports import ContextSummarizer, ConversationRepository
from app.observability.logger import LlmInteractionSink


class RollingSummaryService:
    """Append one valid summary from the latest summary plus new contiguous turns."""

    def __init__(
        self,
        repository: ConversationRepository,
        summarizer: ContextSummarizer,
        *,
        id_factory: Callable[[str], str] = new_id,
        clock: Callable[[], str] = utc_now_iso,
    ) -> None:
        self._repository = repository
        self._summarizer = summarizer
        self._id_factory = id_factory
        self._clock = clock

    def summarize(
        self,
        session_id: str,
        contiguous_turns: tuple[ConversationTurn, ...],
        budget: ContextBudget,
        *,
        llm_log: LlmInteractionSink | None = None,
    ) -> ConversationSummary:
        if not isinstance(session_id, str) or not session_id.strip():
            raise _invalid_summary()
        if not isinstance(budget, ContextBudget):
            raise _invalid_summary()
        previous = self._repository.load_latest_valid_summary(session_id)
        _validate_contiguous_input(session_id, previous, contiguous_turns)
        output = self._summarizer.summarize(
            previous,
            contiguous_turns,
            budget,
            llm_log=llm_log,
        )
        if not isinstance(output, ContextSummaryOutput):
            raise _invalid_summary()
        estimated_tokens = estimate_tokens(output.content)
        if estimated_tokens > budget.max_summary_tokens:
            raise ContextContractError(
                "Context summary exceeds its deterministic budget.",
                code=ContextErrorCode.SUMMARY_TOO_LARGE,
            )
        first = contiguous_turns[0]
        last = contiguous_turns[-1]
        summary = ConversationSummary(
            schema_version=1,
            session_id=session_id,
            summary_id=self._id_factory("summary"),
            version=1 if previous is None else previous.version + 1,
            covered_start_sequence=(
                first.sequence
                if previous is None
                else previous.covered_start_sequence
            ),
            covered_end_sequence=last.sequence,
            content=output.content,
            estimated_tokens=estimated_tokens,
            previous_summary_id=(
                None if previous is None else previous.summary_id
            ),
            source_turn_ids=tuple(turn.turn_id for turn in contiguous_turns),
            provider=output.provider,
            model=output.model,
            created_at=self._clock(),
        )
        self._repository.append_summary(summary)
        return summary


def _validate_contiguous_input(
    session_id: str,
    previous: ConversationSummary | None,
    turns: tuple[ConversationTurn, ...],
) -> None:
    if not isinstance(turns, tuple) or not turns or any(
        not isinstance(turn, ConversationTurn) for turn in turns
    ):
        raise _invalid_summary()
    if any(turn.session_id != session_id for turn in turns):
        raise _invalid_summary()
    expected_start = previous.covered_end_sequence + 1 if previous else 1
    expected = tuple(range(expected_start, expected_start + len(turns)))
    if tuple(turn.sequence for turn in turns) != expected:
        raise _invalid_summary()
    if len({turn.turn_id for turn in turns}) != len(turns):
        raise _invalid_summary()


def _invalid_summary() -> ContextContractError:
    return ContextContractError(
        "Rolling summary input or output is invalid.",
        code=ContextErrorCode.SUMMARY_INVALID,
    )
