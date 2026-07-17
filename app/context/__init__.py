"""Framework-independent contracts for bounded conversation Context."""

from app.context.budget import (
    ESTIMATED_CHARACTERS_PER_TOKEN,
    estimate_tokens,
    normalize_text_for_token_estimate,
)
from app.context.adapters import (
    EmptyMemoryRetriever,
    EmptyProfileProvider,
    FakeMemoryRetriever,
    FakeProfileProvider,
)
from app.context.assembler import ContextAssembler
from app.context.errors import (
    ContextContractError,
    ContextError,
    ContextErrorCode,
    ContextProviderError,
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
    ContextQueryOrigin,
    ContextReport,
    ContextSummaryOutput,
    ConversationRole,
    ConversationSummary,
    ConversationTurn,
    ConversationTurnKind,
)
from app.context.ports import (
    ContextSummarizer,
    ConversationRepository,
    MemoryRetriever,
    ProfileProvider,
)
from app.context.projection import project_context_contributions
from app.context.repository import (
    CONVERSATION_CONCURRENCY_POLICY,
    CorruptTailPolicy,
    JsonlConversationRepository,
)
from app.context.summary_service import RollingSummaryService

__all__ = (
    "ContextAssembly",
    "ContextAssembler",
    "ContextBudget",
    "ContextContractError",
    "ContextContribution",
    "ContextContributionKind",
    "ContextDegradation",
    "ContextDegradationComponent",
    "ContextError",
    "ContextErrorCode",
    "ContextKindCount",
    "ContextKindTokenCount",
    "ContextProviderError",
    "ContextProvenance",
    "ContextQuery",
    "ContextQueryOrigin",
    "ContextReport",
    "ContextSummarizer",
    "ContextSummaryOutput",
    "CONVERSATION_CONCURRENCY_POLICY",
    "ConversationRepository",
    "ConversationRepositoryError",
    "ConversationRole",
    "ConversationSummary",
    "ConversationTurn",
    "ConversationTurnKind",
    "CorruptTailPolicy",
    "ESTIMATED_CHARACTERS_PER_TOKEN",
    "EmptyMemoryRetriever",
    "EmptyProfileProvider",
    "FakeMemoryRetriever",
    "FakeProfileProvider",
    "JsonlConversationRepository",
    "MemoryRetriever",
    "ProfileProvider",
    "RollingSummaryService",
    "estimate_tokens",
    "normalize_text_for_token_estimate",
    "project_context_contributions",
)
