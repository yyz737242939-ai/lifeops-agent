from typing import Any

from app.observability.session import append_log_record


class LLMIOLogger:
    """Record only complete request/response traffic at the LLM boundary."""

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
                "loop": loop,
                "attempt": attempt,
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
                "loop": loop,
                "attempt": run_state.llm_attempts,
                "response": response,
            },
        )

llm_io = LLMIOLogger()
