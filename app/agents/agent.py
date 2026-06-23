import json
import time
from typing import Any

from app.config import (
    LLM_MAX_OUTPUT_TOKENS,
    LLM_MODEL,
    LLM_TEMPERATURE,
)
from app.observability import app_log, events, llm_io
from app.observability.serialization import json_safe
from app.prompts.prompt_builder import build_system_prompt
from app.runtime.context_manager import (
    compact_tool_output,
    summarize_context_messages,
)
from app.runtime.errors import (
    ErrorType,
    ExecutionError,
    classify_llm_exception,
    error_result,
    tool_error_from_result,
)
from app.runtime.run_state import (
    ActionRecord,
    ActionStatus,
    LoopLimits,
    RunState,
    RunStatus,
    StopReason,
)
from app.skills.skill_loader import discover_skills
from app.skills.skill_router import route_skills
from app.skills.skill_state import resolve_skill_state
from app.tools.capability_builder import build_capabilities
from app.tools.tool import TOOLS, ToolEffect, call_tool
from app.utils.llm import client


DEFAULT_LOOP_LIMITS = LoopLimits()


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


def _context_summary(messages: list[Any]) -> dict[str, Any]:
    serialized = json_safe(messages)
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
        serialized = json_safe(item)
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
        StopReason.REPEATED_CALL: "检测到重复工具调用，执行已停止。",
        StopReason.NO_PROGRESS: "工具调用没有产生新进展，执行已停止。",
        StopReason.CANCELLED: "本次执行已取消。",
        StopReason.UNRECOVERABLE_ERROR: "遇到不可恢复的执行错误。",
    }
    reason = reason_messages.get(run_state.stop_reason, "Agent 执行已停止。")
    details = []
    if run_state.completed_actions:
        names = ", ".join(action.tool_name for action in run_state.completed_actions)
        details.append(
            f"已保留 {len(run_state.completed_actions)} 个成功的工具结果：{names}。"
        )
    if run_state.failed_actions:
        names = ", ".join(action.tool_name for action in run_state.failed_actions)
        details.append(f"失败步骤：{names}。")
    if run_state.skipped_actions:
        names = ", ".join(action.tool_name for action in run_state.skipped_actions)
        details.append(f"未执行步骤：{names}。")
    return reason + "".join(details)


def _error_json(
    action: str,
    error_type: ErrorType,
    code: str,
    message: str,
) -> str:
    return json.dumps(
        error_result(
            action,
            ExecutionError(error_type, code, message, retryable=False),
        ),
        ensure_ascii=False,
    )


class Agent:
    def __init__(self, *, loop_limits: LoopLimits | None = None) -> None:
        self.messages: list[Any] = []
        self.skills = discover_skills()
        self.active_skills: tuple[str, ...] = ()
        self.loop_limits = loop_limits or DEFAULT_LOOP_LIMITS
        self.last_run_state: RunState | None = None

    def cancel_current_run(self) -> bool:
        if self.last_run_state is None:
            return False
        if self.last_run_state.status != RunStatus.RUNNING:
            return False
        self.last_run_state.request_cancel()
        return True

    def chat(self, user_input: str) -> str:
        run_state = RunState()
        self.last_run_state = run_state
        events.log_run_started(run_state, self.loop_limits.to_dict())
        events.log_user_input(run_state, user_input)
        app_log.log_info("Run %s started", run_state.run_id)

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
        events.log_routing_resolved(
            run_state,
            available_skills=self.skills,
            routing=routing,
            skill_state=skill_state,
            prompt_chars=prompt_result.prompt_chars,
        )
        events.log_capabilities_built(run_state, capability_result, TOOLS)

        self.messages.append(
            {
                "role": "user",
                "content": user_input,
            }
        )

        while run_state.can_start_llm_round(self.loop_limits):
            if run_state.cancel_requested:
                run_state.stop(
                    StopReason.CANCELLED,
                    partial=bool(run_state.completed_actions),
                )
                return self._stopped_answer(run_state)

            loop_number = run_state.start_llm_round(self.loop_limits)
            response = self._request_llm(
                run_state=run_state,
                loop_number=loop_number,
                instructions=prompt_result.instructions,
                tool_schemas=capability_result.tool_schemas,
            )
            if response is None:
                return self._stopped_answer(run_state)

            events.log_llm_responded(
                run_state, loop_number, _response_summary(response.output)
            )
            llm_io.log_response(run_state, loop_number, response)

            self.messages += response.output

            function_calls = [
                item for item in response.output if item.type == "function_call"
            ]

            if not function_calls:
                answer = response.output_text
                run_state.complete()
                events.log_final_answer(run_state, answer)
                events.log_run_completed(run_state)
                app_log.log_info("Run %s completed", run_state.run_id)
                return answer

            self._execute_function_calls(
                run_state=run_state,
                loop_number=loop_number,
                function_calls=function_calls,
                allowed_tool_names=capability_result.allowed_tool_names,
                loaded_skills=prompt_result.loaded_skills,
            )

            if run_state.stop_reason is not None:
                answer = _runtime_stop_answer(run_state)
                events.log_run_stopped(run_state, answer)
                app_log.log_warning(
                    "Run %s stopped: %s", run_state.run_id, run_state.stop_reason
                )
                return answer

        run_state.stop(
            StopReason.LLM_BUDGET_EXHAUSTED,
            partial=bool(run_state.completed_actions),
        )
        final_answer = _runtime_stop_answer(run_state)
        events.log_run_stopped(run_state, final_answer)
        app_log.log_warning(
            "Run %s stopped: %s", run_state.run_id, run_state.stop_reason
        )
        return final_answer

    def _request_llm(
        self,
        *,
        run_state: RunState,
        loop_number: int,
        instructions: str,
        tool_schemas: tuple[dict[str, Any], ...],
    ) -> Any | None:
        events.log_llm_requested(
            run_state, loop_number, _context_summary(self.messages)
        )
        for retry_index in range(self.loop_limits.max_llm_retries + 1):
            if run_state.cancel_requested:
                run_state.stop(
                    StopReason.CANCELLED,
                    partial=bool(run_state.completed_actions),
                )
                return None

            attempt_number = run_state.start_llm_attempt()
            events.log_llm_attempted(
                run_state, loop_number, attempt_number, retry_index
            )
            llm_io.log_request(
                run_state,
                loop_number,
                attempt_number,
                model=LLM_MODEL,
                instructions=instructions,
                tools=tool_schemas,
                input_messages=self.messages,
                parameters={
                    "temperature": LLM_TEMPERATURE,
                    "max_output_tokens": LLM_MAX_OUTPUT_TOKENS,
                },
            )
            try:
                return client.responses.create(
                    model=LLM_MODEL,
                    instructions=instructions,
                    input=self.messages,
                    tools=list(tool_schemas),
                    temperature=LLM_TEMPERATURE,
                    max_output_tokens=LLM_MAX_OUTPUT_TOKENS,
                )
            except Exception as exception:
                execution_error = classify_llm_exception(exception)
                events.log_llm_failed(
                    run_state, loop_number, attempt_number, execution_error
                )
                app_log.log_error(
                    "LLM attempt %s failed for run %s: %s",
                    attempt_number,
                    run_state.run_id,
                    execution_error.code,
                )
                can_retry = (
                    execution_error.retryable
                    and retry_index < self.loop_limits.max_llm_retries
                )
                if not can_retry:
                    if run_state.completed_actions:
                        run_state.stop(StopReason.LLM_REQUEST_FAILED, partial=True)
                    else:
                        run_state.fail(StopReason.LLM_REQUEST_FAILED)
                    return None
                retry_count = run_state.record_retry(f"llm:{loop_number}")
                events.log_llm_retry_scheduled(
                    run_state, loop_number, retry_count, execution_error
                )
                time.sleep(self.loop_limits.retry_backoff_seconds)
        return None

    def _execute_function_calls(
        self,
        *,
        run_state: RunState,
        loop_number: int,
        function_calls: list[Any],
        allowed_tool_names: frozenset[str],
        loaded_skills: tuple[str, ...],
    ) -> None:
        calls_started_this_round = 0
        for call_index, function_call in enumerate(function_calls):
            tool_name = function_call.name
            raw_arguments = function_call.arguments

            if run_state.cancel_requested:
                self._skip_calls(
                    run_state,
                    loop_number,
                    function_calls[call_index:],
                    ErrorType.CONTROL,
                    "cancelled",
                    "Run was cancelled before tool execution",
                )
                run_state.stop(
                    StopReason.CANCELLED,
                    partial=bool(run_state.completed_actions),
                )
                return

            if not run_state.can_start_tool_call(
                self.loop_limits,
                calls_started_this_round=calls_started_this_round,
            ):
                self._skip_calls(
                    run_state,
                    loop_number,
                    function_calls[call_index:],
                    ErrorType.CONTROL,
                    "tool_budget_exhausted",
                    "Tool call budget exhausted",
                )
                run_state.stop(
                    StopReason.TOOL_BUDGET_EXHAUSTED,
                    partial=bool(run_state.completed_actions),
                )
                return

            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError as exception:
                run_state.start_tool_call(
                    self.loop_limits,
                    calls_started_this_round=calls_started_this_round,
                )
                calls_started_this_round += 1
                tool_result = _error_json(
                    tool_name,
                    ErrorType.INVALID_ARGUMENTS,
                    "invalid_json_arguments",
                    str(exception),
                )
                parsed_result = _parse_result_object(tool_result)
                failed_action = ActionRecord(
                    call_id=function_call.call_id,
                    tool_name=tool_name,
                    arguments=raw_arguments,
                    status=ActionStatus.FAILED,
                    result=tool_result,
                    error=parsed_result.get("error") if parsed_result else None,
                )
                run_state.add_action(failed_action)
                self._append_tool_output(function_call.call_id, tool_result)
                events.log_tool_failed(
                    run_state,
                    loop_number,
                    function_call,
                    tool_result,
                    failed_action.error,
                )
                app_log.log_warning("Invalid JSON arguments for tool %s", tool_name)
                continue

            signature, signature_count, cycle_detected = run_state.register_call(
                tool_name,
                arguments,
            )
            tool = TOOLS.get(tool_name)
            repeated_write = bool(
                tool is not None
                and tool.effect == ToolEffect.WRITE
                and signature_count >= self.loop_limits.max_same_call_attempts
            )
            if cycle_detected or repeated_write:
                self._skip_calls(
                    run_state,
                    loop_number,
                    function_calls[call_index:],
                    ErrorType.CONTROL,
                    "repeated_call",
                    "Repeated tool call or A-B-A-B cycle detected",
                )
                run_state.stop(
                    StopReason.REPEATED_CALL,
                    partial=bool(run_state.completed_actions),
                )
                return

            idempotency_key = None
            if tool is not None and tool.effect == ToolEffect.WRITE:
                idempotency_key = f"{run_state.run_id}:{function_call.call_id}"

            attempt_count = 0
            tool_result = ""
            parsed_result: dict[str, Any] | None = None
            execution_error = None
            while True:
                if not run_state.can_start_tool_call(
                    self.loop_limits,
                    calls_started_this_round=calls_started_this_round,
                ):
                    break
                run_state.start_tool_call(
                    self.loop_limits,
                    calls_started_this_round=calls_started_this_round,
                )
                calls_started_this_round += 1
                attempt_count += 1

                events.log_tool_started(
                    run_state,
                    loop_number,
                    function_call,
                    arguments,
                    attempt_count,
                    idempotency_key,
                )
                if tool is not None and tool_name not in allowed_tool_names:
                    events.log_tool_denied(
                        run_state,
                        loop_number,
                        function_call,
                        arguments,
                        loaded_skills,
                    )

                tool_result = call_tool(
                    tool_name,
                    arguments,
                    allowed_tool_names=allowed_tool_names,
                    idempotency_key=idempotency_key,
                )
                parsed_result = _parse_result_object(tool_result)
                execution_error = tool_error_from_result(parsed_result)
                if run_state.cancel_requested:
                    break
                if execution_error is None:
                    break

                safe_retry = bool(
                    tool is not None
                    and tool.retryable
                    and execution_error.retryable
                    and (tool.effect == ToolEffect.READ or tool.idempotent)
                    and attempt_count <= self.loop_limits.max_tool_retries
                )
                if not safe_retry:
                    break
                if not run_state.can_start_tool_call(
                    self.loop_limits,
                    calls_started_this_round=calls_started_this_round,
                ):
                    break
                retry_count = run_state.record_retry(f"tool:{function_call.call_id}")
                events.log_tool_retry_scheduled(
                    run_state,
                    loop_number,
                    function_call,
                    retry_count,
                    execution_error,
                )
                time.sleep(self.loop_limits.retry_backoff_seconds)

            compacted_tool_result, compaction = compact_tool_output(
                tool_name,
                tool_result,
            )
            action_succeeded = bool(
                parsed_result is not None and parsed_result.get("ok") is True
            )
            observation_signature, observation_count = run_state.register_observation(
                signature,
                parsed_result if parsed_result is not None else tool_result,
            )
            action = ActionRecord(
                call_id=function_call.call_id,
                tool_name=tool_name,
                arguments=arguments,
                status=(
                    ActionStatus.COMPLETED
                    if action_succeeded
                    else ActionStatus.FAILED
                ),
                result=compacted_tool_result,
                error=(execution_error.to_dict() if execution_error else None),
                signature=signature,
                observation_signature=observation_signature,
                attempt_count=attempt_count,
                idempotency_key=idempotency_key,
            )
            run_state.add_action(action)
            events.log_tool_finished(
                run_state, loop_number, action, context_compaction=compaction
            )
            self._append_tool_output(function_call.call_id, compacted_tool_result)

            if run_state.cancel_requested:
                self._skip_calls(
                    run_state,
                    loop_number,
                    function_calls[call_index + 1 :],
                    ErrorType.CONTROL,
                    "cancelled",
                    "Run was cancelled after tool execution",
                )
                run_state.stop(
                    StopReason.CANCELLED,
                    partial=bool(run_state.completed_actions),
                )
                return

            if (
                signature_count >= self.loop_limits.max_same_call_attempts
                and observation_count
                >= self.loop_limits.max_identical_observations
            ):
                self._skip_calls(
                    run_state,
                    loop_number,
                    function_calls[call_index + 1 :],
                    ErrorType.CONTROL,
                    "no_progress",
                    "Repeated call returned an identical observation",
                )
                run_state.stop(
                    StopReason.NO_PROGRESS,
                    partial=bool(run_state.completed_actions),
                )
                return

    def _skip_calls(
        self,
        run_state: RunState,
        loop_number: int,
        calls: list[Any],
        error_type: ErrorType,
        code: str,
        message: str,
    ) -> None:
        for call in calls:
            output = _error_json(call.name, error_type, code, message)
            parsed = _parse_result_object(output)
            skipped_action = ActionRecord(
                call_id=call.call_id,
                tool_name=call.name,
                arguments=call.arguments,
                status=ActionStatus.SKIPPED,
                result=output,
                error=parsed.get("error") if parsed else None,
            )
            run_state.add_action(skipped_action)
            self._append_tool_output(call.call_id, output)
            events.log_tool_skipped(run_state, loop_number, skipped_action)

    def _append_tool_output(self, call_id: str, output: str) -> None:
        self.messages.append(
            {
                "type": "function_call_output",
                "call_id": call_id,
                "output": output,
            }
        )

    def _stopped_answer(self, run_state: RunState) -> str:
        answer = _runtime_stop_answer(run_state)
        events.log_run_stopped(run_state, answer)
        app_log.log_warning(
            "Run %s stopped: %s", run_state.run_id, run_state.stop_reason
        )
        return answer
