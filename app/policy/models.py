"""Policy decision models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class PolicyAction(StrEnum):
    """Supported policy outcomes for one runtime request."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRES_CONFIRMATION = "requires_confirmation"


class PermissionScope(StrEnum):
    """Initial permission scopes used by the policy layer."""

    TASK_WRITE_CANDIDATE = "task.write_candidate"
    MEMORY_WRITE_CANDIDATE = "memory.write_candidate"
    WELLBEING_WRITE_CANDIDATE = "wellbeing.write_candidate"
    RUNTIME_READ = "runtime.read"


@dataclass(frozen=True)
class PolicyDecision:
    """Request-local authorization decision for one runtime request."""

    action: PolicyAction
    authorized_write_scopes: list[PermissionScope] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    requires_confirmation: bool = False
    denied_reason: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.authorized_write_scopes, list):
            raise ValueError("authorized_write_scopes must be a list.")
        for scope in self.authorized_write_scopes:
            if not isinstance(scope, PermissionScope):
                raise ValueError(
                    "authorized_write_scopes must contain PermissionScope values."
                )
        if not isinstance(self.allowed_tools, list):
            raise ValueError("allowed_tools must be a list.")
        for tool_name in self.allowed_tools:
            if not isinstance(tool_name, str) or not tool_name.strip():
                raise ValueError("allowed_tools must contain non-empty strings.")
        if self.denied_reason is not None and not self.denied_reason.strip():
            raise ValueError("denied_reason must be non-empty when provided.")
        if self.reason is not None and not self.reason.strip():
            raise ValueError("reason must be non-empty when provided.")
