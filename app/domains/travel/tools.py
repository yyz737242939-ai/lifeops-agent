"""Travel Tool contracts and handlers."""

from __future__ import annotations

from app.common.errors import AppError
from app.domains.travel.service import TravelService
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


SEARCH_OPTIONS_TOOL = "travel.search_options"
SAVE_ITINERARY_TOOL = "travel.save_itinerary"

_OPTION_PROPERTIES = {
    "option_id": {"type": "string", "minLength": 1},
    "destination": {"type": "string", "minLength": 1},
    "transport": {"type": "string", "minLength": 1},
    "lodging": {"type": "string", "minLength": 1},
    "summary": {"type": "string", "minLength": 1},
    "observed_at": {"type": "string", "minLength": 1},
    "expires_at": {"type": "string", "minLength": 1},
    "provenance": {"type": "string", "minLength": 1},
}


def build_travel_tools(
    service: TravelService,
) -> tuple[tuple[ToolDefinition, ToolHandler], ...]:
    search_definition = ToolDefinition(
        name=SEARCH_OPTIONS_TOOL,
        description="Search one declared fixture-backed Travel option.",
        input_schema={
            "type": "object",
            "properties": {"destination": {"type": "string", "minLength": 1}},
            "required": ["destination"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": _OPTION_PROPERTIES,
            "required": list(_OPTION_PROPERTIES),
            "additionalProperties": False,
        },
        effect=ToolEffect.EXTERNAL_READ,
        risk=ToolRisk.LOW,
        skill_ids=("travel",),
    )
    save_definition = ToolDefinition(
        name=SAVE_ITINERARY_TOOL,
        description="Persist one request-local Travel option as an itinerary.",
        input_schema={
            "type": "object",
            "properties": {"option_id": {"type": "string", "minLength": 1}},
            "required": ["option_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "itinerary_id": {"type": "string", "minLength": 1},
                "destination": {"type": "string", "minLength": 1},
            },
            "required": ["itinerary_id", "destination"],
            "additionalProperties": False,
        },
        effect=ToolEffect.WRITE,
        risk=ToolRisk.MEDIUM,
        skill_ids=("travel",),
    )

    def search_handler(call: ToolCall) -> ToolResult:
        try:
            option = service.search_options(str(call.arguments["destination"]))
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=ToolCallStatus.SUCCEEDED,
                output={
                    field_name: getattr(option, field_name)
                    for field_name in _OPTION_PROPERTIES
                },
            )
        except (AppError, ValueError, KeyError) as exc:
            return _failed(call, exc)

    def save_handler(call: ToolCall) -> ToolResult:
        try:
            itinerary = service.save_itinerary(str(call.arguments["option_id"]))
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=ToolCallStatus.SUCCEEDED,
                output={
                    "itinerary_id": itinerary.itinerary_id,
                    "destination": itinerary.destination,
                },
                evidence=(
                    ExecutionEvidence(
                        evidence_type="travel_itinerary_saved",
                        summary="One Travel itinerary was persisted.",
                        reference=f"travel-itinerary:{itinerary.itinerary_id}",
                    ),
                ),
            )
        except (AppError, ValueError, KeyError) as exc:
            return _failed(call, exc)

    return (
        (search_definition, search_handler),
        (save_definition, save_handler),
    )


def _failed(call: ToolCall, error: Exception) -> ToolResult:
    code = getattr(error, "code", "travel_tool_failed")
    return ToolResult(
        call_id=call.call_id,
        tool_name=call.tool_name,
        status=ToolCallStatus.FAILED,
        error=ToolError(code, "Travel Tool could not complete the operation."),
    )
