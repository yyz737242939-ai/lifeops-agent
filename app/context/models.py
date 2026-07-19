"""Immutable, framework-independent models for Stage 9 Context."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.common.validation import (
    require_non_empty_string,
    require_unique_non_empty_strings,
)
from app.context.errors import ContextErrorCode


class ConversationRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class ConversationTurnKind(StrEnum):
    NATURAL_INPUT = "natural_input"
    PLAN_COMMAND = "plan_command"
    CLARIFICATION = "clarification"
    PLAN_PREVIEW = "plan_preview"
    COMMAND_RESULT = "command_result"
    FINAL_ANSWER = "final_answer"


class ContextQueryOrigin(StrEnum):
    CURRENT_USER_GOAL = "current_user_goal"
    CONFIRMED_PLAN_GOAL = "confirmed_plan_goal"


class ContextContributionKind(StrEnum):
    CONVERSATION_SUMMARY = "conversation_summary"
    CONVERSATION_TURN = "conversation_turn"
    CURRENT_INPUT = "current_input"
    PROFILE = "profile"
    MEMORY = "memory"


class ContextDegradationComponent(StrEnum):
    CONVERSATION_HISTORY = "conversation_history"
    CONVERSATION_SUMMARY = "conversation_summary"
    PROFILE = "profile"
    MEMORY = "memory"
    ASSISTANT_PERSISTENCE = "assistant_persistence"


_TURN_KINDS_BY_ROLE = {
    ConversationRole.USER: frozenset(
        {
            ConversationTurnKind.NATURAL_INPUT,
            ConversationTurnKind.PLAN_COMMAND,
        }
    ),
    ConversationRole.ASSISTANT: frozenset(
        {
            ConversationTurnKind.CLARIFICATION,
            ConversationTurnKind.PLAN_PREVIEW,
            ConversationTurnKind.COMMAND_RESULT,
            ConversationTurnKind.FINAL_ANSWER,
        }
    ),
}


@dataclass(frozen=True)
class ConversationTurn:
    schema_version: int
    session_id: str
    turn_id: str
    sequence: int
    role: ConversationRole
    kind: ConversationTurnKind
    content: str
    run_id: str
    created_at: str

    def __post_init__(self) -> None:
        _require_positive_int(self.schema_version, "schema_version")
        require_non_empty_string(self.session_id, "session_id")
        require_non_empty_string(self.turn_id, "turn_id")
        _require_positive_int(self.sequence, "sequence")
        if not isinstance(self.role, ConversationRole):
            raise ValueError("role must be a ConversationRole.")
        if not isinstance(self.kind, ConversationTurnKind):
            raise ValueError("kind must be a ConversationTurnKind.")
        if self.kind not in _TURN_KINDS_BY_ROLE[self.role]:
            raise ValueError("kind must match role.")
        require_non_empty_string(self.content, "content")
        require_non_empty_string(self.run_id, "run_id")
        require_non_empty_string(self.created_at, "created_at")


@dataclass(frozen=True)
class ConversationSummary:
    schema_version: int
    session_id: str
    summary_id: str
    version: int
    covered_start_sequence: int
    covered_end_sequence: int
    content: str
    estimated_tokens: int
    previous_summary_id: str | None
    source_turn_ids: tuple[str, ...]
    provider: str
    model: str
    created_at: str

    def __post_init__(self) -> None:
        _require_positive_int(self.schema_version, "schema_version")
        require_non_empty_string(self.session_id, "session_id")
        require_non_empty_string(self.summary_id, "summary_id")
        _require_positive_int(self.version, "version")
        _require_positive_int(self.covered_start_sequence, "covered_start_sequence")
        _require_positive_int(self.covered_end_sequence, "covered_end_sequence")
        if self.covered_start_sequence > self.covered_end_sequence:
            raise ValueError("covered sequence range must be ordered.")
        require_non_empty_string(self.content, "content")
        _require_non_negative_int(self.estimated_tokens, "estimated_tokens")
        if self.previous_summary_id is not None:
            require_non_empty_string(self.previous_summary_id, "previous_summary_id")
        require_unique_non_empty_strings(self.source_turn_ids, "source_turn_ids")
        require_non_empty_string(self.provider, "provider")
        require_non_empty_string(self.model, "model")
        require_non_empty_string(self.created_at, "created_at")


@dataclass(frozen=True)
class ContextBudget:
    """Composition-owned deterministic limits for one Context assembly."""

    max_total_tokens: int
    max_recent_turns: int
    max_summary_tokens: int
    max_profile_tokens: int
    max_memory_items: int
    max_memory_tokens: int
    max_current_input_tokens: int

    def __post_init__(self) -> None:
        _require_positive_int(self.max_total_tokens, "max_total_tokens")
        _require_non_negative_int(self.max_recent_turns, "max_recent_turns")
        _require_non_negative_int(self.max_summary_tokens, "max_summary_tokens")
        _require_non_negative_int(self.max_profile_tokens, "max_profile_tokens")
        _require_non_negative_int(self.max_memory_items, "max_memory_items")
        _require_non_negative_int(self.max_memory_tokens, "max_memory_tokens")
        _require_positive_int(
            self.max_current_input_tokens, "max_current_input_tokens"
        )
        for field_name, value in (
            ("max_summary_tokens", self.max_summary_tokens),
            ("max_profile_tokens", self.max_profile_tokens),
            ("max_memory_tokens", self.max_memory_tokens),
            ("max_current_input_tokens", self.max_current_input_tokens),
        ):
            if value > self.max_total_tokens:
                raise ValueError(f"{field_name} cannot exceed max_total_tokens.")


@dataclass(frozen=True)
class ContextQuery:
    text: str
    origin: ContextQueryOrigin
    session_id: str
    run_id: str
    turn_id: str

    def __post_init__(self) -> None:
        require_non_empty_string(self.text, "text")
        if not isinstance(self.origin, ContextQueryOrigin):
            raise ValueError("origin must be a ContextQueryOrigin.")
        require_non_empty_string(self.session_id, "session_id")
        require_non_empty_string(self.run_id, "run_id")
        require_non_empty_string(self.turn_id, "turn_id")


@dataclass(frozen=True)
class ContextProvenance:
    """Stable source reference plus immutable, content-free identifiers."""

    reference: str
    attributes: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        require_non_empty_string(self.reference, "reference")
        if not isinstance(self.attributes, tuple):
            raise ValueError("attributes must be a tuple.")
        keys: list[str] = []
        for item in self.attributes:
            if not isinstance(item, tuple) or len(item) != 2:
                raise ValueError("attributes must contain key/value tuples.")
            key, value = item
            require_non_empty_string(key, "attribute key")
            require_non_empty_string(value, "attribute value")
            keys.append(key)
        if len(set(keys)) != len(keys):
            raise ValueError("attributes must not contain duplicate keys.")


@dataclass(frozen=True)
class ContextContribution:
    kind: ContextContributionKind
    source: str
    content: str
    estimated_tokens: int
    provenance: ContextProvenance

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ContextContributionKind):
            raise ValueError("kind must be a ContextContributionKind.")
        require_non_empty_string(self.source, "source")
        require_non_empty_string(self.content, "content")
        _require_non_negative_int(self.estimated_tokens, "estimated_tokens")
        if not isinstance(self.provenance, ContextProvenance):
            raise ValueError("provenance must be ContextProvenance.")


@dataclass(frozen=True)
class ContextSummaryOutput:
    """Typed provider output; local services own ranges, IDs, and token counts."""

    content: str
    provider: str
    model: str

    def __post_init__(self) -> None:
        require_non_empty_string(self.content, "content")
        require_non_empty_string(self.provider, "provider")
        require_non_empty_string(self.model, "model")


@dataclass(frozen=True)
class ContextKindTokenCount:
    kind: ContextContributionKind
    estimated_tokens: int

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ContextContributionKind):
            raise ValueError("kind must be a ContextContributionKind.")
        _require_non_negative_int(self.estimated_tokens, "estimated_tokens")


@dataclass(frozen=True)
class ContextKindCount:
    kind: ContextContributionKind
    count: int

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ContextContributionKind):
            raise ValueError("kind must be a ContextContributionKind.")
        _require_non_negative_int(self.count, "count")


@dataclass(frozen=True)
class ContextDegradation:
    component: ContextDegradationComponent
    error_code: ContextErrorCode

    def __post_init__(self) -> None:
        if not isinstance(self.component, ContextDegradationComponent):
            raise ValueError("component must be a ContextDegradationComponent.")
        if not isinstance(self.error_code, ContextErrorCode):
            raise ValueError("error_code must be a ContextErrorCode.")


@dataclass(frozen=True)
class ContextReport:
    """Content-free assembly diagnostics safe for semantic event projection."""

    assembly_id: str
    selected_turn_count: int
    summary_version: int | None
    summary_covered_range: tuple[int, int] | None
    profile_included: bool
    memory_candidate_count: int
    memory_selected_count: int
    per_kind_estimated_tokens: tuple[ContextKindTokenCount, ...]
    trimmed_counts: tuple[ContextKindCount, ...]
    degradations: tuple[ContextDegradation, ...]
    created_at: str

    def __post_init__(self) -> None:
        require_non_empty_string(self.assembly_id, "assembly_id")
        _require_non_negative_int(self.selected_turn_count, "selected_turn_count")
        if self.summary_version is not None:
            _require_positive_int(self.summary_version, "summary_version")
        if self.summary_covered_range is not None:
            if (
                not isinstance(self.summary_covered_range, tuple)
                or len(self.summary_covered_range) != 2
            ):
                raise ValueError("summary_covered_range must contain two integers.")
            start, end = self.summary_covered_range
            _require_positive_int(start, "summary covered start")
            _require_positive_int(end, "summary covered end")
            if start > end:
                raise ValueError("summary_covered_range must be ordered.")
        if (self.summary_version is None) != (self.summary_covered_range is None):
            raise ValueError("summary version and covered range must appear together.")
        if not isinstance(self.profile_included, bool):
            raise ValueError("profile_included must be a bool.")
        _require_non_negative_int(self.memory_candidate_count, "memory_candidate_count")
        _require_non_negative_int(self.memory_selected_count, "memory_selected_count")
        if self.memory_selected_count > self.memory_candidate_count:
            raise ValueError("memory_selected_count cannot exceed candidate count.")
        _require_unique_kind_tuple(
            self.per_kind_estimated_tokens,
            ContextKindTokenCount,
            "per_kind_estimated_tokens",
        )
        _require_unique_kind_tuple(
            self.trimmed_counts,
            ContextKindCount,
            "trimmed_counts",
        )
        _require_tuple_of(self.degradations, ContextDegradation, "degradations")
        require_non_empty_string(self.created_at, "created_at")


@dataclass(frozen=True)
class ContextAssembly:
    assembly_id: str
    session_id: str
    run_id: str
    turn_id: str
    query: ContextQuery
    contributions: tuple[ContextContribution, ...]
    estimated_total_tokens: int
    report: ContextReport

    def __post_init__(self) -> None:
        require_non_empty_string(self.assembly_id, "assembly_id")
        require_non_empty_string(self.session_id, "session_id")
        require_non_empty_string(self.run_id, "run_id")
        require_non_empty_string(self.turn_id, "turn_id")
        if not isinstance(self.query, ContextQuery):
            raise ValueError("query must be a ContextQuery.")
        if (
            self.session_id,
            self.run_id,
            self.turn_id,
        ) != (
            self.query.session_id,
            self.query.run_id,
            self.query.turn_id,
        ):
            raise ValueError("assembly identity must match query identity.")
        _require_tuple_of(
            self.contributions, ContextContribution, "contributions"
        )
        _require_non_negative_int(
            self.estimated_total_tokens, "estimated_total_tokens"
        )
        if not isinstance(self.report, ContextReport):
            raise ValueError("report must be a ContextReport.")
        if self.report.assembly_id != self.assembly_id:
            raise ValueError("report assembly_id must match assembly_id.")


def _require_positive_int(value: object, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer.")


def _require_non_negative_int(value: object, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer.")


def _require_tuple_of(values: object, item_type: type, field_name: str) -> None:
    if not isinstance(values, tuple) or any(
        not isinstance(item, item_type) for item in values
    ):
        raise ValueError(f"{field_name} must contain {item_type.__name__} values.")


def _require_unique_kind_tuple(
    values: object, item_type: type, field_name: str
) -> None:
    _require_tuple_of(values, item_type, field_name)
    kinds = tuple(item.kind for item in values)  # type: ignore[union-attr]
    if len(set(kinds)) != len(kinds):
        raise ValueError(f"{field_name} must not contain duplicate kinds.")
