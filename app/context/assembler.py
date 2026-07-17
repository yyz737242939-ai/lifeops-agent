"""Deterministic bounded Context assembly for one Runtime request."""

from __future__ import annotations

from collections.abc import Callable

from app.common.ids import new_id
from app.common.time import utc_now_iso
from app.context.adapters import EmptyMemoryRetriever, EmptyProfileProvider
from app.context.budget import estimate_tokens
from app.context.errors import (
    ContextContractError,
    ContextError,
    ContextErrorCode,
    ConversationRepositoryError,
)
from app.context.models import (
    ContextAssembly,
    ContextBudget,
    ContextContribution,
    ContextContributionKind,
    ContextDegradation,
    ContextDegradationComponent,
    ContextKindCount,
    ContextKindTokenCount,
    ContextProvenance,
    ContextQuery,
    ContextReport,
    ConversationSummary,
    ConversationTurn,
)
from app.context.ports import ConversationRepository, MemoryRetriever, ProfileProvider
from app.context.summary_service import RollingSummaryService
from app.observability.logger import LlmInteractionSink


class ContextAssembler:
    """Build one immutable assembly without Domain retrieval or authorization."""

    def __init__(
        self,
        repository: ConversationRepository,
        summary_service: RollingSummaryService,
        *,
        profile_provider: ProfileProvider | None = None,
        memory_retriever: MemoryRetriever | None = None,
        id_factory: Callable[[str], str] = new_id,
        clock: Callable[[], str] = utc_now_iso,
    ) -> None:
        self._repository = repository
        self._summary_service = summary_service
        self._profile_provider = profile_provider or EmptyProfileProvider()
        self._memory_retriever = memory_retriever or EmptyMemoryRetriever()
        self._id_factory = id_factory
        self._clock = clock

    def assemble(
        self,
        query: ContextQuery,
        budget: ContextBudget,
        *,
        llm_log: LlmInteractionSink | None = None,
    ) -> ContextAssembly:
        if not isinstance(query, ContextQuery) or not isinstance(budget, ContextBudget):
            raise _assembly_error()
        assembly_id = self._id_factory("assembly")
        degradations: list[ContextDegradation] = []
        try:
            turns = self._repository.load_turns(query.session_id, None, None)
        except ConversationRepositoryError as exc:
            if exc.code == ContextErrorCode.PATH_INVALID.value:
                raise
            turns = ()
            degradations.append(
                ContextDegradation(
                    ContextDegradationComponent.CONVERSATION_HISTORY,
                    _known_code(exc.code, ContextErrorCode.HISTORY_READ_FAILED),
                )
            )

        current_turn = _find_current_turn(turns, query)
        if current_turn is None:
            if turns:
                raise _assembly_error()
            current_content = query.text
            history: tuple[ConversationTurn, ...] = ()
        else:
            current_content = current_turn.content
            history = tuple(
                turn
                for turn in turns
                if turn.sequence < current_turn.sequence
                and turn.turn_id != query.turn_id
            )
        current_tokens = estimate_tokens(current_content)
        if current_tokens > budget.max_current_input_tokens:
            raise ContextContractError(
                "Current input exceeds the frozen Context limit.",
                code=ContextErrorCode.INPUT_TOO_LARGE,
            )

        summary = self._load_summary(query.session_id, degradations)
        summary_end = summary.covered_end_sequence if summary else 0
        unsummarized = tuple(
            turn for turn in history if turn.sequence > summary_end
        )
        recent_cap = budget.max_recent_turns
        older = unsummarized[:-recent_cap] if recent_cap else unsummarized
        if older:
            try:
                summary = self._summary_service.summarize(
                    query.session_id,
                    older,
                    budget,
                    llm_log=llm_log,
                )
            except ContextError as exc:
                degradations.append(
                    ContextDegradation(
                        ContextDegradationComponent.CONVERSATION_SUMMARY,
                        _known_code(exc.code, ContextErrorCode.SUMMARY_PROVIDER_FAILED),
                    )
                )
            summary_end = summary.covered_end_sequence if summary else 0
        recent_candidates = tuple(
            turn for turn in history if turn.sequence > summary_end
        )[-recent_cap:] if recent_cap else ()

        current_contribution = _turn_contribution(
            current_turn,
            content=current_content,
            kind=ContextContributionKind.CURRENT_INPUT,
            query=query,
        )
        remaining = budget.max_total_tokens - current_tokens
        if remaining < 0:
            raise ContextContractError(
                "Current input exceeds the total Context limit.",
                code=ContextErrorCode.INPUT_TOO_LARGE,
            )
        selected_recent_reversed: list[ContextContribution] = []
        for turn in reversed(recent_candidates):
            contribution = _turn_contribution(
                turn,
                content=turn.content,
                kind=ContextContributionKind.CONVERSATION_TURN,
                query=query,
            )
            if contribution.estimated_tokens > remaining:
                break
            selected_recent_reversed.append(contribution)
            remaining -= contribution.estimated_tokens
        selected_recent = tuple(reversed(selected_recent_reversed))

        summary_contribution: ContextContribution | None = None
        if summary is not None:
            candidate = _summary_contribution(summary)
            if candidate.estimated_tokens <= remaining:
                summary_contribution = candidate
                remaining -= candidate.estimated_tokens

        profile = self._load_profile(degradations)
        selected_profile: ContextContribution | None = None
        if (
            profile is not None
            and profile.kind == ContextContributionKind.PROFILE
            and profile.estimated_tokens <= budget.max_profile_tokens
            and profile.estimated_tokens <= remaining
        ):
            selected_profile = profile
            remaining -= profile.estimated_tokens

        memories = self._load_memories(query, budget, degradations)
        selected_memories: list[ContextContribution] = []
        seen_memory_refs: set[str] = set()
        memory_tokens = 0
        for memory in memories:
            if memory.provenance.reference in seen_memory_refs:
                continue
            if len(selected_memories) >= budget.max_memory_items:
                break
            next_memory_tokens = memory_tokens + memory.estimated_tokens
            if (
                next_memory_tokens > budget.max_memory_tokens
                or memory.estimated_tokens > remaining
            ):
                continue
            selected_memories.append(memory)
            seen_memory_refs.add(memory.provenance.reference)
            memory_tokens = next_memory_tokens
            remaining -= memory.estimated_tokens

        contributions = (
            *((selected_profile,) if selected_profile else ()),
            *selected_memories,
            *((summary_contribution,) if summary_contribution else ()),
            *selected_recent,
            current_contribution,
        )
        total = sum(item.estimated_tokens for item in contributions)
        per_kind = tuple(
            ContextKindTokenCount(
                kind,
                sum(
                    item.estimated_tokens
                    for item in contributions
                    if item.kind == kind
                ),
            )
            for kind in ContextContributionKind
        )
        trimmed = tuple(
            ContextKindCount(kind, count)
            for kind, count in (
                (
                    ContextContributionKind.CONVERSATION_TURN,
                    len(history) - len(selected_recent),
                ),
                (
                    ContextContributionKind.CONVERSATION_SUMMARY,
                    int(summary is not None and summary_contribution is None),
                ),
                (
                    ContextContributionKind.PROFILE,
                    int(profile is not None and selected_profile is None),
                ),
                (
                    ContextContributionKind.MEMORY,
                    len(memories) - len(selected_memories),
                ),
                (ContextContributionKind.CURRENT_INPUT, 0),
            )
        )
        report = ContextReport(
            assembly_id=assembly_id,
            selected_turn_count=len(selected_recent),
            summary_version=(summary.version if summary_contribution else None),
            summary_covered_range=(
                (
                    summary.covered_start_sequence,
                    summary.covered_end_sequence,
                )
                if summary_contribution
                else None
            ),
            profile_included=selected_profile is not None,
            memory_candidate_count=len(memories),
            memory_selected_count=len(selected_memories),
            per_kind_estimated_tokens=per_kind,
            trimmed_counts=trimmed,
            degradations=tuple(degradations),
            created_at=self._clock(),
        )
        return ContextAssembly(
            assembly_id=assembly_id,
            session_id=query.session_id,
            run_id=query.run_id,
            turn_id=query.turn_id,
            query=query,
            contributions=contributions,
            estimated_total_tokens=total,
            report=report,
        )

    def _load_summary(
        self,
        session_id: str,
        degradations: list[ContextDegradation],
    ) -> ConversationSummary | None:
        try:
            return self._repository.load_latest_valid_summary(session_id)
        except ConversationRepositoryError as exc:
            degradations.append(
                ContextDegradation(
                    ContextDegradationComponent.CONVERSATION_SUMMARY,
                    _known_code(exc.code, ContextErrorCode.SUMMARY_INVALID),
                )
            )
            return None

    def _load_profile(
        self, degradations: list[ContextDegradation]
    ) -> ContextContribution | None:
        try:
            contribution = self._profile_provider.load_profile()
            if contribution is not None and not isinstance(
                contribution, ContextContribution
            ):
                raise ValueError("invalid profile contribution")
            if (
                contribution is not None
                and contribution.kind != ContextContributionKind.PROFILE
            ):
                raise ValueError("profile provider returned the wrong contribution kind")
            return contribution
        except Exception:
            degradations.append(
                ContextDegradation(
                    ContextDegradationComponent.PROFILE,
                    ContextErrorCode.PROFILE_PROVIDER_FAILED,
                )
            )
            return None

    def _load_memories(
        self,
        query: ContextQuery,
        budget: ContextBudget,
        degradations: list[ContextDegradation],
    ) -> tuple[ContextContribution, ...]:
        try:
            contributions = self._memory_retriever.search(
                query,
                budget.max_memory_items,
                budget.max_memory_tokens,
            )
            if not isinstance(contributions, tuple) or any(
                not isinstance(item, ContextContribution)
                or item.kind != ContextContributionKind.MEMORY
                for item in contributions
            ):
                raise ValueError("invalid memory contributions")
            return contributions
        except Exception:
            degradations.append(
                ContextDegradation(
                    ContextDegradationComponent.MEMORY,
                    ContextErrorCode.MEMORY_PROVIDER_FAILED,
                )
            )
            return ()


def _find_current_turn(
    turns: tuple[ConversationTurn, ...], query: ContextQuery
) -> ConversationTurn | None:
    matches = tuple(turn for turn in turns if turn.turn_id == query.turn_id)
    if len(matches) > 1:
        raise _assembly_error()
    if not matches:
        return None
    turn = matches[0]
    if turn.session_id != query.session_id or turn.run_id != query.run_id:
        raise _assembly_error()
    return turn


def _turn_contribution(
    turn: ConversationTurn | None,
    *,
    content: str,
    kind: ContextContributionKind,
    query: ContextQuery,
) -> ContextContribution:
    turn_id = turn.turn_id if turn else query.turn_id
    sequence = str(turn.sequence) if turn else "unavailable"
    return ContextContribution(
        kind=kind,
        source=(
            "conversation.current_input"
            if kind == ContextContributionKind.CURRENT_INPUT
            else "conversation.turn"
        ),
        content=content,
        estimated_tokens=estimate_tokens(content),
        provenance=ContextProvenance(
            reference=f"conversation://{query.session_id}/{turn_id}",
            attributes=(("turn_id", turn_id), ("sequence", sequence)),
        ),
    )


def _summary_contribution(summary: ConversationSummary) -> ContextContribution:
    return ContextContribution(
        kind=ContextContributionKind.CONVERSATION_SUMMARY,
        source="conversation.summary",
        content=summary.content,
        estimated_tokens=summary.estimated_tokens,
        provenance=ContextProvenance(
            reference=f"conversation-summary://{summary.session_id}/{summary.summary_id}",
            attributes=(
                ("summary_id", summary.summary_id),
                ("version", str(summary.version)),
                ("covered_start_sequence", str(summary.covered_start_sequence)),
                ("covered_end_sequence", str(summary.covered_end_sequence)),
            ),
        ),
    )


def _known_code(value: str | None, fallback: ContextErrorCode) -> ContextErrorCode:
    try:
        return ContextErrorCode(value)
    except (TypeError, ValueError):
        return fallback


def _assembly_error() -> ContextContractError:
    return ContextContractError(
        "Context assembly input is invalid.",
        code=ContextErrorCode.ASSEMBLY_FAILED,
    )
