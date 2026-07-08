import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any

from app.runtime.errors import classify_tool_exception, normalize_tool_result
from app.tools.registry import ToolDefinition, ToolEffect, ToolResult
from app.utils.serialization import json_safe


_TOOL_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="lifeops-tool")
LoadIdempotentResult = Callable[[str], dict[str, Any] | None]
SaveIdempotentResult = Callable[[str, dict[str, Any]], None]


def execute_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    tools: dict[str, ToolDefinition],
    allowed_tool_names: frozenset[str],
    idempotency_key: str | None,
    load_idempotent_result: LoadIdempotentResult,
    save_idempotent_result: SaveIdempotentResult,
) -> str:
    """Authorize and execute one tool with timeout and idempotency handling."""
    tool = tools.get(name)
    if tool is None:
        return _serialize_result(
            normalize_tool_result(
                name,
                {"ok": False, "action": name, "error": "tool_not_found"},
            )
        )
    if name not in allowed_tool_names:
        return _serialize_result(
            normalize_tool_result(
                name,
                {
                    "ok": False,
                    "action": name,
                    "error": "tool_not_allowed",
                    "allowed_tools": [
                        tool_name
                        for tool_name in tools
                        if tool_name in allowed_tool_names
                    ],
                },
            )
        )

    cached = _load_cached_write(tool, idempotency_key, load_idempotent_result)
    if cached is not None:
        return _serialize_result(cached)

    result = _execute_with_timeout(tool, name, arguments)
    normalized = normalize_tool_result(name, result)
    stored = _store_successful_write(
        tool,
        normalized,
        idempotency_key,
        save_idempotent_result,
    )
    return _serialize_result(stored)


def _load_cached_write(
    tool: ToolDefinition,
    idempotency_key: str | None,
    load_result: LoadIdempotentResult,
) -> dict[str, Any] | None:
    if tool.effect != ToolEffect.WRITE or not idempotency_key:
        return None
    cached = load_result(idempotency_key)
    if cached is None:
        return None
    replayed = dict(cached)
    replayed["idempotency"] = {"key": idempotency_key, "replayed": True}
    return replayed


def _execute_with_timeout(
    tool: ToolDefinition,
    name: str,
    arguments: dict[str, Any],
) -> ToolResult:
    try:
        future = _TOOL_EXECUTOR.submit(tool.function, **arguments)
        return future.result(timeout=tool.timeout_seconds)
    except FutureTimeoutError:
        future.cancel()
        return classify_tool_exception(
            name,
            TimeoutError(f"{name} exceeded {tool.timeout_seconds} seconds"),
        )
    except Exception as error:
        return classify_tool_exception(name, error)


def _store_successful_write(
    tool: ToolDefinition,
    result: ToolResult,
    idempotency_key: str | None,
    save_result: SaveIdempotentResult,
) -> ToolResult:
    if (
        tool.effect != ToolEffect.WRITE
        or not idempotency_key
        or result.get("ok") is not True
    ):
        return result
    stored = dict(result)
    stored["idempotency"] = {"key": idempotency_key, "replayed": False}
    save_result(idempotency_key, stored)
    return stored


def _serialize_result(result: ToolResult) -> str:
    return json.dumps(json_safe(result), ensure_ascii=False)
