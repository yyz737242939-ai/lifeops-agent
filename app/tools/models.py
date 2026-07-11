"""Framework-independent Tool System models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import re
from typing import Any

from app.common.validation import (
    require_non_empty_string,
    require_unique_non_empty_strings,
)


_TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
_CAPABILITY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")


def _require_object_schema(schema: dict[str, Any], field_name: str) -> None:
    if not isinstance(schema, dict):
        raise ValueError(f"{field_name} must be a dict.")
    if schema.get("type") != "object":
        raise ValueError(f'{field_name} must declare type="object".')
    properties = schema.get("properties")
    if properties is not None and not isinstance(properties, dict):
        raise ValueError(f"{field_name}.properties must be a dict when provided.")
    required = schema.get("required")
    if required is not None:
        if not isinstance(required, list) or any(
            not isinstance(item, str) or not item.strip() for item in required
        ):
            raise ValueError(
                f"{field_name}.required must be a list of non-empty strings."
            )
        if len(set(required)) != len(required):
            raise ValueError(f"{field_name}.required must not contain duplicates.")
        if properties is not None and not set(required).issubset(properties):
            raise ValueError(
                f"{field_name}.required must only reference declared properties."
            )


class ToolEffect(StrEnum):
    READ = "read"
    WRITE = "write"
    EXTERNAL_READ = "external_read"


class ToolRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ToolCallStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"
    REQUIRES_CONFIRMATION = "requires_confirmation"


class GuardrailAction(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRES_CONFIRMATION = "requires_confirmation"


class GuardrailStage(StrEnum):
    PRE_EXECUTION = "pre_execution"
    POST_EXECUTION = "post_execution"


@dataclass(frozen=True)
class ToolDefinition:
    """Code-configured contract for one tool, separate from its handler."""

    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    effect: ToolEffect
    risk: ToolRisk
    required_scopes: tuple[str, ...] = field(default_factory=tuple)
    required_capabilities: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        require_non_empty_string(self.name, "name")
        if not _TOOL_NAME_PATTERN.fullmatch(self.name):
            raise ValueError(
                "name must use lowercase dot-separated segments containing "
                "letters, numbers, or underscores."
            )
        require_non_empty_string(self.description, "description")
        _require_object_schema(self.input_schema, "input_schema")
        _require_object_schema(self.output_schema, "output_schema")
        if not isinstance(self.effect, ToolEffect):
            raise ValueError("effect must be a ToolEffect.")
        if not isinstance(self.risk, ToolRisk):
            raise ValueError("risk must be a ToolRisk.")
        require_unique_non_empty_strings(self.required_scopes, "required_scopes")
        require_unique_non_empty_strings(
            self.required_capabilities, "required_capabilities"
        )


@dataclass(frozen=True)
class ToolCapability:
    """One stable capability that tools may require and callers may hold."""

    name: str
    description: str = ""

    def __post_init__(self) -> None:
        require_non_empty_string(self.name, "name")
        if not _CAPABILITY_PATTERN.fullmatch(self.name):
            raise ValueError(
                "name must use at least two lowercase dot-separated segments."
            )
        if not isinstance(self.description, str):
            raise ValueError("description must be a string.")


@dataclass(frozen=True)
class ToolCapabilitySet:
    """Request-local capabilities and visible tool names after intersection."""

    capabilities: tuple[str, ...] = field(default_factory=tuple)
    tool_names: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        require_unique_non_empty_strings(self.capabilities, "capabilities")
        require_unique_non_empty_strings(self.tool_names, "tool_names")


@dataclass(frozen=True)
class ToolCall:
    """Structured request to invoke one tool through the future gateway."""

    call_id: str
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_non_empty_string(self.call_id, "call_id")
        require_non_empty_string(self.tool_name, "tool_name")
        if not isinstance(self.arguments, dict):
            raise ValueError("arguments must be a dict.")


@dataclass(frozen=True)
class ToolError:
    code: str
    message: str
    retryable: bool = False

    def __post_init__(self) -> None:
        require_non_empty_string(self.code, "code")
        require_non_empty_string(self.message, "message")
        if not isinstance(self.retryable, bool):
            raise ValueError("retryable must be a bool.")


@dataclass(frozen=True)
class ExecutionEvidence:
    """Evidence supporting what a handler actually observed or changed."""

    evidence_type: str
    summary: str
    reference: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_non_empty_string(self.evidence_type, "evidence_type")
        require_non_empty_string(self.summary, "summary")
        if self.reference is not None:
            require_non_empty_string(self.reference, "reference")
        if not isinstance(self.attributes, dict):
            raise ValueError("attributes must be a dict.")


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    tool_name: str
    status: ToolCallStatus
    output: dict[str, Any] | None = None
    evidence: tuple[ExecutionEvidence, ...] = field(default_factory=tuple)
    error: ToolError | None = None

    def __post_init__(self) -> None:
        require_non_empty_string(self.call_id, "call_id")
        require_non_empty_string(self.tool_name, "tool_name")
        if not isinstance(self.status, ToolCallStatus):
            raise ValueError("status must be a ToolCallStatus.")
        if self.output is not None and not isinstance(self.output, dict):
            raise ValueError("output must be a dict when provided.")
        if not isinstance(self.evidence, tuple) or any(
            not isinstance(item, ExecutionEvidence) for item in self.evidence
        ):
            raise ValueError("evidence must contain ExecutionEvidence values.")
        if self.error is not None and not isinstance(self.error, ToolError):
            raise ValueError("error must be a ToolError when provided.")
        if self.status == ToolCallStatus.SUCCEEDED and self.error is not None:
            raise ValueError("a succeeded result must not contain an error.")
        if self.status == ToolCallStatus.FAILED and self.error is None:
            raise ValueError("a failed result must contain an error.")


@dataclass(frozen=True)
class GuardrailDecision:
    """Auditable pre- or post-execution safety decision."""

    action: GuardrailAction
    stage: GuardrailStage
    reason_code: str
    reason: str
    tool_name: str
    required_scopes: tuple[str, ...] = field(default_factory=tuple)
    satisfied_scopes: tuple[str, ...] = field(default_factory=tuple)
    sanitized_args_summary: dict[str, Any] = field(default_factory=dict)
    evidence_requirements: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.action, GuardrailAction):
            raise ValueError("action must be a GuardrailAction.")
        if not isinstance(self.stage, GuardrailStage):
            raise ValueError("stage must be a GuardrailStage.")
        require_non_empty_string(self.reason_code, "reason_code")
        require_non_empty_string(self.reason, "reason")
        require_non_empty_string(self.tool_name, "tool_name")
        require_unique_non_empty_strings(self.required_scopes, "required_scopes")
        require_unique_non_empty_strings(self.satisfied_scopes, "satisfied_scopes")
        if not set(self.satisfied_scopes).issubset(self.required_scopes):
            raise ValueError("satisfied_scopes must be a subset of required_scopes.")
        if not isinstance(self.sanitized_args_summary, dict):
            raise ValueError("sanitized_args_summary must be a dict.")
        require_unique_non_empty_strings(
            self.evidence_requirements, "evidence_requirements"
        )
