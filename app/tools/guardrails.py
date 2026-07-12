"""Deterministic pre- and post-execution Tool guardrails."""

from __future__ import annotations

from typing import Any

from app.tools.errors import ToolNotFoundError, ToolSchemaError
from app.tools.models import (
    AllowedToolSet,
    GuardrailAction,
    GuardrailDecision,
    GuardrailStage,
    ToolCall,
    ToolCallStatus,
    ToolEffect,
    ToolResult,
)
from app.tools.registry import ToolRegistry
from app.tools.schema import validate_tool_value


def evaluate_pre_execution(
    call: ToolCall,
    allowed_tools: AllowedToolSet,
    registry: ToolRegistry,
    *,
    confirmed_tool_name: str | None = None,
) -> GuardrailDecision:
    """Decide whether one concrete ToolCall may reach its handler."""

    try:
        definition = registry.get(call.tool_name)
    except ToolNotFoundError:
        return _decision(
            GuardrailAction.DENY,
            GuardrailStage.PRE_EXECUTION,
            "tool_not_registered",
            "Tool is not registered.",
            call.tool_name,
        )
    if call.tool_name not in allowed_tools.tool_names:
        return _decision(
            GuardrailAction.DENY,
            GuardrailStage.PRE_EXECUTION,
            "tool_not_allowed",
            "Tool is not in the request-local AllowedToolSet.",
            call.tool_name,
        )
    if definition.effect == ToolEffect.WRITE and confirmed_tool_name != call.tool_name:
        return _decision(
            GuardrailAction.REQUIRES_CONFIRMATION,
            GuardrailStage.PRE_EXECUTION,
            "confirmation_required",
            "WRITE Tool requires confirmation bound to this Tool name.",
            call.tool_name,
        )
    try:
        validate_tool_value(call.arguments, definition.input_schema, "arguments")
    except ToolSchemaError:
        return _decision(
            GuardrailAction.DENY,
            GuardrailStage.PRE_EXECUTION,
            "arguments_invalid",
            "Tool arguments do not match the input schema.",
            call.tool_name,
            sanitized_args_summary=_summarize_arguments(call.arguments),
        )
    return _decision(
        GuardrailAction.ALLOW,
        GuardrailStage.PRE_EXECUTION,
        "allowed",
        "Policy, confirmation, and input checks passed.",
        call.tool_name,
        sanitized_args_summary=_summarize_arguments(call.arguments),
        evidence_requirements=("write_effect",)
        if definition.effect == ToolEffect.WRITE
        else (),
    )


def evaluate_post_execution(
    call: ToolCall,
    result: ToolResult,
    registry: ToolRegistry,
) -> GuardrailDecision:
    """Validate handler identity, output contract, and WRITE evidence."""

    try:
        definition = registry.get(call.tool_name)
    except ToolNotFoundError:
        return _decision(
            GuardrailAction.DENY,
            GuardrailStage.POST_EXECUTION,
            "tool_not_registered",
            "Tool is not registered.",
            call.tool_name,
        )
    if result.call_id != call.call_id or result.tool_name != call.tool_name:
        return _decision(
            GuardrailAction.DENY,
            GuardrailStage.POST_EXECUTION,
            "result_identity_mismatch",
            "Tool result does not match the requested call.",
            call.tool_name,
        )
    if result.status != ToolCallStatus.SUCCEEDED:
        return _decision(
            GuardrailAction.DENY,
            GuardrailStage.POST_EXECUTION,
            "tool_not_succeeded",
            "Tool did not return a successful result.",
            call.tool_name,
        )
    try:
        validate_tool_value(result.output, definition.output_schema, "output")
    except ToolSchemaError:
        return _decision(
            GuardrailAction.DENY,
            GuardrailStage.POST_EXECUTION,
            "output_invalid",
            "Tool output does not match the output schema.",
            call.tool_name,
        )
    if definition.effect == ToolEffect.WRITE and not result.evidence:
        return _decision(
            GuardrailAction.DENY,
            GuardrailStage.POST_EXECUTION,
            "write_evidence_missing",
            "Successful WRITE Tool result requires execution evidence.",
            call.tool_name,
            evidence_requirements=("write_effect",),
        )
    return _decision(
        GuardrailAction.ALLOW,
        GuardrailStage.POST_EXECUTION,
        "result_accepted",
        "Output contract and evidence checks passed.",
        call.tool_name,
    )


def _summarize_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    return {name: type(value).__name__ for name, value in sorted(arguments.items())}


def _decision(
    action: GuardrailAction,
    stage: GuardrailStage,
    reason_code: str,
    reason: str,
    tool_name: str,
    *,
    sanitized_args_summary: dict[str, Any] | None = None,
    evidence_requirements: tuple[str, ...] = (),
) -> GuardrailDecision:
    return GuardrailDecision(
        action=action,
        stage=stage,
        reason_code=reason_code,
        reason=reason,
        tool_name=tool_name,
        sanitized_args_summary=sanitized_args_summary or {},
        evidence_requirements=evidence_requirements,
    )
