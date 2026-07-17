"""Memory Tool contracts and handlers; all behavior delegates to MemoryService."""

from __future__ import annotations

from collections.abc import Callable

from app.memory.errors import MemoryError
from app.memory.models import MemoryEntry, MemoryWriteContext, decode_memory_tags
from app.memory.service import MemoryConflictError, MemoryService
from app.observability.logger import TraceSink
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


SAVE_MEMORY_TOOL = "memory.save"
SEARCH_MEMORY_TOOL = "memory.search"
LIST_MEMORY_TOOL = "memory.list"
UPDATE_MEMORY_TOOL = "memory.update"
ARCHIVE_MEMORY_TOOL = "memory.archive"

MemoryWriteContextFactory = Callable[[ToolCall], MemoryWriteContext]

_TAGS_SCHEMA = {
    "type": "array",
    "maxItems": 20,
    "items": {"type": "string", "minLength": 1, "maxLength": 100},
}
_MANAGEMENT_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "memory_id": {"type": "string", "minLength": 1},
        "version": {"type": "integer", "minimum": 1},
        "status": {"type": "string", "enum": ["active", "superseded", "archived"]},
        "tags": _TAGS_SCHEMA,
        "preview": {"type": "string", "minLength": 1, "maxLength": 240},
    },
    "required": ["memory_id", "version", "status", "tags", "preview"],
    "additionalProperties": False,
}


def build_memory_tools(
    service: MemoryService,
    write_context_factory: MemoryWriteContextFactory,
    *,
    event_sink: TraceSink | None = None,
) -> tuple[tuple[ToolDefinition, ToolHandler], ...]:
    if not callable(write_context_factory):
        raise ValueError("write_context_factory must be callable.")
    definitions = _definitions()

    def save_handler(call: ToolCall) -> ToolResult:
        try:
            write_context = write_context_factory(call)
            result = service.save_confirmed(
                str(call.arguments["content"]),
                _tags(call),
                write_context,
            )
            record = result.entry.record
            return _success_write(
                call,
                {
                    "memory_id": record.memory_id,
                    "version": record.version,
                    "status": record.status.value,
                    "idempotent_existing": result.idempotent_existing,
                },
                "memory_saved",
                "One confirmed Memory version is committed.",
                record.memory_id,
                record.version,
                (
                    record.evidence_ref
                    if result.idempotent_existing
                    else write_context.evidence_ref
                ),
            )
        except MemoryConflictError as exc:
            return ToolResult(
                call.call_id,
                call.tool_name,
                ToolCallStatus.FAILED,
                output={
                    "conflict_candidates": [
                        {
                            "memory_id": item.memory_id,
                            "version": item.version,
                            "reason": item.reason,
                            "content": item.content,
                            "tags": list(item.tags),
                        }
                        for item in exc.candidates
                    ]
                },
                error=ToolError(exc.code, "Memory conflicts with an active candidate."),
            )
        except (MemoryError, ValueError, KeyError, TypeError) as exc:
            return _failed(call, exc)

    def search_handler(call: ToolCall) -> ToolResult:
        try:
            entries = service.search(
                str(call.arguments["query"]),
                int(call.arguments.get("limit", 5)),
            )
            return ToolResult(
                call.call_id,
                call.tool_name,
                ToolCallStatus.SUCCEEDED,
                output={"items": [_search_item(entry) for entry in entries]},
            )
        except (MemoryError, ValueError, KeyError, TypeError) as exc:
            return _failed(call, exc)

    def list_handler(call: ToolCall) -> ToolResult:
        try:
            mode = str(call.arguments.get("mode", "active"))
            limit = int(call.arguments.get("limit", 20))
            if mode == "active":
                entries = service.list_active()
            elif mode == "archived":
                entries = service.list_archived()
            elif mode == "history":
                memory_id = str(call.arguments["memory_id"])
                entries = service.list_history(memory_id)
            else:
                raise ValueError("mode is invalid.")
            return ToolResult(
                call.call_id,
                call.tool_name,
                ToolCallStatus.SUCCEEDED,
                output={"items": [_management_item(item) for item in entries[:limit]]},
            )
        except (MemoryError, ValueError, KeyError, TypeError) as exc:
            return _failed(call, exc)

    def update_handler(call: ToolCall) -> ToolResult:
        try:
            write_context = write_context_factory(call)
            result = service.update_confirmed(
                str(call.arguments["memory_id"]),
                int(call.arguments["expected_version"]),
                str(call.arguments["content"]),
                _tags(call),
                write_context,
            )
            record = result.entry.record
            return _success_write(
                call,
                {
                    "memory_id": record.memory_id,
                    "version": record.version,
                    "status": record.status.value,
                    "idempotent_existing": result.idempotent_existing,
                },
                "memory_updated",
                "One confirmed Memory update is committed.",
                record.memory_id,
                record.version,
                (
                    record.evidence_ref
                    if result.idempotent_existing
                    else write_context.evidence_ref
                ),
            )
        except MemoryConflictError as exc:
            return ToolResult(
                call.call_id,
                call.tool_name,
                ToolCallStatus.FAILED,
                output={"conflict_candidates": [_conflict_item(item) for item in exc.candidates]},
                error=ToolError(exc.code, "Memory update conflicts with another active candidate."),
            )
        except (MemoryError, ValueError, KeyError, TypeError) as exc:
            return _failed(call, exc)

    def archive_handler(call: ToolCall) -> ToolResult:
        try:
            write_context = write_context_factory(call)
            record = service.archive_confirmed(
                str(call.arguments["memory_id"]),
                int(call.arguments["expected_version"]),
                write_context,
            )
            return _success_write(
                call,
                {"memory_id": record.memory_id, "version": record.version, "status": record.status.value},
                "memory_archived",
                "One confirmed Memory version is archived.",
                record.memory_id,
                record.version,
                write_context.evidence_ref,
            )
        except (MemoryError, ValueError, KeyError, TypeError) as exc:
            return _failed(call, exc)

    handlers = {
        SAVE_MEMORY_TOOL: save_handler,
        SEARCH_MEMORY_TOOL: search_handler,
        LIST_MEMORY_TOOL: list_handler,
        UPDATE_MEMORY_TOOL: update_handler,
        ARCHIVE_MEMORY_TOOL: archive_handler,
    }
    return tuple(
        (
            definition,
            _observed_handler(handlers[definition.name], event_sink),
        )
        for definition in definitions
    )


def _definitions() -> tuple[ToolDefinition, ...]:
    write_output = {
        "type": "object",
        "properties": {
            "memory_id": {"type": "string", "minLength": 1},
            "version": {"type": "integer", "minimum": 1},
            "status": {"type": "string", "enum": ["active", "archived"]},
            "idempotent_existing": {"type": "boolean"},
        },
        "required": ["memory_id", "version", "status", "idempotent_existing"],
        "additionalProperties": False,
    }
    return (
        ToolDefinition(
            SAVE_MEMORY_TOOL,
            "Save one explicit user-confirmed global Memory, at most once per user request. "
            "Never infer a save. If this Tool reports a conflict, do not call memory.save "
            "again in the same request; return the candidate ID/version to the user.",
            _content_input(),
            write_output,
            ToolEffect.WRITE,
            ToolRisk.MEDIUM,
            ("memory",),
            max_calls_per_run=1,
        ),
        ToolDefinition(
            SEARCH_MEMORY_TOOL,
            "Search verified active explicit Memory with deterministic local matching.",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 1, "maxLength": 500},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "maxItems": 10,
                        "items": {
                            "type": "object",
                            "properties": {
                                "memory_id": {"type": "string", "minLength": 1},
                                "version": {"type": "integer", "minimum": 1},
                                "content": {"type": "string", "minLength": 1, "maxLength": 12000},
                                "tags": _TAGS_SCHEMA,
                            },
                            "required": ["memory_id", "version", "content", "tags"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["items"],
                "additionalProperties": False,
            },
            ToolEffect.READ,
            ToolRisk.LOW,
            ("memory",),
        ),
        ToolDefinition(
            LIST_MEMORY_TOOL,
            "List active or archived Memory metadata, or version history for one ID.",
            {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["active", "archived", "history"], "default": "active"},
                    "memory_id": {"type": "string", "minLength": 1},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
                },
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {"items": {"type": "array", "maxItems": 50, "items": _MANAGEMENT_ITEM_SCHEMA}},
                "required": ["items"],
                "additionalProperties": False,
            },
            ToolEffect.READ,
            ToolRisk.LOW,
            ("memory",),
        ),
        ToolDefinition(
            UPDATE_MEMORY_TOOL,
            "Create a confirmed immutable version replacing one expected active Memory version.",
            {
                **_content_input(),
                "properties": {
                    "memory_id": {"type": "string", "minLength": 1},
                    "expected_version": {"type": "integer", "minimum": 1},
                    **_content_input()["properties"],
                },
                "required": ["memory_id", "expected_version", "content"],
            },
            write_output,
            ToolEffect.WRITE,
            ToolRisk.MEDIUM,
            ("memory",),
        ),
        ToolDefinition(
            ARCHIVE_MEMORY_TOOL,
            "Archive one expected active Memory version without deleting its immutable file.",
            {
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string", "minLength": 1},
                    "expected_version": {"type": "integer", "minimum": 1},
                },
                "required": ["memory_id", "expected_version"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string", "minLength": 1},
                    "version": {"type": "integer", "minimum": 1},
                    "status": {"type": "string", "enum": ["archived"]},
                },
                "required": ["memory_id", "version", "status"],
                "additionalProperties": False,
            },
            ToolEffect.WRITE,
            ToolRisk.MEDIUM,
            ("memory",),
        ),
    )


def _content_input() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "content": {"type": "string", "minLength": 1, "maxLength": 12000},
            "tags": _TAGS_SCHEMA,
        },
        "required": ["content"],
        "additionalProperties": False,
    }


def _tags(call: ToolCall) -> tuple[str, ...]:
    return tuple(str(value) for value in call.arguments.get("tags", ()))


def _search_item(entry: MemoryEntry) -> dict[str, object]:
    return {
        "memory_id": entry.record.memory_id,
        "version": entry.record.version,
        "content": entry.document.content,
        "tags": list(decode_memory_tags(entry.record.tags_json)),
    }


def _management_item(entry: MemoryEntry) -> dict[str, object]:
    preview = " ".join(entry.document.content.split())[:240]
    return {
        "memory_id": entry.record.memory_id,
        "version": entry.record.version,
        "status": entry.record.status.value,
        "tags": list(decode_memory_tags(entry.record.tags_json)),
        "preview": preview,
    }


def _conflict_item(item) -> dict[str, object]:
    return {
        "memory_id": item.memory_id,
        "version": item.version,
        "reason": item.reason,
        "content": item.content,
        "tags": list(item.tags),
    }


def _success_write(
    call: ToolCall,
    output: dict[str, object],
    evidence_type: str,
    summary: str,
    memory_id: str,
    version: int,
    evidence_reference: str,
) -> ToolResult:
    return ToolResult(
        call.call_id,
        call.tool_name,
        ToolCallStatus.SUCCEEDED,
        output=output,
        evidence=(ExecutionEvidence(evidence_type, summary, evidence_reference),),
    )


def _failed(call: ToolCall, error: Exception) -> ToolResult:
    return ToolResult(
        call.call_id,
        call.tool_name,
        ToolCallStatus.FAILED,
        error=ToolError(getattr(error, "code", "memory_invalid"), "Memory Tool could not complete the operation."),
    )


def _observed_handler(
    handler: ToolHandler,
    event_sink: TraceSink | None,
) -> ToolHandler:
    def observed(call: ToolCall) -> ToolResult:
        result = handler(call)
        if event_sink is not None:
            payload: dict[str, object] = {
                "tool_name": result.tool_name,
                "call_id": result.call_id,
                "status": result.status.value,
                "evidence_count": len(result.evidence),
            }
            if result.output is not None:
                for key in ("memory_id", "version", "idempotent_existing"):
                    if key in result.output:
                        payload[key] = result.output[key]
            if result.error is not None:
                payload["error_code"] = result.error.code
            event_sink.append(
                (
                    "memory.tool.completed"
                    if result.status == ToolCallStatus.SUCCEEDED
                    else "memory.tool.failed"
                ),
                payload,
            )
        return result

    return observed
