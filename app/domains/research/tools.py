"""Research Tool contracts and handlers."""

from __future__ import annotations

from app.common.errors import AppError
from app.domains.research.models import ResearchItemSet
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
FETCH_BRIEFING_SOURCE_TOOL = "research.fetch_briefing_source"
PARSE_ITEMS_TOOL = "research.parse_items"
RANK_ITEMS_TOOL = "research.rank_items"
BUILD_BRIEF_DRAFT_TOOL = "research.build_brief_draft"
SAVE_SOURCE_TOOL = "research.save_source"
SAVE_BRIEF_TOOL = "research.save_brief"
CREATE_NOTE_TOOL = "research.create_note"
SEARCH_KNOWLEDGE_TOOL = "research.search_knowledge"

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

_ITEM_PROPERTIES = {
    "item_id": {"type": "string", "minLength": 1},
    "source_key": {"type": "string", "minLength": 1},
    "title": {"type": "string", "minLength": 1},
    "url": {"type": "string", "minLength": 1},
    "raw_position": {"type": "integer", "minimum": 1},
    "topic_hint": {"type": "string", "minLength": 1},
    "score": {"type": "integer"},
}

_ITEM_SET_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "item_set_id": {"type": "string", "minLength": 1},
        "items": {
            "type": "array",
            "minItems": 1,
            "maxItems": 20,
            "items": {
                "type": "object",
                "properties": _ITEM_PROPERTIES,
                "required": list(_ITEM_PROPERTIES),
                "additionalProperties": False,
            },
        },
    },
    "required": ["item_set_id", "items"],
    "additionalProperties": False,
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
    fetch_briefing_definition = ToolDefinition(
        name=FETCH_BRIEFING_SOURCE_TOOL,
        description="Fetch one declared Hugging Face list page for a temporary briefing.",
        input_schema={
            "type": "object",
            "properties": {"source_key": {"type": "string", "minLength": 1}},
            "required": ["source_key"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "document_id": {"type": "string", "minLength": 1},
                "observation_id": {"type": "string", "minLength": 1},
                "source_key": {"type": "string", "minLength": 1},
                "title": {"type": "string", "minLength": 1},
                "url": {"type": "string", "minLength": 1},
                "content_hash": {"type": "string", "minLength": 1},
                "fetched_at": {"type": "string", "minLength": 1},
                "provenance": {"type": "string", "minLength": 1},
            },
            "required": [
                "document_id",
                "observation_id",
                "source_key",
                "title",
                "url",
                "content_hash",
                "fetched_at",
                "provenance",
            ],
            "additionalProperties": False,
        },
        effect=ToolEffect.EXTERNAL_READ,
        risk=ToolRisk.LOW,
        skill_ids=("research",),
    )
    save_brief_definition = ToolDefinition(
        name=SAVE_BRIEF_TOOL,
        description="Persist one request-local Research brief draft whose sources are saved.",
        input_schema={
            "type": "object",
            "properties": {"draft_id": {"type": "string", "minLength": 1}},
            "required": ["draft_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "brief_id": {"type": "string", "minLength": 1},
                "title": {"type": "string", "minLength": 1},
            },
            "required": ["brief_id", "title"],
            "additionalProperties": False,
        },
        effect=ToolEffect.WRITE,
        risk=ToolRisk.MEDIUM,
        skill_ids=("research",),
    )
    create_note_definition = ToolDefinition(
        name=CREATE_NOTE_TOOL,
        description="Persist one explicitly confirmed Research note.",
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "minLength": 1, "maxLength": 200},
                "body": {"type": "string", "minLength": 1, "maxLength": 12000},
            },
            "required": ["title", "body"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "minLength": 1},
                "title": {"type": "string", "minLength": 1},
            },
            "required": ["note_id", "title"],
            "additionalProperties": False,
        },
        effect=ToolEffect.WRITE,
        risk=ToolRisk.MEDIUM,
        skill_ids=("research",),
    )
    parse_definition = ToolDefinition(
        name=PARSE_ITEMS_TOOL,
        description="Parse one request-local Research document into typed list items.",
        input_schema={
            "type": "object",
            "properties": {
                "document_id": {"type": "string", "minLength": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["document_id", "limit"],
            "additionalProperties": False,
        },
        output_schema=_ITEM_SET_OUTPUT_SCHEMA,
        effect=ToolEffect.READ,
        risk=ToolRisk.LOW,
        skill_ids=("research",),
    )
    rank_definition = ToolDefinition(
        name=RANK_ITEMS_TOOL,
        description="Deduplicate and rank one request-local Research item set.",
        input_schema={
            "type": "object",
            "properties": {
                "item_set_id": {"type": "string", "minLength": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                "topic_filter": {"type": "string", "minLength": 1},
            },
            "required": ["item_set_id", "limit"],
            "additionalProperties": False,
        },
        output_schema=_ITEM_SET_OUTPUT_SCHEMA,
        effect=ToolEffect.READ,
        risk=ToolRisk.LOW,
        skill_ids=("research",),
    )
    search_definition = ToolDefinition(
        name=SEARCH_KNOWLEDGE_TOOL,
        description="Search saved Research sources, notes, and briefs with pagination.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1},
                "item_kinds": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 3,
                    "items": {
                        "type": "string",
                        "enum": ["source", "note", "brief"],
                    },
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                "offset": {"type": "integer", "minimum": 0},
            },
            "required": ["query", "item_kinds", "limit", "offset"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "maxItems": 100,
                    "items": {
                        "type": "object",
                        "properties": {
                            "item_id": {"type": "string", "minLength": 1},
                            "item_kind": {
                                "type": "string",
                                "enum": ["source", "note", "brief"],
                            },
                            "title": {"type": "string", "minLength": 1},
                            "created_at": {"type": "string", "minLength": 1},
                        },
                        "required": ["item_id", "item_kind", "title", "created_at"],
                        "additionalProperties": False,
                    },
                },
                "next_offset": {"type": "integer", "minimum": 0},
            },
            "required": ["items", "next_offset"],
            "additionalProperties": False,
        },
        effect=ToolEffect.READ,
        risk=ToolRisk.LOW,
        skill_ids=("research",),
    )
    build_brief_definition = ToolDefinition(
        name=BUILD_BRIEF_DRAFT_TOOL,
        description="Build a temporary Chinese source-linked brief from a ranked item set.",
        input_schema={
            "type": "object",
            "properties": {
                "item_set_id": {"type": "string", "minLength": 1},
                "title": {"type": "string", "minLength": 1, "maxLength": 200},
            },
            "required": ["item_set_id", "title"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "draft_id": {"type": "string", "minLength": 1},
                "title": {"type": "string", "minLength": 1},
                "body": {"type": "string", "minLength": 1},
                "source_urls": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string", "minLength": 1},
                },
                "provenance": {"type": "string", "minLength": 1},
            },
            "required": ["draft_id", "title", "body", "source_urls", "provenance"],
            "additionalProperties": False,
        },
        effect=ToolEffect.READ,
        risk=ToolRisk.LOW,
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

    def fetch_briefing_handler(call: ToolCall) -> ToolResult:
        try:
            document = service.fetch_content(str(call.arguments["source_key"]))
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=ToolCallStatus.SUCCEEDED,
                output={
                    field_name: getattr(document, field_name)
                    for field_name in (
                        "document_id",
                        "observation_id",
                        "source_key",
                        "title",
                        "url",
                        "content_hash",
                        "fetched_at",
                        "provenance",
                    )
                },
            )
        except (AppError, ValueError, KeyError, RuntimeError) as exc:
            return _failed(call, exc)

    def parse_handler(call: ToolCall) -> ToolResult:
        try:
            item_set = service.parse_items(
                str(call.arguments["document_id"]), limit=int(call.arguments["limit"])
            )
            return _item_set_result(call, item_set)
        except (AppError, ValueError, KeyError) as exc:
            return _failed(call, exc)

    def save_brief_handler(call: ToolCall) -> ToolResult:
        try:
            brief = service.save_brief(str(call.arguments["draft_id"]))
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=ToolCallStatus.SUCCEEDED,
                output={"brief_id": brief.brief_id, "title": brief.title},
                evidence=(
                    ExecutionEvidence(
                        evidence_type="research_brief_saved",
                        summary="One Research brief was persisted.",
                        reference=f"research-brief:{brief.brief_id}",
                    ),
                ),
            )
        except (AppError, ValueError, KeyError) as exc:
            return _failed(call, exc)

    def create_note_handler(call: ToolCall) -> ToolResult:
        try:
            note = service.create_note(
                str(call.arguments["title"]), str(call.arguments["body"])
            )
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=ToolCallStatus.SUCCEEDED,
                output={"note_id": note.note_id, "title": note.title},
                evidence=(
                    ExecutionEvidence(
                        evidence_type="research_note_created",
                        summary="One Research note was persisted.",
                        reference=f"research-note:{note.note_id}",
                    ),
                ),
            )
        except (AppError, ValueError, KeyError) as exc:
            return _failed(call, exc)

    def rank_handler(call: ToolCall) -> ToolResult:
        try:
            item_set = service.rank_items(
                str(call.arguments["item_set_id"]),
                limit=int(call.arguments["limit"]),
                topic_filter=(
                    str(call.arguments["topic_filter"])
                    if "topic_filter" in call.arguments
                    else None
                ),
            )
            return _item_set_result(call, item_set)
        except (AppError, ValueError, KeyError) as exc:
            return _failed(call, exc)

    def search_handler(call: ToolCall) -> ToolResult:
        try:
            item_kinds = tuple(str(value) for value in call.arguments["item_kinds"])
            limit = int(call.arguments["limit"])
            offset = int(call.arguments["offset"])
            items = service.search_saved_items(
                str(call.arguments["query"]),
                item_kinds,
                limit=limit,
                offset=offset,
            )
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=ToolCallStatus.SUCCEEDED,
                output={
                    "items": [
                        {
                            "item_id": item.item_id,
                            "item_kind": item.item_kind,
                            "title": item.title,
                            "created_at": item.created_at,
                        }
                        for item in items
                    ],
                    "next_offset": offset + len(items),
                },
            )
        except (AppError, ValueError, KeyError, TypeError) as exc:
            return _failed(call, exc)

    def build_brief_handler(call: ToolCall) -> ToolResult:
        try:
            draft = service.build_brief_draft(
                str(call.arguments["item_set_id"]), str(call.arguments["title"])
            )
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=ToolCallStatus.SUCCEEDED,
                output={
                    "draft_id": draft.draft_id,
                    "title": draft.title,
                    "body": draft.body,
                    "source_urls": list(draft.source_urls),
                    "provenance": draft.provenance,
                },
            )
        except (AppError, ValueError, KeyError) as exc:
            return _failed(call, exc)

    return (
        (fetch_definition, fetch_handler),
        (fetch_briefing_definition, fetch_briefing_handler),
        (parse_definition, parse_handler),
        (rank_definition, rank_handler),
        (search_definition, search_handler),
        (build_brief_definition, build_brief_handler),
        (save_definition, save_handler),
        (save_brief_definition, save_brief_handler),
        (create_note_definition, create_note_handler),
    )


def _item_set_result(call: ToolCall, item_set: ResearchItemSet) -> ToolResult:
    return ToolResult(
        call_id=call.call_id,
        tool_name=call.tool_name,
        status=ToolCallStatus.SUCCEEDED,
        output={
            "item_set_id": item_set.item_set_id,
            "items": [
                {
                    "item_id": item.item_id,
                    "source_key": item.source_key,
                    "title": item.title,
                    "url": item.url,
                    "raw_position": item.raw_position,
                    "topic_hint": item.topic_hint or "other",
                    "score": item.score or 0,
                }
                for item in item_set.items
            ],
        },
    )


def _failed(call: ToolCall, error: Exception) -> ToolResult:
    code = getattr(error, "code", "research_tool_failed")
    return ToolResult(
        call_id=call.call_id,
        tool_name=call.tool_name,
        status=ToolCallStatus.FAILED,
        error=ToolError(code, "Research Tool could not complete the operation."),
    )
