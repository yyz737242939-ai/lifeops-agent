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


BUILD_BRIEF_TOOL = "research.build_brief"
SEARCH_PAPERS_TOOL = "research.search_papers"
SAVE_SOURCE_TOOL = "research.save_source"
SAVE_BRIEF_TOOL = "research.save_brief"
CREATE_NOTE_TOOL = "research.create_note"
CREATE_TOPIC_TOOL = "research.create_topic"
LINK_ITEMS_TOOL = "research.link_items"
APPEND_REVISION_TOOL = "research.append_revision"
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
    "paper_id": {"type": "string", "minLength": 1, "maxLength": 200},
    "authors": {
        "type": "array",
        "maxItems": 20,
        "items": {"type": "string", "minLength": 1, "maxLength": 120},
    },
}

def build_research_tools(
    service: ResearchService,
) -> tuple[tuple[ToolDefinition, ToolHandler], ...]:
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
    search_papers_definition = ToolDefinition(
        name=SEARCH_PAPERS_TOOL,
        description=(
            "Search public Hugging Face papers through the local MCP adapter and "
            "return temporary observations."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 200},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 5,
                },
            },
            "required": ["query", "limit"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "observations": {
                    "type": "array",
                    "maxItems": 10,
                    "items": {
                        "type": "object",
                        "properties": {
                            **_OBSERVATION_PROPERTIES,
                            "published_at": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 64,
                            },
                        },
                        "required": list(_OBSERVATION_PROPERTIES),
                        "additionalProperties": False,
                    },
                },
                "invalid_count": {"type": "integer", "minimum": 0, "maximum": 10},
            },
            "required": ["observations", "invalid_count"],
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
    create_topic_definition = ToolDefinition(
        name=CREATE_TOPIC_TOOL,
        description="Create one explicitly confirmed Research topic.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "minLength": 1, "maxLength": 200},
                "description": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 4000,
                },
            },
            "required": ["name", "description"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "string", "minLength": 1},
                "name": {"type": "string", "minLength": 1},
            },
            "required": ["topic_id", "name"],
            "additionalProperties": False,
        },
        effect=ToolEffect.WRITE,
        risk=ToolRisk.MEDIUM,
        skill_ids=("research",),
    )
    item_kind_schema = {
        "type": "string",
        "enum": ["topic", "source", "note", "brief"],
    }
    link_items_definition = ToolDefinition(
        name=LINK_ITEMS_TOOL,
        description="Create one explicitly confirmed relationship between saved Research items.",
        input_schema={
            "type": "object",
            "properties": {
                "from_kind": item_kind_schema,
                "from_id": {"type": "string", "minLength": 1},
                "to_kind": item_kind_schema,
                "to_id": {"type": "string", "minLength": 1},
                "relation": {"type": "string", "minLength": 1, "maxLength": 100},
            },
            "required": ["from_kind", "from_id", "to_kind", "to_id", "relation"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "link_id": {"type": "string", "minLength": 1},
                "from_id": {"type": "string", "minLength": 1},
                "to_id": {"type": "string", "minLength": 1},
                "relation": {"type": "string", "minLength": 1},
            },
            "required": ["link_id", "from_id", "to_id", "relation"],
            "additionalProperties": False,
        },
        effect=ToolEffect.WRITE,
        risk=ToolRisk.MEDIUM,
        skill_ids=("research",),
    )
    append_revision_definition = ToolDefinition(
        name=APPEND_REVISION_TOOL,
        description="Append one explicitly confirmed immutable revision to a saved Research item.",
        input_schema={
            "type": "object",
            "properties": {
                "item_kind": item_kind_schema,
                "item_id": {"type": "string", "minLength": 1},
                "content": {"type": "string", "minLength": 1, "maxLength": 12000},
            },
            "required": ["item_kind", "item_id", "content"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "revision_id": {"type": "string", "minLength": 1},
                "version": {"type": "integer", "minimum": 1},
            },
            "required": ["revision_id", "version"],
            "additionalProperties": False,
        },
        effect=ToolEffect.WRITE,
        risk=ToolRisk.MEDIUM,
        skill_ids=("research",),
    )
    search_definition = ToolDefinition(
        name=SEARCH_KNOWLEDGE_TOOL,
        description=(
            "Search saved Research sources, notes, and briefs, or list/filter "
            "Research topics when query is omitted."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1},
                "topic_filter": {"type": "string", "minLength": 1, "maxLength": 200},
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
            "required": ["limit", "offset"],
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
                                "enum": ["topic", "source", "note", "brief"],
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
        name=BUILD_BRIEF_TOOL,
        description=(
            "Fetch declared Hugging Face list pages and build one temporary, "
            "source-linked Research brief."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "source_keys": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 2,
                    "items": {
                        "type": "string",
                        "enum": ["hf_daily_papers", "hf_blog"],
                    },
                },
                "topic_filter": {"type": "string", "minLength": 1, "maxLength": 100},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 10,
                },
            },
            "required": ["source_keys", "limit"],
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
                "source_observation_ids": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 2,
                    "items": {"type": "string", "minLength": 1},
                },
                "item_count": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": [
                "draft_id",
                "title",
                "body",
                "source_urls",
                "provenance",
                "source_observation_ids",
                "item_count",
            ],
            "additionalProperties": False,
        },
        effect=ToolEffect.EXTERNAL_READ,
        risk=ToolRisk.LOW,
        skill_ids=("research",),
    )

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

    def search_papers_handler(call: ToolCall) -> ToolResult:
        try:
            result = service.search_papers(
                str(call.arguments["query"]),
                limit=int(call.arguments["limit"]),
            )
            output_observations = []
            for observation in result.observations:
                paper = {
                    "observation_id": observation.observation_id,
                    "source_key": observation.source_key,
                    "title": observation.title,
                    "url": observation.url,
                    "summary": observation.summary,
                    "content_hash": observation.content_hash,
                    "fetched_at": observation.fetched_at,
                    "provenance": observation.provenance,
                    "paper_id": observation.external_id,
                    "authors": list(observation.authors),
                }
                if observation.published_at is not None:
                    paper["published_at"] = observation.published_at
                output_observations.append(paper)
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=ToolCallStatus.SUCCEEDED,
                output={
                    "observations": output_observations,
                    "invalid_count": result.invalid_count,
                },
            )
        except (AppError, ValueError, KeyError, RuntimeError) as exc:
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

    def create_topic_handler(call: ToolCall) -> ToolResult:
        try:
            topic = service.create_topic(
                str(call.arguments["name"]),
                str(call.arguments["description"]),
            )
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=ToolCallStatus.SUCCEEDED,
                output={"topic_id": topic.topic_id, "name": topic.name},
                evidence=(
                    ExecutionEvidence(
                        evidence_type="research_topic_created",
                        summary="One Research topic was persisted.",
                        reference=f"research-topic:{topic.topic_id}",
                    ),
                ),
            )
        except (AppError, ValueError, KeyError) as exc:
            return _failed(call, exc)

    def link_items_handler(call: ToolCall) -> ToolResult:
        try:
            link = service.link_items(
                str(call.arguments["from_kind"]),
                str(call.arguments["from_id"]),
                str(call.arguments["to_kind"]),
                str(call.arguments["to_id"]),
                str(call.arguments["relation"]),
            )
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=ToolCallStatus.SUCCEEDED,
                output={
                    "link_id": link.link_id,
                    "from_id": link.from_id,
                    "to_id": link.to_id,
                    "relation": link.relation,
                },
                evidence=(
                    ExecutionEvidence(
                        evidence_type="research_items_linked",
                        summary="One Research relationship was persisted.",
                        reference=f"research-link:{link.link_id}",
                    ),
                ),
            )
        except (AppError, ValueError, KeyError) as exc:
            return _failed(call, exc)

    def append_revision_handler(call: ToolCall) -> ToolResult:
        try:
            revision = service.append_revision(
                str(call.arguments["item_kind"]),
                str(call.arguments["item_id"]),
                str(call.arguments["content"]),
            )
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=ToolCallStatus.SUCCEEDED,
                output={
                    "revision_id": revision.revision_id,
                    "version": revision.version,
                },
                evidence=(
                    ExecutionEvidence(
                        evidence_type="research_revision_appended",
                        summary="One immutable Research revision was persisted.",
                        reference=f"research-revision:{revision.revision_id}",
                    ),
                ),
            )
        except (AppError, ValueError, KeyError) as exc:
            return _failed(call, exc)

    def search_handler(call: ToolCall) -> ToolResult:
        try:
            limit = int(call.arguments["limit"])
            offset = int(call.arguments["offset"])
            if "query" in call.arguments:
                if "item_kinds" not in call.arguments:
                    raise ValueError("item_kinds is required when query is present.")
                item_kinds = tuple(
                    str(value) for value in call.arguments["item_kinds"]
                )
                saved_items = service.search_saved_items(
                    str(call.arguments["query"]),
                    item_kinds,
                    limit=limit,
                    offset=offset,
                )
                output_items = [
                    {
                        "item_id": item.item_id,
                        "item_kind": item.item_kind,
                        "title": item.title,
                        "created_at": item.created_at,
                    }
                    for item in saved_items
                ]
            else:
                if "item_kinds" in call.arguments:
                    raise ValueError("item_kinds is only valid with query.")
                topics = service.list_topics(
                    limit=limit,
                    offset=offset,
                    filter_text=(
                        str(call.arguments["topic_filter"])
                        if "topic_filter" in call.arguments
                        else None
                    ),
                )
                output_items = [
                    {
                        "item_id": topic.topic_id,
                        "item_kind": "topic",
                        "title": topic.name,
                        "created_at": topic.created_at,
                    }
                    for topic in topics
                ]
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                status=ToolCallStatus.SUCCEEDED,
                output={
                    "items": output_items,
                    "next_offset": offset + len(output_items),
                },
            )
        except (AppError, ValueError, KeyError, TypeError) as exc:
            return _failed(call, exc)

    def build_brief_handler(call: ToolCall) -> ToolResult:
        try:
            result = service.build_brief(
                tuple(str(value) for value in call.arguments["source_keys"]),
                limit=int(call.arguments["limit"]),
                topic_filter=(
                    str(call.arguments["topic_filter"])
                    if "topic_filter" in call.arguments
                    else None
                ),
            )
            draft = result.draft
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
                    "source_observation_ids": list(
                        result.source_observation_ids
                    ),
                    "item_count": result.item_count,
                },
            )
        except (AppError, ValueError, KeyError, RuntimeError, TypeError) as exc:
            return _failed(call, exc)

    return (
        (search_papers_definition, search_papers_handler),
        (search_definition, search_handler),
        (build_brief_definition, build_brief_handler),
        (save_definition, save_handler),
        (save_brief_definition, save_brief_handler),
        (create_note_definition, create_note_handler),
        (create_topic_definition, create_topic_handler),
        (link_items_definition, link_items_handler),
        (append_revision_definition, append_revision_handler),
    )


def _failed(call: ToolCall, error: Exception) -> ToolResult:
    code = getattr(error, "code", "research_tool_failed")
    return ToolResult(
        call_id=call.call_id,
        tool_name=call.tool_name,
        status=ToolCallStatus.FAILED,
        error=ToolError(code, "Research Tool could not complete the operation."),
    )
