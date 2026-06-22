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
from app.runtime.run_state import (
    ActionRecord,
    ActionStatus,
    LoopLimits,
    RunState,
    StopReason,
)
from app.skills.skill_loader import discover_skills
from app.skills.skill_router import route_skills
from app.skills.skill_state import resolve_skill_state
from app.tools.capability_builder import build_capabilities
from app.tools.tool import TOOLS, call_tool
from app.utils.llm import client


DEFAULT_LOOP_LIMITS = LoopLimits()


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


def _parse_result_object(result: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(result)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _runtime_stop_answer(run_state: RunState) -> str:
    reason_messages = {
        StopReason.LLM_BUDGET_EXHAUSTED: "模型调用轮数已达到限制。",
        StopReason.TOOL_BUDGET_EXHAUSTED: "工具调用数量已达到限制。",
        StopReason.LLM_REQUEST_FAILED: "模型请求失败。",
    }
    reason = reason_messages.get(run_state.stop_reason, "Agent 执行已停止。")
    if run_state.completed_actions:
        return f"{reason}已保留 {len(run_state.completed_actions)} 个成功的工具结果。"
    return reason


class Agent:
    def __init__(self, *, loop_limits: LoopLimits | None = None) -> None:
        self.messages: list[Any] = []
        self.skills = discover_skills()
        self.active_skills: tuple[str, ...] = ()
        self.loop_limits = loop_limits or DEFAULT_LOOP_LIMITS
        self.last_run_state: RunState | None = None

    def chat(self, user_input: str) -> str:
        run_state = RunState()
        self.last_run_state = run_state
        run_id = run_state.run_id
        log_event(
            "run_started",
            run_id=run_id,
            limits=self.loop_limits.to_dict(),
        )
        log_event("user_input", run_id=run_id, role="user", content=user_input)

        routing = route_skills(user_input, self.skills)
        skill_state = resolve_skill_state(
            user_input,
            routing.selected,
            self.active_skills,
        )
        self.active_skills = skill_state.next_active_skills
        prompt_result = build_system_prompt(
            self.skills,
            skill_state.loaded_skills,
        )
        capability_result = build_capabilities(prompt_result.loaded_skills)
        log_event(
            "skill_routing",
            run_id=run_id,
            available_skills=list(self.skills),
            directly_selected=list(skill_state.directly_selected),
            inherited_skills=list(skill_state.inherited_skills),
            loaded_skills=list(skill_state.loaded_skills),
            previous_active_skills=list(skill_state.previous_active_skills),
            next_active_skills=list(skill_state.next_active_skills),
            inheritance_used=skill_state.inheritance_used,
            state_cleared=skill_state.state_cleared,
            state_resolution=skill_state.resolution,
            scores=routing.scores,
            reasons={name: list(items) for name, items in routing.reasons.items()},
            direct_fallback_used=routing.fallback_used,
            prompt_chars=prompt_result.prompt_chars,
        )
        log_event(
            "capability_build",
            run_id=run_id,
            loaded_skills=list(prompt_result.loaded_skills),
            visible_tool_names=[
                schema["name"] for schema in capability_result.tool_schemas
            ],
            capability_sources={
                name: list(sources)
                for name, sources in capability_result.capability_sources.items()
            },
            tool_schema_count=capability_result.schema_count,
            tool_schema_chars=capability_result.schema_chars,
            fallback_used=capability_result.fallback_used,
        )

        self.messages.append(
            {
                "role": "user",
                "content": user_input,
            }
        )

        while run_state.can_start_llm_round(self.loop_limits):
            loop_number = run_state.start_llm_round(self.loop_limits)
            log_event(
                "llm_request",
                run_id=run_id,
                loop=loop_number,
                model=LLM_MODEL,
                context=_context_summary(self.messages),
                run_state=run_state.to_dict(include_actions=False),
            )
            log_raw_event(
                "llm_request",
                run_id=run_id,
                loop=loop_number,
                model=LLM_MODEL,
                instructions=prompt_result.instructions,
                tools=capability_result.tool_schemas,
                input=_serialize_output(self.messages),
            )

            try:
                response = client.responses.create(
                    model=LLM_MODEL,
                    instructions=prompt_result.instructions,
                    input=self.messages,
                    tools=list(capability_result.tool_schemas),
                    temperature=LLM_TEMPERATURE,
                    max_output_tokens=LLM_MAX_OUTPUT_TOKENS,
                )
            except Exception as e:
                error_message = f"LLM request failed: {e}"
                run_state.fail(StopReason.LLM_REQUEST_FAILED)
                log_event(
                    "run_stopped",
                    run_id=run_id,
                    error_message=error_message,
                    run_state=run_state.to_dict(),
                )
                return error_message

            raw_output = _serialize_output(response.output)
            log_event(
                "llm_response",
                run_id=run_id,
                loop=loop_number,
                output=_response_summary(response.output),
            )
            log_raw_event(
                "llm_response",
                run_id=run_id,
                loop=loop_number,
                output=raw_output,
                output_text=response.output_text,
            )

            self.messages += response.output

            function_calls = [
                item for item in response.output if item.type == "function_call"
            ]

            if not function_calls:
                answer = response.output_text
                run_state.complete()
                log_event(
                    "final_answer",
                    run_id=run_id,
                    role="assistant",
                    content=answer,
                )
                log_event(
                    "run_completed",
                    run_id=run_id,
                    run_state=run_state.to_dict(),
                )
                return answer

            calls_started_this_round = 0
            for call_index, function_call in enumerate(function_calls):
                tool_name = function_call.name
                raw_arguments = function_call.arguments

                if not run_state.can_start_tool_call(
                    self.loop_limits,
                    calls_started_this_round=calls_started_this_round,
                ):
                    for skipped_call in function_calls[call_index:]:
                        skipped_result = json.dumps(
                            {
                                "ok": False,
                                "action": skipped_call.name,
                                "error": "tool_budget_exhausted",
                            },
                            ensure_ascii=False,
                        )
                        run_state.add_action(
                            ActionRecord(
                                call_id=skipped_call.call_id,
                                tool_name=skipped_call.name,
                                arguments=skipped_call.arguments,
                                status=ActionStatus.SKIPPED,
                                result=skipped_result,
                                error="tool_budget_exhausted",
                            )
                        )
                        self.messages.append(
                            {
                                "type": "function_call_output",
                                "call_id": skipped_call.call_id,
                                "output": skipped_result,
                            }
                        )
                        log_event(
                            "tool_skipped",
                            run_id=run_id,
                            loop=loop_number,
                            tool_call_name=skipped_call.name,
                            tool_call_arguments=skipped_call.arguments,
                            error="tool_budget_exhausted",
                        )
                    run_state.stop(
                        StopReason.TOOL_BUDGET_EXHAUSTED,
                        partial=bool(run_state.completed_actions),
                    )
                    break

                run_state.start_tool_call(
                    self.loop_limits,
                    calls_started_this_round=calls_started_this_round,
                )
                calls_started_this_round += 1

                try:
                    arguments = json.loads(raw_arguments)
                except json.JSONDecodeError as e:
                    tool_result = json.dumps(
                        {
                            "ok": False,
                            "action": tool_name,
                            "error": "invalid_json_arguments",
                            "message": str(e),
                        },
                        ensure_ascii=False,
                    )
                    run_state.add_action(
                        ActionRecord(
                            call_id=function_call.call_id,
                            tool_name=tool_name,
                            arguments=raw_arguments,
                            status=ActionStatus.FAILED,
                            result=tool_result,
                            error="invalid_json_arguments",
                        )
                    )
                    log_event(
                        "tool_error",
                        run_id=run_id,
                        loop=loop_number,
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
                    run_id=run_id,
                    loop=loop_number,
                    tool_call_name=tool_name,
                    tool_call_arguments=arguments,
                )

                if (
                    tool_name in TOOLS
                    and tool_name not in capability_result.allowed_tool_names
                ):
                    log_event(
                        "tool_denied",
                        run_id=run_id,
                        loop=loop_number,
                        tool_call_name=tool_name,
                        tool_call_arguments=arguments,
                        loaded_skills=list(prompt_result.loaded_skills),
                        allowed_tool_names=[
                            schema["name"]
                            for schema in capability_result.tool_schemas
                        ],
                        error="tool_not_allowed",
                    )

                tool_result = call_tool(
                    tool_name,
                    arguments,
                    allowed_tool_names=capability_result.allowed_tool_names,
                )
                compacted_tool_result, compaction = compact_tool_output(
                    tool_name,
                    tool_result,
                )
                parsed_result = _parse_result_object(tool_result)
                action_succeeded = bool(
                    parsed_result is not None and parsed_result.get("ok") is True
                )
                action_error = None
                if not action_succeeded:
                    if parsed_result is not None:
                        action_error = str(parsed_result.get("error") or "tool_failed")
                    else:
                        action_error = "invalid_tool_result"
                run_state.add_action(
                    ActionRecord(
                        call_id=function_call.call_id,
                        tool_name=tool_name,
                        arguments=arguments,
                        status=(
                            ActionStatus.COMPLETED
                            if action_succeeded
                            else ActionStatus.FAILED
                        ),
                        result=compacted_tool_result,
                        error=action_error,
                    )
                )
                log_event(
                    "tool_result",
                    run_id=run_id,
                    loop=loop_number,
                    role="tool",
                    tool_call_name=tool_name,
                    tool_call_arguments=arguments,
                    content=compacted_tool_result,
                    context_compaction=compaction,
                )
                log_raw_event(
                    "tool_result",
                    run_id=run_id,
                    loop=loop_number,
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

            if run_state.stop_reason is not None:
                answer = _runtime_stop_answer(run_state)
                log_event(
                    "run_stopped",
                    run_id=run_id,
                    final_answer=answer,
                    run_state=run_state.to_dict(),
                )
                return answer

        run_state.stop(
            StopReason.LLM_BUDGET_EXHAUSTED,
            partial=bool(run_state.completed_actions),
        )
        final_answer = _runtime_stop_answer(run_state)
        log_event(
            "run_stopped",
            run_id=run_id,
            final_answer=final_answer,
            run_state=run_state.to_dict(),
        )
        return final_answer
