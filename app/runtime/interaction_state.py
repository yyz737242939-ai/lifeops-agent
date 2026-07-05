from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4

from app.utils.time import now_iso


class RiskLevel(StrEnum):
    """Risk category for a pending user-confirmed operation."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PendingConfirmationStatus(StrEnum):
    """Lifecycle status for one cross-turn confirmation request."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"
    CONSUMED = "consumed"


@dataclass
class PendingConfirmation:
    """Temporary safety state for one operation awaiting user confirmation."""

    operation: str
    risk_level: RiskLevel
    scope_summary: str
    arguments: dict[str, Any]
    source_user_input: str
    tool_name: str | None = None
    created_turn_index: int = 0
    expires_after_turns: int = 2
    requires_current_confirmation: bool = True
    id: str = field(default_factory=lambda: f"pending_{uuid4().hex}")
    status: PendingConfirmationStatus = PendingConfirmationStatus.PENDING
    created_at: str = field(default_factory=now_iso)
    consumed_turn_index: int | None = None

    def __post_init__(self) -> None:
        if not self.operation.strip():
            raise ValueError("operation must not be empty")
        if not self.scope_summary.strip():
            raise ValueError("scope_summary must not be empty")
        if self.expires_after_turns < 1:
            raise ValueError("expires_after_turns must be at least 1")
        if self.created_turn_index < 0:
            raise ValueError("created_turn_index must be at least 0")

    @property
    def is_pending(self) -> bool:
        return self.status == PendingConfirmationStatus.PENDING

    def is_expired_at(self, turn_index: int) -> bool:
        return turn_index > self.created_turn_index + self.expires_after_turns

    def expire(self) -> None:
        self._ensure_pending()
        self.status = PendingConfirmationStatus.EXPIRED

    def confirm(self) -> None:
        self._ensure_pending()
        self.status = PendingConfirmationStatus.CONFIRMED

    def cancel(self) -> None:
        self._ensure_pending()
        self.status = PendingConfirmationStatus.CANCELLED

    def supersede(self) -> None:
        self._ensure_pending()
        self.status = PendingConfirmationStatus.SUPERSEDED

    def consume(self, *, turn_index: int) -> None:
        if self.status != PendingConfirmationStatus.CONFIRMED:
            raise RuntimeError("Only a confirmed pending operation can be consumed")
        self.status = PendingConfirmationStatus.CONSUMED
        self.consumed_turn_index = turn_index

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "operation": self.operation,
            "tool_name": self.tool_name,
            "risk_level": self.risk_level.value,
            "scope_summary": self.scope_summary,
            "arguments": self.arguments,
            "created_at": self.created_at,
            "created_turn_index": self.created_turn_index,
            "expires_after_turns": self.expires_after_turns,
            "status": self.status.value,
            "requires_current_confirmation": self.requires_current_confirmation,
            "source_user_input": self.source_user_input,
            "consumed_turn_index": self.consumed_turn_index,
        }

    def _ensure_pending(self) -> None:
        if self.status != PendingConfirmationStatus.PENDING:
            raise RuntimeError("Pending confirmation is already terminal")


@dataclass
class InteractionState:
    """Cross-turn temporary interaction state owned by one Agent instance."""

    pending_confirmation: PendingConfirmation | None = None
    turn_index: int = 0

    def advance_turn(self) -> int:
        self.turn_index += 1
        self.expire_pending_if_needed()
        return self.turn_index

    def create_pending_confirmation(
        self,
        *,
        operation: str,
        risk_level: RiskLevel,
        scope_summary: str,
        arguments: dict[str, Any],
        source_user_input: str,
        tool_name: str | None = None,
        expires_after_turns: int = 2,
        requires_current_confirmation: bool = True,
    ) -> PendingConfirmation:
        if self.pending_confirmation is not None and self.pending_confirmation.is_pending:
            self.pending_confirmation.supersede()

        pending = PendingConfirmation(
            operation=operation,
            tool_name=tool_name,
            risk_level=risk_level,
            scope_summary=scope_summary,
            arguments=arguments,
            created_turn_index=self.turn_index,
            expires_after_turns=expires_after_turns,
            requires_current_confirmation=requires_current_confirmation,
            source_user_input=source_user_input,
        )
        self.pending_confirmation = pending
        return pending

    def confirm_pending(self) -> PendingConfirmation | None:
        pending = self.active_pending_confirmation
        if pending is None:
            return None
        pending.confirm()
        return pending

    def cancel_pending(self) -> PendingConfirmation | None:
        pending = self.active_pending_confirmation
        if pending is None:
            return None
        pending.cancel()
        return pending

    def consume_confirmed_pending(self) -> PendingConfirmation | None:
        pending = self.pending_confirmation
        if pending is None or pending.status != PendingConfirmationStatus.CONFIRMED:
            return None
        pending.consume(turn_index=self.turn_index)
        self.pending_confirmation = None
        return pending

    def clear_terminal_pending(self) -> PendingConfirmation | None:
        pending = self.pending_confirmation
        if pending is not None and not pending.is_pending:
            self.pending_confirmation = None
            return pending
        return None

    def expire_pending_if_needed(self) -> PendingConfirmation | None:
        pending = self.active_pending_confirmation
        if pending is None or not pending.is_expired_at(self.turn_index):
            return None
        pending.expire()
        return pending

    @property
    def active_pending_confirmation(self) -> PendingConfirmation | None:
        if self.pending_confirmation is None:
            return None
        if not self.pending_confirmation.is_pending:
            return None
        return self.pending_confirmation

    def to_dict(self) -> dict[str, Any]:
        return {
            "state_scope": "cross_turn_interaction_safety",
            "turn_index": self.turn_index,
            "pending_confirmation": (
                self.pending_confirmation.to_dict()
                if self.pending_confirmation is not None
                else None
            ),
        }
