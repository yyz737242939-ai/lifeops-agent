from typing import Any

from app.observability.session import append_log_record
from app.utils.serialization import json_safe


_RESPONSE_LOG_FIELDS = (
    "id",
    "model",
    "status",
    "created_at",
    "completed_at",
    "output_text",
    "output",
    "usage",
    "error",
    "incomplete_details",
)


def compact_response_for_log(response: Any) -> dict[str, Any]:
    """Keep response-only diagnostics and omit request fields echoed by the SDK."""
    serialized = json_safe(response)
    source = serialized if isinstance(serialized, dict) else {}
    compact: dict[str, Any] = {}

    for field_name in _RESPONSE_LOG_FIELDS:
        value = source.get(field_name)
        if field_name not in source:
            try:
                value = json_safe(getattr(response, field_name))
            except (AttributeError, TypeError, ValueError):
                continue
        if value is not None:
            compact[field_name] = value

    return compact


class LLMIOLogger:
    """Record requests and compact diagnostic responses at the LLM boundary."""

    def log_request(
        self,
        run_state: Any,
        loop: int,
        attempt: int,
        *,
        model: str,
        instructions: str,
        tools: Any,
        input_messages: Any,
        parameters: dict[str, Any],
    ) -> None:
        append_log_record(
            "llm",
            "llm.request",
            {
                "run_id": run_state.run_id,
                "chat_llm_round_number": loop,
                "chat_llm_request_number": attempt,
                "model": model,
                "instructions": instructions,
                "tools": tools,
                "input": input_messages,
                "parameters": parameters,
            },
        )

    def log_response(self, run_state: Any, loop: int, response: Any) -> None:
        append_log_record(
            "llm",
            "llm.response",
            {
                "run_id": run_state.run_id,
                "chat_llm_round_number": loop,
                "chat_llm_request_number": run_state.chat_llm_request_count,
                "response_log_format": "diagnostic_projection_v1",
                "response": compact_response_for_log(response),
            },
        )

llm_io = LLMIOLogger()
