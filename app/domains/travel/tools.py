"""Travel Tool contracts and handlers."""

from __future__ import annotations

from dataclasses import fields

from app.common.errors import AppError
from app.domains.travel.models import ExternalLookupResult, TravelComparison, Trip
from app.domains.travel.ports import (
    CalendarAvailabilityQuery,
    LodgingSearchQuery,
    PlaceSearchQuery,
    TransportSearchQuery,
    WeatherInformationQuery,
)
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


SAVE_ITINERARY_TOOL = "travel.save_itinerary"
CREATE_TRIP_TOOL = "travel.create_trip"
GET_TRIP_TOOL = "travel.get_trip"
LIST_TRIPS_TOOL = "travel.list_trips"
UPDATE_TRIP_CONSTRAINTS_TOOL = "travel.update_trip_constraints"
ARCHIVE_TRIP_TOOL = "travel.archive_trip"
CHECK_CALENDAR_AVAILABILITY_TOOL = "travel.check_calendar_availability"
GET_WEATHER_TOOL = "travel.get_weather"
SEARCH_TRANSPORT_TOOL = "travel.search_transport"
SEARCH_LODGING_TOOL = "travel.search_lodging"
SEARCH_PLACES_TOOL = "travel.search_places"
COMPARE_OPTIONS_TOOL = "travel.compare_options"
BUILD_ITINERARY_DRAFT_TOOL = "travel.build_itinerary_draft"

_TRIP_PROPERTIES = {
    "trip_id": {"type": "string", "minLength": 1},
    "title": {"type": "string", "minLength": 1},
    "status": {"type": "string", "enum": ["active", "archived"]},
    "version": {"type": "integer", "minimum": 1},
    "created_at": {"type": "string", "minLength": 1},
    "updated_at": {"type": "string", "minLength": 1},
}

_TRIP_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": _TRIP_PROPERTIES,
    "required": list(_TRIP_PROPERTIES),
    "additionalProperties": False,
}

_CONSTRAINT_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {
            "type": "string",
            "enum": [
                "budget",
                "date",
                "destination",
                "document",
                "lodging",
                "other",
                "transport",
                "traveler_count",
            ],
        },
        "value": {"type": "string", "minLength": 1, "maxLength": 1000},
    },
    "required": ["kind", "value"],
    "additionalProperties": False,
}

_OBSERVATION_SCHEMA = {
    "type": "object",
    "properties": {
        "observation_id": {"type": "string", "minLength": 1},
        "provider": {"type": "string", "minLength": 1},
        "source_ref": {"type": "string", "minLength": 1},
        "observed_at": {"type": "string", "minLength": 1},
        "expires_at": {"type": "string", "minLength": 1},
        "provenance": {"type": "string", "minLength": 1},
    },
    "required": [
        "observation_id",
        "provider",
        "source_ref",
        "observed_at",
        "provenance",
    ],
    "additionalProperties": False,
}

_FAILURE_SCHEMA = {
    "type": "object",
    "properties": {
        "provider": {"type": "string", "minLength": 1},
        "code": {
            "type": "string",
            "enum": ["expired", "no_results", "provider_error", "rate_limit", "timeout"],
        },
        "message": {"type": "string", "minLength": 1},
        "retryable": {"type": "boolean"},
    },
    "required": ["provider", "code", "message", "retryable"],
    "additionalProperties": False,
}


def _external_result_schema(candidate_properties: dict) -> dict:
    candidate_schema = {
        "type": "object",
        "properties": candidate_properties,
        "required": list(candidate_properties),
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["success", "no_results", "partial_failure", "failed"],
            },
            "observation": _OBSERVATION_SCHEMA,
            "candidates": {
                "type": "array",
                "maxItems": 100,
                "items": candidate_schema,
            },
            "failures": {
                "type": "array",
                "maxItems": 20,
                "items": _FAILURE_SCHEMA,
            },
        },
        "required": ["status", "observation", "candidates", "failures"],
        "additionalProperties": False,
    }


_ASSESSMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "candidate_id": {"type": "string", "minLength": 1},
        "candidate_kind": {
            "type": "string",
            "enum": ["calendar", "weather", "transport", "lodging", "place"],
        },
        "matched_constraint_ids": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
        "conflicting_constraint_ids": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
        "unresolved_constraint_ids": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
        "expired": {"type": "boolean"},
        "summary": {"type": "string", "minLength": 1},
    },
    "required": [
        "candidate_id",
        "candidate_kind",
        "matched_constraint_ids",
        "conflicting_constraint_ids",
        "unresolved_constraint_ids",
        "expired",
        "summary",
    ],
    "additionalProperties": False,
}


def build_travel_tools(
    service: TravelService,
) -> tuple[tuple[ToolDefinition, ToolHandler], ...]:
    create_trip_definition = ToolDefinition(
        name=CREATE_TRIP_TOOL,
        description="Create one durable Travel trip after confirmation.",
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "minLength": 1, "maxLength": 200}
            },
            "required": ["title"],
            "additionalProperties": False,
        },
        output_schema=_TRIP_OUTPUT_SCHEMA,
        effect=ToolEffect.WRITE,
        risk=ToolRisk.MEDIUM,
        skill_ids=("travel",),
    )
    get_trip_definition = ToolDefinition(
        name=GET_TRIP_TOOL,
        description="Read one saved Travel trip and its declared constraints.",
        input_schema={
            "type": "object",
            "properties": {"trip_id": {"type": "string", "minLength": 1}},
            "required": ["trip_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                **_TRIP_PROPERTIES,
                "constraints": {
                    "type": "array",
                    "maxItems": 64,
                    "items": _CONSTRAINT_SCHEMA,
                },
            },
            "required": [*_TRIP_PROPERTIES, "constraints"],
            "additionalProperties": False,
        },
        effect=ToolEffect.READ,
        risk=ToolRisk.LOW,
        skill_ids=("travel",),
    )
    list_trips_definition = ToolDefinition(
        name=LIST_TRIPS_TOOL,
        description="List saved Travel trips in stable creation order.",
        input_schema={
            "type": "object",
            "properties": {"include_archived": {"type": "boolean"}},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "trips": {
                    "type": "array",
                    "maxItems": 100,
                    "items": _TRIP_OUTPUT_SCHEMA,
                }
            },
            "required": ["trips"],
            "additionalProperties": False,
        },
        effect=ToolEffect.READ,
        risk=ToolRisk.LOW,
        skill_ids=("travel",),
    )
    update_constraints_definition = ToolDefinition(
        name=UPDATE_TRIP_CONSTRAINTS_TOOL,
        description="Replace one active trip's declared constraints after confirmation.",
        input_schema={
            "type": "object",
            "properties": {
                "trip_id": {"type": "string", "minLength": 1},
                "expected_version": {"type": "integer", "minimum": 1},
                "constraints": {
                    "type": "array",
                    "maxItems": 64,
                    "items": _CONSTRAINT_SCHEMA,
                },
            },
            "required": ["trip_id", "expected_version", "constraints"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "trip_id": {"type": "string", "minLength": 1},
                "version": {"type": "integer", "minimum": 1},
                "constraints": {
                    "type": "array",
                    "maxItems": 64,
                    "items": _CONSTRAINT_SCHEMA,
                },
            },
            "required": ["trip_id", "version", "constraints"],
            "additionalProperties": False,
        },
        effect=ToolEffect.WRITE,
        risk=ToolRisk.MEDIUM,
        skill_ids=("travel",),
    )
    archive_trip_definition = ToolDefinition(
        name=ARCHIVE_TRIP_TOOL,
        description="Archive one active Travel trip after confirmation.",
        input_schema={
            "type": "object",
            "properties": {
                "trip_id": {"type": "string", "minLength": 1},
                "expected_version": {"type": "integer", "minimum": 1},
            },
            "required": ["trip_id", "expected_version"],
            "additionalProperties": False,
        },
        output_schema=_TRIP_OUTPUT_SCHEMA,
        effect=ToolEffect.WRITE,
        risk=ToolRisk.MEDIUM,
        skill_ids=("travel",),
    )
    calendar_definition = ToolDefinition(
        name=CHECK_CALENDAR_AVAILABILITY_TOOL,
        description="Check fixture-backed calendar availability without writing Calendar.",
        input_schema={
            "type": "object",
            "properties": {
                "starts_at": {"type": "string", "minLength": 1},
                "ends_at": {"type": "string", "minLength": 1},
                "timezone": {"type": "string", "minLength": 1},
                "minimum_duration_minutes": {"type": "integer", "minimum": 1},
            },
            "required": [
                "starts_at",
                "ends_at",
                "timezone",
                "minimum_duration_minutes",
            ],
            "additionalProperties": False,
        },
        output_schema=_external_result_schema(
            {
                "candidate_id": {"type": "string", "minLength": 1},
                "observation_id": {"type": "string", "minLength": 1},
                "starts_at": {"type": "string", "minLength": 1},
                "ends_at": {"type": "string", "minLength": 1},
                "timezone": {"type": "string", "minLength": 1},
            }
        ),
        effect=ToolEffect.EXTERNAL_READ,
        risk=ToolRisk.LOW,
        skill_ids=("travel",),
    )
    weather_definition = ToolDefinition(
        name=GET_WEATHER_TOOL,
        description="Read fixture-backed weather information for a declared location and date range.",
        input_schema={
            "type": "object",
            "properties": {
                "location": {"type": "string", "minLength": 1},
                "starts_on": {"type": "string", "minLength": 1},
                "ends_on": {"type": "string", "minLength": 1},
            },
            "required": ["location", "starts_on", "ends_on"],
            "additionalProperties": False,
        },
        output_schema=_external_result_schema(
            {
                "candidate_id": {"type": "string", "minLength": 1},
                "observation_id": {"type": "string", "minLength": 1},
                "location": {"type": "string", "minLength": 1},
                "date": {"type": "string", "minLength": 1},
                "condition": {"type": "string", "minLength": 1},
                "temperature_min": {"type": "number"},
                "temperature_max": {"type": "number"},
                "temperature_unit": {"type": "string", "minLength": 1},
            }
        ),
        effect=ToolEffect.EXTERNAL_READ,
        risk=ToolRisk.LOW,
        skill_ids=("travel",),
    )
    transport_definition = ToolDefinition(
        name=SEARCH_TRANSPORT_TOOL,
        description="Search fixture-backed transport candidates without booking.",
        input_schema={
            "type": "object",
            "properties": {
                "origin": {"type": "string", "minLength": 1},
                "destination": {"type": "string", "minLength": 1},
                "departs_on": {"type": "string", "minLength": 1},
                "traveler_count": {"type": "integer", "minimum": 1},
            },
            "required": ["origin", "destination", "departs_on", "traveler_count"],
            "additionalProperties": False,
        },
        output_schema=_external_result_schema(
            {
                "candidate_id": {"type": "string", "minLength": 1},
                "observation_id": {"type": "string", "minLength": 1},
                "origin": {"type": "string", "minLength": 1},
                "destination": {"type": "string", "minLength": 1},
                "mode": {"type": "string", "minLength": 1},
                "departs_at": {"type": "string", "minLength": 1},
                "arrives_at": {"type": "string", "minLength": 1},
                "price_minor": {"type": "integer", "minimum": 0},
                "currency": {"type": "string", "minLength": 1},
            }
        ),
        effect=ToolEffect.EXTERNAL_READ,
        risk=ToolRisk.LOW,
        skill_ids=("travel",),
    )
    lodging_definition = ToolDefinition(
        name=SEARCH_LODGING_TOOL,
        description="Search fixture-backed lodging candidates without booking.",
        input_schema={
            "type": "object",
            "properties": {
                "destination": {"type": "string", "minLength": 1},
                "check_in": {"type": "string", "minLength": 1},
                "check_out": {"type": "string", "minLength": 1},
                "guest_count": {"type": "integer", "minimum": 1},
            },
            "required": ["destination", "check_in", "check_out", "guest_count"],
            "additionalProperties": False,
        },
        output_schema=_external_result_schema(
            {
                "candidate_id": {"type": "string", "minLength": 1},
                "observation_id": {"type": "string", "minLength": 1},
                "destination": {"type": "string", "minLength": 1},
                "name": {"type": "string", "minLength": 1},
                "check_in": {"type": "string", "minLength": 1},
                "check_out": {"type": "string", "minLength": 1},
                "price_minor": {"type": "integer", "minimum": 0},
                "currency": {"type": "string", "minLength": 1},
            }
        ),
        effect=ToolEffect.EXTERNAL_READ,
        risk=ToolRisk.LOW,
        skill_ids=("travel",),
    )
    places_definition = ToolDefinition(
        name=SEARCH_PLACES_TOOL,
        description="Search fixture-backed place candidates for itinerary planning.",
        input_schema={
            "type": "object",
            "properties": {
                "destination": {"type": "string", "minLength": 1},
                "query": {"type": "string", "minLength": 1},
            },
            "required": ["destination", "query"],
            "additionalProperties": False,
        },
        output_schema=_external_result_schema(
            {
                "candidate_id": {"type": "string", "minLength": 1},
                "observation_id": {"type": "string", "minLength": 1},
                "destination": {"type": "string", "minLength": 1},
                "name": {"type": "string", "minLength": 1},
                "category": {"type": "string", "minLength": 1},
                "summary": {"type": "string", "minLength": 1},
            }
        ),
        effect=ToolEffect.EXTERNAL_READ,
        risk=ToolRisk.LOW,
        skill_ids=("travel",),
    )
    compare_definition = ToolDefinition(
        name=COMPARE_OPTIONS_TOOL,
        description="Compare request-local Travel candidates against saved trip constraints.",
        input_schema={
            "type": "object",
            "properties": {
                "trip_id": {"type": "string", "minLength": 1},
                "observation_ids": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 20,
                    "items": {"type": "string", "minLength": 1},
                },
            },
            "required": ["trip_id", "observation_ids"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "comparison_id": {"type": "string", "minLength": 1},
                "trip_id": {"type": "string", "minLength": 1},
                "observation_ids": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "minLength": 1},
                },
                "assessments": {
                    "type": "array",
                    "minItems": 1,
                    "items": _ASSESSMENT_SCHEMA,
                },
                "empty_observation_ids": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                },
                "failures": {
                    "type": "array",
                    "items": _FAILURE_SCHEMA,
                },
                "created_at": {"type": "string", "minLength": 1},
            },
            "required": [
                "comparison_id",
                "trip_id",
                "observation_ids",
                "assessments",
                "empty_observation_ids",
                "failures",
                "created_at",
            ],
            "additionalProperties": False,
        },
        effect=ToolEffect.READ,
        risk=ToolRisk.LOW,
        skill_ids=("travel",),
    )
    draft_definition = ToolDefinition(
        name=BUILD_ITINERARY_DRAFT_TOOL,
        description="Build a versioned request-local itinerary draft from compared candidates.",
        input_schema={
            "type": "object",
            "properties": {
                "comparison_id": {"type": "string", "minLength": 1},
                "candidate_ids": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 100,
                    "items": {"type": "string", "minLength": 1},
                },
                "summary": {"type": "string", "minLength": 1, "maxLength": 4000},
            },
            "required": ["comparison_id", "candidate_ids", "summary"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "draft_id": {"type": "string", "minLength": 1},
                "trip_id": {"type": "string", "minLength": 1},
                "comparison_id": {"type": "string", "minLength": 1},
                "candidate_ids": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "minLength": 1},
                },
                "observation_ids": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "minLength": 1},
                },
                "summary": {"type": "string", "minLength": 1},
                "version": {"type": "integer", "minimum": 1},
                "created_at": {"type": "string", "minLength": 1},
            },
            "required": [
                "draft_id",
                "trip_id",
                "comparison_id",
                "candidate_ids",
                "observation_ids",
                "summary",
                "version",
                "created_at",
            ],
            "additionalProperties": False,
        },
        effect=ToolEffect.READ,
        risk=ToolRisk.LOW,
        skill_ids=("travel",),
    )

    def create_trip_handler(call: ToolCall) -> ToolResult:
        try:
            trip = service.create_trip(str(call.arguments["title"]))
            return _trip_result(
                call,
                trip,
                evidence=ExecutionEvidence(
                    evidence_type="travel_trip_created",
                    summary="One Travel trip was persisted.",
                    reference=f"travel-trip:{trip.trip_id}",
                ),
            )
        except (AppError, ValueError, KeyError) as exc:
            return _failed(call, exc)

    def get_trip_handler(call: ToolCall) -> ToolResult:
        try:
            trip_id = str(call.arguments["trip_id"])
            trip = service.get_trip(trip_id)
            output = _trip_output(trip)
            output["constraints"] = [
                {"kind": item.kind, "value": item.value}
                for item in service.get_trip_constraints(trip_id)
            ]
            return ToolResult(
                call.call_id, call.tool_name, ToolCallStatus.SUCCEEDED, output=output
            )
        except (AppError, ValueError, KeyError) as exc:
            return _failed(call, exc)

    def list_trips_handler(call: ToolCall) -> ToolResult:
        try:
            trips = service.list_trips(
                include_archived=bool(call.arguments.get("include_archived", False))
            )
            return ToolResult(
                call.call_id,
                call.tool_name,
                ToolCallStatus.SUCCEEDED,
                output={"trips": [_trip_output(trip) for trip in trips]},
            )
        except (AppError, ValueError, KeyError) as exc:
            return _failed(call, exc)

    def update_constraints_handler(call: ToolCall) -> ToolResult:
        try:
            trip_id = str(call.arguments["trip_id"])
            constraints = service.update_trip_constraints(
                trip_id,
                tuple(
                    (str(item["kind"]), str(item["value"]))
                    for item in call.arguments["constraints"]
                ),
                expected_version=int(call.arguments["expected_version"]),
            )
            trip = service.get_trip(trip_id)
            return ToolResult(
                call.call_id,
                call.tool_name,
                ToolCallStatus.SUCCEEDED,
                output={
                    "trip_id": trip.trip_id,
                    "version": trip.version,
                    "constraints": [
                        {"kind": item.kind, "value": item.value}
                        for item in constraints
                    ],
                },
                evidence=(
                    ExecutionEvidence(
                        evidence_type="travel_constraints_updated",
                        summary="One Travel trip's constraints were replaced.",
                        reference=f"travel-trip:{trip.trip_id}",
                    ),
                ),
            )
        except (AppError, ValueError, KeyError, TypeError) as exc:
            return _failed(call, exc)

    def archive_trip_handler(call: ToolCall) -> ToolResult:
        try:
            trip = service.archive_trip(
                str(call.arguments["trip_id"]),
                expected_version=int(call.arguments["expected_version"]),
            )
            return _trip_result(
                call,
                trip,
                evidence=ExecutionEvidence(
                    evidence_type="travel_trip_archived",
                    summary="One Travel trip was archived.",
                    reference=f"travel-trip:{trip.trip_id}",
                ),
            )
        except (AppError, ValueError, KeyError, TypeError) as exc:
            return _failed(call, exc)
    save_definition = ToolDefinition(
        name=SAVE_ITINERARY_TOOL,
        description="Persist one confirmed request-local itinerary draft idempotently.",
        input_schema={
            "type": "object",
            "properties": {
                "draft_id": {"type": "string", "minLength": 1},
                "idempotency_key": {"type": "string", "minLength": 1},
            },
            "required": ["draft_id", "idempotency_key"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "itinerary_id": {"type": "string", "minLength": 1},
                "destination": {"type": "string", "minLength": 1},
                "draft_id": {"type": "string", "minLength": 1},
                "version": {"type": "integer", "minimum": 1},
                "item_ids": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "minLength": 1},
                },
                "decision_id": {"type": "string", "minLength": 1},
            },
            "required": [
                "itinerary_id",
                "destination",
                "draft_id",
                "version",
                "item_ids",
                "decision_id",
            ],
            "additionalProperties": False,
        },
        effect=ToolEffect.WRITE,
        risk=ToolRisk.MEDIUM,
        skill_ids=("travel",),
    )

    def calendar_handler(call: ToolCall) -> ToolResult:
        try:
            result = service.check_calendar_availability(
                CalendarAvailabilityQuery(
                    starts_at=str(call.arguments["starts_at"]),
                    ends_at=str(call.arguments["ends_at"]),
                    timezone=str(call.arguments["timezone"]),
                    minimum_duration_minutes=int(
                        call.arguments["minimum_duration_minutes"]
                    ),
                )
            )
            return _external_result(call, result)
        except (AppError, ValueError, KeyError, TypeError) as exc:
            return _failed(call, exc)

    def weather_handler(call: ToolCall) -> ToolResult:
        try:
            result = service.get_weather(
                WeatherInformationQuery(
                    location=str(call.arguments["location"]),
                    starts_on=str(call.arguments["starts_on"]),
                    ends_on=str(call.arguments["ends_on"]),
                )
            )
            return _external_result(call, result)
        except (AppError, ValueError, KeyError, TypeError) as exc:
            return _failed(call, exc)

    def transport_handler(call: ToolCall) -> ToolResult:
        try:
            result = service.search_transport(
                TransportSearchQuery(
                    origin=str(call.arguments["origin"]),
                    destination=str(call.arguments["destination"]),
                    departs_on=str(call.arguments["departs_on"]),
                    traveler_count=int(call.arguments["traveler_count"]),
                )
            )
            return _external_result(call, result)
        except (AppError, ValueError, KeyError, TypeError) as exc:
            return _failed(call, exc)

    def lodging_handler(call: ToolCall) -> ToolResult:
        try:
            result = service.search_lodging(
                LodgingSearchQuery(
                    destination=str(call.arguments["destination"]),
                    check_in=str(call.arguments["check_in"]),
                    check_out=str(call.arguments["check_out"]),
                    guest_count=int(call.arguments["guest_count"]),
                )
            )
            return _external_result(call, result)
        except (AppError, ValueError, KeyError, TypeError) as exc:
            return _failed(call, exc)

    def places_handler(call: ToolCall) -> ToolResult:
        try:
            result = service.search_places(
                PlaceSearchQuery(
                    destination=str(call.arguments["destination"]),
                    query=str(call.arguments["query"]),
                )
            )
            return _external_result(call, result)
        except (AppError, ValueError, KeyError, TypeError) as exc:
            return _failed(call, exc)

    def compare_handler(call: ToolCall) -> ToolResult:
        try:
            comparison = service.compare_candidates(
                str(call.arguments["trip_id"]),
                tuple(str(item) for item in call.arguments["observation_ids"]),
            )
            return ToolResult(
                call.call_id,
                call.tool_name,
                ToolCallStatus.SUCCEEDED,
                output=_comparison_output(comparison),
            )
        except (AppError, ValueError, KeyError, TypeError) as exc:
            return _failed(call, exc)

    def draft_handler(call: ToolCall) -> ToolResult:
        try:
            draft = service.build_itinerary_draft(
                str(call.arguments["comparison_id"]),
                tuple(str(item) for item in call.arguments["candidate_ids"]),
                str(call.arguments["summary"]),
            )
            return ToolResult(
                call.call_id,
                call.tool_name,
                ToolCallStatus.SUCCEEDED,
                output={
                    "draft_id": draft.draft_id,
                    "trip_id": draft.trip_id,
                    "comparison_id": draft.comparison_id,
                    "candidate_ids": list(draft.candidate_ids),
                    "observation_ids": list(draft.observation_ids),
                    "summary": draft.summary,
                    "version": draft.version,
                    "created_at": draft.created_at,
                },
            )
        except (AppError, ValueError, KeyError, TypeError) as exc:
            return _failed(call, exc)

    def save_handler(call: ToolCall) -> ToolResult:
        try:
            saved = service.save_itinerary(
                str(call.arguments["draft_id"]),
                str(call.arguments["idempotency_key"]),
            )
            itinerary = saved.itinerary
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=ToolCallStatus.SUCCEEDED,
                output={
                    "itinerary_id": itinerary.itinerary_id,
                    "destination": itinerary.destination,
                    "draft_id": itinerary.draft_id,
                    "version": itinerary.version,
                    "item_ids": [item.item_id for item in saved.items],
                    "decision_id": saved.decision.decision_id,
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
        (create_trip_definition, create_trip_handler),
        (get_trip_definition, get_trip_handler),
        (list_trips_definition, list_trips_handler),
        (update_constraints_definition, update_constraints_handler),
        (archive_trip_definition, archive_trip_handler),
        (calendar_definition, calendar_handler),
        (weather_definition, weather_handler),
        (transport_definition, transport_handler),
        (lodging_definition, lodging_handler),
        (places_definition, places_handler),
        (compare_definition, compare_handler),
        (draft_definition, draft_handler),
        (save_definition, save_handler),
    )


def _external_result(
    call: ToolCall, result: ExternalLookupResult
) -> ToolResult:
    observation = {
        field_name: getattr(result.observation, field_name)
        for field_name in (
            "observation_id",
            "provider",
            "source_ref",
            "observed_at",
            "expires_at",
            "provenance",
        )
        if getattr(result.observation, field_name) is not None
    }
    candidates = [
        {field.name: getattr(candidate, field.name) for field in fields(candidate)}
        for candidate in result.candidates
    ]
    failures = [
        {
            "provider": failure.provider,
            "code": failure.code,
            "message": failure.message,
            "retryable": failure.retryable,
        }
        for failure in result.failures
    ]
    return ToolResult(
        call.call_id,
        call.tool_name,
        ToolCallStatus.SUCCEEDED,
        output={
            "status": result.status,
            "observation": observation,
            "candidates": candidates,
            "failures": failures,
        },
    )


def _comparison_output(comparison: TravelComparison) -> dict[str, object]:
    return {
        "comparison_id": comparison.comparison_id,
        "trip_id": comparison.trip_id,
        "observation_ids": list(comparison.observation_ids),
        "assessments": [
            {
                "candidate_id": item.candidate_id,
                "candidate_kind": item.candidate_kind,
                "matched_constraint_ids": list(item.matched_constraint_ids),
                "conflicting_constraint_ids": list(
                    item.conflicting_constraint_ids
                ),
                "unresolved_constraint_ids": list(item.unresolved_constraint_ids),
                "expired": item.expired,
                "summary": item.summary,
            }
            for item in comparison.assessments
        ],
        "empty_observation_ids": list(comparison.empty_observation_ids),
        "failures": [
            {
                "provider": failure.provider,
                "code": failure.code,
                "message": failure.message,
                "retryable": failure.retryable,
            }
            for failure in comparison.failures
        ],
        "created_at": comparison.created_at,
    }


def _trip_output(trip: Trip) -> dict[str, object]:
    return {field_name: getattr(trip, field_name) for field_name in _TRIP_PROPERTIES}


def _trip_result(
    call: ToolCall,
    trip: Trip,
    *,
    evidence: ExecutionEvidence,
) -> ToolResult:
    return ToolResult(
        call.call_id,
        call.tool_name,
        ToolCallStatus.SUCCEEDED,
        output=_trip_output(trip),
        evidence=(evidence,),
    )


def _failed(call: ToolCall, error: Exception) -> ToolResult:
    code = getattr(error, "code", "travel_tool_failed")
    return ToolResult(
        call_id=call.call_id,
        tool_name=call.tool_name,
        status=ToolCallStatus.FAILED,
        error=ToolError(code, "Travel Tool could not complete the operation."),
    )
