"""Request-local context assembly for one model call."""

import json
from dataclasses import dataclass
from typing import Any

from app.context.context_manager import summarize_context_messages
from app.memory.memory_context import (
    profile_context_message,
    profile_context_report,
    semantic_memory_context_message,
)
from app.utils.serialization import json_safe


@dataclass(frozen=True)
class RequestLocalContext:
    """Prepared model input plus diagnostics for request-local providers."""

    input_messages: list[Any]
    context_engine_report: dict[str, Any]
    memory_report: dict[str, Any]
    task_report: dict[str, Any]
    recovery_report: dict[str, Any]
    diagnostics: dict[str, Any]

    def log_parameters(self) -> dict[str, Any]:
        return {
            "context_engine": self.context_engine_report,
            "memory": self.memory_report,
            "task_context": self.task_report,
            "recovery_context": self.recovery_report,
        }


class RequestLocalContextBuilder:
    """Build the fixed request-local context provider order for Agent calls."""

    def __init__(
        self,
        *,
        context_engine: Any,
        profile_loader: Any,
        memory_retriever: Any,
        task_context_builder: Any,
        recovery_context_builder: Any,
    ) -> None:
        self.context_engine = context_engine
        self.profile_loader = profile_loader
        self.memory_retriever = memory_retriever
        self.task_context_builder = task_context_builder
        self.recovery_context_builder = recovery_context_builder

    def build(
        self,
        *,
        messages: list[Any],
        instructions: str,
        tool_schemas: tuple[dict[str, Any], ...],
        user_input: str,
    ) -> RequestLocalContext:
        assembly = self.context_engine.assemble(
            messages,
            instructions=instructions,
            tools=tool_schemas,
        )
        profile = self.profile_loader.load()
        profile_message = profile_context_message(profile)
        semantic_memories = self.memory_retriever.retrieve(user_input)
        semantic_message = semantic_memory_context_message(semantic_memories)
        task_context = self.task_context_builder.build(user_input)
        task_message = task_context.message()
        recovery_context = self.recovery_context_builder.build(
            user_input,
            task_context=task_context,
        )
        recovery_message = recovery_context.message()

        input_messages = list(assembly.input_messages)
        request_local_messages = [
            profile_message,
            semantic_message,
            task_message,
            recovery_message,
        ]
        for insert_index, message in enumerate(
            message for message in request_local_messages if message is not None
        ):
            input_messages.insert(insert_index, message)

        memory_report = profile_context_report(
            profile,
            profile_message,
            semantic_memories,
            semantic_message,
        )
        task_report = task_context.report(task_message)
        recovery_report = recovery_context.report(recovery_message)
        diagnostics = _llm_input_diagnostics(input_messages)
        diagnostics["context_engine"] = assembly.report
        diagnostics["memory"] = memory_report
        diagnostics["task_context"] = task_report
        diagnostics["recovery_context"] = recovery_report

        return RequestLocalContext(
            input_messages=input_messages,
            context_engine_report=assembly.report,
            memory_report=memory_report,
            task_report=task_report,
            recovery_report=recovery_report,
            diagnostics=diagnostics,
        )


def _preview_text(value: Any, max_length: int = 240) -> str:
    text = "" if value is None else str(value)
    if len(text) <= max_length:
        return text
    return f"{text[:max_length]}..."


def _message_summary(message: Any) -> dict[str, Any]:
    serialized = json_safe(message)
    if isinstance(serialized, dict):
        content = serialized.get("content")
        if content is None:
            content = serialized.get("output")
        return {
            "role": serialized.get("role"),
            "type": serialized.get("type", "message"),
            "call_id": serialized.get("call_id"),
            "name": serialized.get("name"),
            "content_preview": _preview_text(content),
        }

    return {
        "role": None,
        "type": type(message).__name__,
        "content_preview": _preview_text(serialized),
    }


def _llm_input_diagnostics(messages: list[Any]) -> dict[str, Any]:
    serialized = json_safe(messages)
    summary = {
        "message_count": len(messages),
        "approx_json_chars": len(json.dumps(serialized, ensure_ascii=False)),
        "messages": [_message_summary(message) for message in messages],
    }
    summary["context_budget"] = summarize_context_messages(serialized)
    return summary

