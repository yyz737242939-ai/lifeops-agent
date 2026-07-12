"""Research Tool contracts and handlers."""

from __future__ import annotations

from app.common.errors import AppError
from app.domains.research.service import ResearchService
from app.tools.models import (
    ExecutionEvidence,
    ToolCall,
    ToolCallStatus,
    ToolDefinition,
    ToolEffect,
    ToolError,
    ToolResult,
    ToolRisk,
)
from app.tools.registry import ToolHandler


FETCH_SOURCE_TOOL = "research.fetch_source"
SAVE_SOURCE_TOOL = "research.save_source"

_OBSERVATION_PROPERTIES = {
    "observation_id": {"type": "string", "minLength": 1},
    "source_key": {"type": "string", "minLength": 1},
    "title": {"type": "string", "minLength": 1},
    "url": {"type": "string", "minLength": 1},
    "summary": {"type": "string", "minLength": 1},
    "content_hash": {"type": "string", "minLength": 1},
    "fetched_at": {"type": "string", "minLength": 1},
    "provenance": {"type": "string", "minLength": 1},
}


def build_research_tools(
    service: ResearchService,
) -> tuple[tuple[ToolDefinition, ToolHandler], ...]:
    fetch_definition = ToolDefinition(
        name=FETCH_SOURCE_TOOL,
        description="Fetch one declared Research fixture source as a temporary observation.",
        input_schema={
            "type": "object",
            "properties": {"source_key": {"type": "string", "minLength": 1}},
            "required": ["source_key"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": _OBSERVATION_PROPERTIES,
            "required": list(_OBSERVATION_PROPERTIES),
            "additionalProperties": False,
        },
        effect=ToolEffect.EXTERNAL_READ,
        risk=ToolRisk.LOW,
        skill_ids=("research",),
    )
    save_definition = ToolDefinition(
        name=SAVE_SOURCE_TOOL,
        description="Persist one request-local Research observation as a Source.",
        input_schema={
            "type": "object",
            "properties": {"observation_id": {"type": "string", "minLength": 1}},
            "required": ["observation_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "source_id": {"type": "string", "minLength": 1},
                "url": {"type": "string", "minLength": 1},
            },
            "required": ["source_id", "url"],
            "additionalProperties": False,
        },
        effect=ToolEffect.WRITE,
        risk=ToolRisk.MEDIUM,
        skill_ids=("research",),
    )

    def fetch_handler(call: ToolCall) -> ToolResult:
        try:
            observation = service.fetch_source(str(call.arguments["source_key"]))
            output = {
                field_name: getattr(observation, field_name)
                for field_name in _OBSERVATION_PROPERTIES
            }
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=ToolCallStatus.SUCCEEDED,
                output=output,
            )
        except (AppError, ValueError, KeyError) as exc:
            return _failed(call, exc)

    def save_handler(call: ToolCall) -> ToolResult:
        try:
            source = service.save_source(str(call.arguments["observation_id"]))
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=ToolCallStatus.SUCCEEDED,
                output={"source_id": source.source_id, "url": source.url},
                evidence=(
                    ExecutionEvidence(
                        evidence_type="research_source_saved",
                        summary="One Research source was persisted.",
                        reference=f"research-source:{source.source_id}",
                    ),
                ),
            )
        except (AppError, ValueError, KeyError) as exc:
            return _failed(call, exc)

    return (
        (fetch_definition, fetch_handler),
        (save_definition, save_handler),
    )


def _failed(call: ToolCall, error: Exception) -> ToolResult:
    code = getattr(error, "code", "research_tool_failed")
    return ToolResult(
        call_id=call.call_id,
        tool_name=call.tool_name,
        status=ToolCallStatus.FAILED,
        error=ToolError(code, "Research Tool could not complete the operation."),
    )
