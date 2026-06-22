import json
from typing import Any

from app.config import (
    LLM_MAX_OUTPUT_TOKENS,
    LLM_MODEL,
    LLM_TEMPERATURE,
)
from app.prompts.prompt_builder import build_system_prompt
from app.runtime.context_manager import (
    compact_tool_output,
    summarize_context_messages,
)
from app.runtime.conversation_logger import log_event, log_raw_event
from app.skills.skill_loader import discover_skills
from app.tools.tool import call_tool
from app.tools.tool_schema import TOOL_SCHEMAS
from app.utils.llm import client


MAX_TOOL_CALL_LOOPS = 3


def _serialize_output(output: Any) -> Any:
    if hasattr(output, "model_dump"):
        return _serialize_output(output.model_dump())
    if isinstance(output, list):
        return [_serialize_output(item) for item in output]
    if isinstance(output, dict):
        return {key: _serialize_output(value) for key, value in output.items()}
    if isinstance(output, (str, int, float, bool)) or output is None:
        return output
    return repr(output)


def _preview_text(value: Any, max_length: int = 240) -> str:
    text = "" if value is None else str(value)
    if len(text) <= max_length:
        return text
    return f"{text[:max_length]}..."


def _message_summary(message: Any) -> dict[str, Any]:
    serialized = _serialize_output(message)
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


def _context_summary(messages: list[Any]) -> dict[str, Any]:
    serialized = _serialize_output(messages)
    summary = {
        "message_count": len(messages),
        "approx_json_chars": len(json.dumps(serialized, ensure_ascii=False)),
        "messages": [_message_summary(message) for message in messages],
    }
    summary["context_budget"] = summarize_context_messages(serialized)
    return summary


def _response_summary(output: list[Any]) -> list[dict[str, Any]]:
    summaries = []
    for item in output:
        serialized = _serialize_output(item)
        if not isinstance(serialized, dict):
            summaries.append(
                {
                    "type": type(item).__name__,
                    "content_preview": _preview_text(serialized),
                }
            )
            continue

        summary: dict[str, Any] = {
            "type": serialized.get("type"),
            "role": serialized.get("role"),
            "id": serialized.get("id"),
            "status": serialized.get("status"),
        }
        if serialized.get("type") == "function_call":
            summary["name"] = serialized.get("name")
            summary["arguments"] = serialized.get("arguments")
            summary["call_id"] = serialized.get("call_id")
        else:
            summary["content_preview"] = _preview_text(serialized.get("content"))
        summaries.append(summary)
    return summaries


class Agent:
    def __init__(self) -> None:
        self.messages: list[Any] = []
        self.skills = discover_skills()

    def chat(self, user_input: str) -> str:
        log_event("user_input", role="user", content=user_input)

        prompt_result = build_system_prompt(user_input, self.skills)
        routing = prompt_result.routing
        log_event(
            "skill_routing",
            available_skills=list(self.skills),
            selected_skills=list(prompt_result.loaded_skills),
            scores=routing.scores,
            reasons={name: list(items) for name, items in routing.reasons.items()},
            fallback_used=routing.fallback_used,
            prompt_chars=prompt_result.prompt_chars,
        )

        self.messages.append(
            {
                "role": "user",
                "content": user_input,
            }
        )

        for loop_index in range(MAX_TOOL_CALL_LOOPS):
            log_event(
                "llm_request",
                loop=loop_index + 1,
                model=LLM_MODEL,
                context=_context_summary(self.messages),
            )
            log_raw_event(
                "llm_request",
                loop=loop_index + 1,
                model=LLM_MODEL,
                instructions=prompt_result.instructions,
                tools=TOOL_SCHEMAS,
                input=_serialize_output(self.messages),
            )

            try:
                response = client.responses.create(
                    model=LLM_MODEL,
                    instructions=prompt_result.instructions,
                    input=self.messages,
                    tools=TOOL_SCHEMAS,
                    temperature=LLM_TEMPERATURE,
                    max_output_tokens=LLM_MAX_OUTPUT_TOKENS,
                )
            except Exception as e:
                error_message = f"LLM request failed: {e}"
                log_event("error", error_message=error_message)
                return error_message

            raw_output = _serialize_output(response.output)
            log_event(
                "llm_response",
                loop=loop_index + 1,
                output=_response_summary(response.output),
            )
            log_raw_event(
                "llm_response",
                loop=loop_index + 1,
                output=raw_output,
                output_text=response.output_text,
            )

            self.messages += response.output

            function_calls = [
                item for item in response.output if item.type == "function_call"
            ]

            if not function_calls:
                answer = response.output_text
                log_event("final_answer", role="assistant", content=answer)
                return answer

            for function_call in function_calls:
                tool_name = function_call.name
                raw_arguments = function_call.arguments

                try:
                    arguments = json.loads(raw_arguments)
                except json.JSONDecodeError as e:
                    tool_result = f"Error: invalid JSON arguments for {tool_name}: {e}"
                    log_event(
                        "tool_error",
                        tool_call_name=tool_name,
                        tool_call_arguments=raw_arguments,
                        tool_result=tool_result,
                        error_message=str(e),
                    )
                    self.messages.append(
                        {
                            "type": "function_call_output",
                            "call_id": function_call.call_id,
                            "output": tool_result,
                        }
                    )
                    continue

                log_event(
                    "tool_call",
                    tool_call_name=tool_name,
                    tool_call_arguments=arguments,
                )

                tool_result = call_tool(tool_name, arguments)
                compacted_tool_result, compaction = compact_tool_output(
                    tool_name,
                    tool_result,
                )
                log_event(
                    "tool_result",
                    role="tool",
                    tool_call_name=tool_name,
                    tool_call_arguments=arguments,
                    content=compacted_tool_result,
                    context_compaction=compaction,
                )
                log_raw_event(
                    "tool_result",
                    role="tool",
                    tool_call_name=tool_name,
                    tool_call_arguments=arguments,
                    full_content=tool_result,
                    context_content=compacted_tool_result,
                    context_compaction=compaction,
                )

                self.messages.append(
                    {
                        "type": "function_call_output",
                        "call_id": function_call.call_id,
                        "output": compacted_tool_result,
                    }
                )

        final_answer = "工具调用次数过多，已停止。"
        log_event(
            "error",
            error_message="Exceeded maximum tool call loop count",
            final_answer=final_answer,
        )
        return final_answer
