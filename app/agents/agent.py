import json
import time
from dataclasses import dataclass
from typing import Any

from app.config import (
    LLM_MAX_OUTPUT_TOKENS,
    LLM_MODEL,
    LLM_TEMPERATURE,
)
from app.observability import app_log, events, llm_io
from app.prompts.prompt_builder import build_system_prompt
from app.runtime.context_engine import ContextEngine
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
from app.runtime.write_policy import (
    authorized_write_tools,
    has_write_success_claim,
    requires_bulk_delete_confirmation,
)
from app.skills.skill_loader import discover_skills
from app.skills.skill_router import route_skills
from app.skills.skill_state import resolve_skill_state
from app.tools.capability_builder import build_capabilities
from app.tools.tool import TOOLS, ToolEffect, call_tool
from app.utils.json_file import parse_json_object
from app.utils.llm import client
from app.utils.serialization import json_safe


DEFAULT_LOOP_LIMITS = LoopLimits()


@dataclass(frozen=True)
class TurnContext:
    """Prompt and capability snapshot that stays fixed during one user turn."""

    instructions: str
    tool_schemas: tuple[dict[str, Any], ...]
    allowed_tool_names: frozenset[str]
    loaded_skills: tuple[str, ...]
    bulk_delete_confirmation_required: bool


@dataclass(frozen=True)
class ToolExecutionResult:
    """Result of all runtime attempts for one model-requested tool action."""

    content: str
    parsed: dict[str, Any] | None
    error: ExecutionError | None
    tool_execution_attempt_count: int


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
    return parse_json_object(result)


def _requested_count_from_arguments(arguments: dict[str, Any]) -> int | None:
    limit = arguments.get("limit")
    return limit if isinstance(limit, int) and limit > 0 else None


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
    if run_state.completed_action_records:
        names = ", ".join(
            action.tool_name for action in run_state.completed_action_records
        )
        details.append(
            f"已保留 {len(run_state.completed_action_records)} 个成功的工具结果：{names}。"
        )
    if run_state.failed_action_records:
        names = ", ".join(
            action.tool_name for action in run_state.failed_action_records
        )
        details.append(f"失败步骤：{names}。")
    if run_state.skipped_action_records:
        names = ", ".join(
            action.tool_name for action in run_state.skipped_action_records
        )
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
    """Coordinate skill routing, LLM rounds, tools, and per-request RunState."""

    def __init__(self, *, loop_limits: LoopLimits | None = None) -> None:
        self.messages: list[Any] = []
        self.skills = discover_skills()
        self.active_skills: tuple[str, ...] = ()
        self.loop_limits = loop_limits or DEFAULT_LOOP_LIMITS
        self.last_run_state: RunState | None = None
        self.context_engine = ContextEngine()

    def cancel_current_run(self) -> bool:
        """Request cooperative cancellation at the next runtime checkpoint."""
        if self.last_run_state is None:
            return False
        if self.last_run_state.status != RunStatus.RUNNING:
            return False
        self.last_run_state.request_cancel()
        return True

    def chat(self, user_input: str) -> str:
        """Execute one user turn and return either an answer or stop summary."""
        run_state = RunState()
        self.last_run_state = run_state
        events.log_run_started(run_state, self.loop_limits.to_dict())
        events.log_user_input(run_state, user_input)
        app_log.log_info("Run %s started", run_state.run_id)

        turn = self._prepare_turn(user_input, run_state)
        return self._run_agent_loop(run_state, turn)

    def _prepare_turn(self, user_input: str, run_state: RunState) -> TurnContext:
        """Resolve skills and freeze the prompt/tool boundary for this turn."""
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
        authorized_writes = authorized_write_tools(user_input)
        bulk_delete_confirmation_required = requires_bulk_delete_confirmation(
            user_input
        )
        capability_result = build_capabilities(
            prompt_result.loaded_skills,
            authorized_write_tool_names=authorized_writes,
        )
        instructions = prompt_result.instructions
        if bulk_delete_confirmation_required:
            instructions += (
                "\n\nSafety policy for this turn:\n"
                "- The user requested a destructive bulk deletion without explicit confirmation.\n"
                "- Do not delete anything. Ask the user to confirm the exact bulk deletion.\n"
                "- Do not claim that any item was deleted."
            )
        events.log_routing_resolved(
            run_state,
            available_skills=self.skills,
            routing=routing,
            skill_state=skill_state,
            prompt_chars=prompt_result.prompt_chars,
        )
        events.log_capabilities_built(run_state, capability_result, TOOLS)
        self.messages.append({"role": "user", "content": user_input})
        return TurnContext(
            instructions=instructions,
            tool_schemas=capability_result.tool_schemas,
            allowed_tool_names=capability_result.allowed_tool_names,
            loaded_skills=prompt_result.loaded_skills,
            bulk_delete_confirmation_required=bulk_delete_confirmation_required,
        )

    def _run_agent_loop(self, run_state: RunState, turn: TurnContext) -> str:
        """Run sequential LLM/tool rounds until completion or a controlled stop."""
        while run_state.can_start_llm_round(self.loop_limits):
            if run_state.chat_cancellation_requested:
                run_state.stop(
                    StopReason.CANCELLED,
                    partial=bool(run_state.completed_action_records),
                )
                return self._stopped_answer(run_state)

            loop_number = run_state.start_llm_round(self.loop_limits)
            response = self._request_llm(
                run_state=run_state,
                loop_number=loop_number,
                instructions=turn.instructions,
                tool_schemas=turn.tool_schemas,
            )
            if response is None:
                return self._stopped_answer(run_state)

            events.log_llm_responded(
                run_state, loop_number, _response_summary(response.output)
            )
            llm_io.log_response(run_state, loop_number, response)

            function_calls = [
                item for item in response.output if item.type == "function_call"
            ]

            if not function_calls:
                answer = self._validate_final_answer(response.output_text, run_state)
                if answer == response.output_text:
                    self.messages += response.output
                else:
                    self.messages.append({"role": "assistant", "content": answer})
                run_state.complete()
                self.context_engine.after_turn(self.messages)
                events.log_final_answer(run_state, answer)
                events.log_run_completed(run_state)
                app_log.log_info("Run %s completed", run_state.run_id)
                return answer

            self.messages += response.output

            self._execute_function_calls(
                run_state=run_state,
                loop_number=loop_number,
                function_calls=function_calls,
                allowed_tool_names=turn.allowed_tool_names,
                loaded_skills=turn.loaded_skills,
            )

            if run_state.stop_reason is not None:
                return self._stopped_answer(run_state)

        run_state.stop(
            StopReason.LLM_BUDGET_EXHAUSTED,
            partial=bool(run_state.completed_action_records),
        )
        return self._stopped_answer(run_state)

    @staticmethod
    def _validate_final_answer(answer: str, run_state: RunState) -> str:
        """Prevent a model-only answer from claiming an unconfirmed write."""
        successful_writes = [
            action
            for action in run_state.completed_action_records
            if (tool := TOOLS.get(action.tool_name)) is not None
            and tool.effect == ToolEffect.WRITE
        ]
        failed_writes = [
            action
            for action in run_state.failed_action_records
            if (tool := TOOLS.get(action.tool_name)) is not None
            and tool.effect == ToolEffect.WRITE
        ]
        if failed_writes and has_write_success_claim(answer):
            succeeded = ", ".join(action.tool_name for action in successful_writes) or "无"
            failed = ", ".join(action.tool_name for action in failed_writes)
            return (
                f"本次写入未全部成功。已成功：{succeeded}；未成功：{failed}。"
                "请确认后重试失败项。"
            )
        if successful_writes or not has_write_success_claim(answer):
            return answer
        return (
            "我没有收到任何成功的写入结果，因此不能确认数据已经保存或修改。"
            "请重试该写入操作，或稍后再试。"
        )

    def _request_llm(
        self,
        *,
        run_state: RunState,
        loop_number: int,
        instructions: str,
        tool_schemas: tuple[dict[str, Any], ...],
    ) -> Any | None:
        """Call the model with explicit retry accounting and boundary logs."""
        assembly = self.context_engine.assemble(
            self.messages,
            instructions=instructions,
            tools=tool_schemas,
        )
        context = _context_summary(assembly.input_messages)
        context["context_engine"] = assembly.report
        events.log_llm_requested(run_state, loop_number, context)
        for retry_index in range(self.loop_limits.max_llm_retries + 1):
            if run_state.chat_cancellation_requested:
                run_state.stop(
                    StopReason.CANCELLED,
                    partial=bool(run_state.completed_action_records),
                )
                return None

            request_number = run_state.start_llm_request()
            events.log_llm_attempted(
                run_state, loop_number, request_number, retry_index
            )
            llm_io.log_request(
                run_state,
                loop_number,
                request_number,
                model=LLM_MODEL,
                instructions=instructions,
                tools=tool_schemas,
                input_messages=assembly.input_messages,
                parameters={
                    "temperature": LLM_TEMPERATURE,
                    "max_output_tokens": LLM_MAX_OUTPUT_TOKENS,
                    "context_engine": assembly.report,
                },
            )
            try:
                return client.responses.create(
                    model=LLM_MODEL,
                    instructions=instructions,
                    input=assembly.input_messages,
                    tools=list(tool_schemas),
                    temperature=LLM_TEMPERATURE,
                    max_output_tokens=LLM_MAX_OUTPUT_TOKENS,
                )
            except Exception as exception:
                if not self._handle_llm_failure(
                    run_state=run_state,
                    loop_number=loop_number,
                    llm_request_number=request_number,
                    retry_index=retry_index,
                    exception=exception,
                ):
                    return None
                time.sleep(self.loop_limits.retry_backoff_seconds)
        return None

    def _handle_llm_failure(
        self,
        *,
        run_state: RunState,
        loop_number: int,
        llm_request_number: int,
        retry_index: int,
        exception: Exception,
    ) -> bool:
        """Classify one LLM failure and decide whether the loop may retry."""
        execution_error = classify_llm_exception(exception)
        events.log_llm_failed(
            run_state, loop_number, llm_request_number, execution_error
        )
        app_log.log_error(
            "LLM attempt %s failed for run %s: %s",
            llm_request_number,
            run_state.run_id,
            execution_error.code,
        )
        can_retry = (
            execution_error.retryable
            and retry_index < self.loop_limits.max_llm_retries
        )
        if not can_retry:
            if run_state.completed_action_records:
                run_state.stop(StopReason.LLM_REQUEST_FAILED, partial=True)
            else:
                run_state.fail(StopReason.LLM_REQUEST_FAILED)
            return False

        retry_count = run_state.record_retry(f"llm:{loop_number}")
        events.log_llm_retry_scheduled(
            run_state, loop_number, retry_count, execution_error
        )
        return True

    def _execute_function_calls(
        self,
        *,
        run_state: RunState,
        loop_number: int,
        function_calls: list[Any],
        allowed_tool_names: frozenset[str],
        loaded_skills: tuple[str, ...],
    ) -> None:
        """Execute one response's tool calls in order, preserving stop semantics."""
        calls_started_this_round = 0
        for call_index, function_call in enumerate(function_calls):
            tool_name = function_call.name
            raw_arguments = function_call.arguments

            if self._stop_before_tool_call(
                run_state,
                loop_number,
                function_calls[call_index:],
                calls_started_this_round,
            ):
                return

            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError as exception:
                calls_started_this_round = self._record_invalid_arguments(
                    run_state,
                    loop_number,
                    function_call,
                    exception,
                    calls_started_this_round,
                )
                continue

            signature, signature_count, cycle_detected = run_state.register_call(
                tool_name,
                arguments,
            )
            # Stable signatures expose deterministic repetition without guessing intent.
            tool = TOOLS.get(tool_name)
            repeated_write = bool(
                tool is not None
                and tool.effect == ToolEffect.WRITE
                and signature_count >= self.loop_limits.max_same_call_attempts
            )
            if cycle_detected or repeated_write:
                self._stop_repeated_calls(
                    run_state, loop_number, function_calls[call_index:]
                )
                return

            idempotency_key = None
            if tool is not None and tool.effect == ToolEffect.WRITE:
                # A call_id identifies the same requested side effect across retries.
                idempotency_key = f"{run_state.run_id}:{function_call.call_id}"

            execution, calls_started_this_round = self._execute_tool_with_retry(
                run_state=run_state,
                loop_number=loop_number,
                function_call=function_call,
                arguments=arguments,
                tool=tool,
                allowed_tool_names=allowed_tool_names,
                loaded_skills=loaded_skills,
                idempotency_key=idempotency_key,
                calls_started_this_round=calls_started_this_round,
            )

            observation_count = self._record_tool_result(
                run_state=run_state,
                loop_number=loop_number,
                function_call=function_call,
                arguments=arguments,
                signature=signature,
                idempotency_key=idempotency_key,
                execution=execution,
            )
            if self._stop_after_tool_call(
                run_state=run_state,
                loop_number=loop_number,
                remaining_calls=function_calls[call_index + 1 :],
                signature_count=signature_count,
                observation_count=observation_count,
            ):
                return

    def _record_tool_result(
        self,
        *,
        run_state: RunState,
        loop_number: int,
        function_call: Any,
        arguments: dict[str, Any],
        signature: str,
        idempotency_key: str | None,
        execution: ToolExecutionResult,
    ) -> int:
        """Compact a tool result, record its Action, and append its observation."""
        compacted_result, compaction = compact_tool_output(
            function_call.name,
            execution.content,
            requested_count=_requested_count_from_arguments(arguments),
        )
        action_succeeded = bool(
            execution.parsed is not None and execution.parsed.get("ok") is True
        )
        observation_signature, observation_count = run_state.register_observation(
            signature,
            execution.parsed if execution.parsed is not None else execution.content,
        )
        action = ActionRecord(
            call_id=function_call.call_id,
            tool_name=function_call.name,
            arguments=arguments,
            status=(
                ActionStatus.COMPLETED if action_succeeded else ActionStatus.FAILED
            ),
            result=compacted_result,
            error=(execution.error.to_dict() if execution.error else None),
            tool_call_signature=signature,
            tool_observation_signature=observation_signature,
            tool_execution_attempt_count=execution.tool_execution_attempt_count,
            idempotency_key=idempotency_key,
        )
        run_state.add_action(action)
        events.log_tool_finished(
            run_state, loop_number, action, context_compaction=compaction
        )
        self._append_tool_output(function_call.call_id, compacted_result)
        return observation_count

    def _stop_after_tool_call(
        self,
        *,
        run_state: RunState,
        loop_number: int,
        remaining_calls: list[Any],
        signature_count: int,
        observation_count: int,
    ) -> bool:
        """Apply cancellation and no-progress checkpoints after an observation."""
        if run_state.chat_cancellation_requested:
            code = "cancelled"
            message = "Run was cancelled after tool execution"
            reason = StopReason.CANCELLED
        elif (
            signature_count >= self.loop_limits.max_same_call_attempts
            and observation_count >= self.loop_limits.max_identical_observations
        ):
            code = "no_progress"
            message = "Repeated call returned an identical observation"
            reason = StopReason.NO_PROGRESS
        else:
            return False

        self._skip_calls(
            run_state,
            loop_number,
            remaining_calls,
            ErrorType.CONTROL,
            code,
            message,
        )
        run_state.stop(reason, partial=bool(run_state.completed_action_records))
        return True

    def _stop_before_tool_call(
        self,
        run_state: RunState,
        loop_number: int,
        remaining_calls: list[Any],
        calls_started_this_round: int,
    ) -> bool:
        """Apply cancellation and budget checkpoints before side effects begin."""
        if run_state.chat_cancellation_requested:
            code = "cancelled"
            message = "Run was cancelled before tool execution"
            reason = StopReason.CANCELLED
        elif not run_state.can_start_tool_call(
            self.loop_limits,
            calls_started_this_round=calls_started_this_round,
        ):
            code = "tool_budget_exhausted"
            message = "Tool call budget exhausted"
            reason = StopReason.TOOL_BUDGET_EXHAUSTED
        else:
            return False

        self._skip_calls(
            run_state,
            loop_number,
            remaining_calls,
            ErrorType.CONTROL,
            code,
            message,
        )
        run_state.stop(reason, partial=bool(run_state.completed_action_records))
        return True

    def _record_invalid_arguments(
        self,
        run_state: RunState,
        loop_number: int,
        function_call: Any,
        exception: json.JSONDecodeError,
        calls_started_this_round: int,
    ) -> int:
        """Turn malformed model arguments into a failed action and observation."""
        run_state.start_tool_call(
            self.loop_limits,
            calls_started_this_round=calls_started_this_round,
        )
        tool_result = _error_json(
            function_call.name,
            ErrorType.INVALID_ARGUMENTS,
            "invalid_json_arguments",
            str(exception),
        )
        parsed_result = _parse_result_object(tool_result)
        failed_action = ActionRecord(
            call_id=function_call.call_id,
            tool_name=function_call.name,
            arguments=function_call.arguments,
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
        app_log.log_warning(
            "Invalid JSON arguments for tool %s", function_call.name
        )
        return calls_started_this_round + 1

    def _stop_repeated_calls(
        self,
        run_state: RunState,
        loop_number: int,
        remaining_calls: list[Any],
    ) -> None:
        """Stop before executing a repeated write or detected A-B-A-B cycle."""
        self._skip_calls(
            run_state,
            loop_number,
            remaining_calls,
            ErrorType.CONTROL,
            "repeated_call",
            "Repeated tool call or A-B-A-B cycle detected",
        )
        run_state.stop(
            StopReason.REPEATED_CALL,
            partial=bool(run_state.completed_action_records),
        )

    def _execute_tool_with_retry(
        self,
        *,
        run_state: RunState,
        loop_number: int,
        function_call: Any,
        arguments: dict[str, Any],
        tool: Any,
        allowed_tool_names: frozenset[str],
        loaded_skills: tuple[str, ...],
        idempotency_key: str | None,
        calls_started_this_round: int,
    ) -> tuple[ToolExecutionResult, int]:
        """Execute one tool action while making every retry explicit and budgeted."""
        attempt_count = 0
        tool_result = ""
        parsed_result: dict[str, Any] | None = None
        execution_error: ExecutionError | None = None

        while run_state.can_start_tool_call(
            self.loop_limits,
            calls_started_this_round=calls_started_this_round,
        ):
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
            if tool is not None and function_call.name not in allowed_tool_names:
                events.log_tool_denied(
                    run_state,
                    loop_number,
                    function_call,
                    arguments,
                    loaded_skills,
                )

            tool_result = call_tool(
                function_call.name,
                arguments,
                allowed_tool_names=allowed_tool_names,
                idempotency_key=idempotency_key,
            )
            parsed_result = _parse_result_object(tool_result)
            execution_error = tool_error_from_result(parsed_result)
            if run_state.chat_cancellation_requested or execution_error is None:
                break
            if not self._can_retry_tool(tool, execution_error, attempt_count):
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

        return (
            ToolExecutionResult(
                content=tool_result,
                parsed=parsed_result,
                error=execution_error,
                tool_execution_attempt_count=attempt_count,
            ),
            calls_started_this_round,
        )

    def _can_retry_tool(
        self,
        tool: Any,
        execution_error: ExecutionError,
        attempt_count: int,
    ) -> bool:
        """Retry only safe read/idempotent operations within the retry budget."""
        return bool(
            tool is not None
            and tool.retryable
            and execution_error.retryable
            and (tool.effect == ToolEffect.READ or tool.idempotent)
            and attempt_count <= self.loop_limits.max_tool_retries
        )

    def _skip_calls(
        self,
        run_state: RunState,
        loop_number: int,
        calls: list[Any],
        error_type: ErrorType,
        code: str,
        message: str,
    ) -> None:
        """Record skipped calls and still return one observation per call_id."""
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
        """Append the Responses API observation paired to a function call."""
        self.messages.append(
            {
                "type": "function_call_output",
                "call_id": call_id,
                "output": output,
            }
        )

    def _stopped_answer(self, run_state: RunState) -> str:
        """Log and format a controlled runtime stop exactly once."""
        answer = _runtime_stop_answer(run_state)
        self.context_engine.after_turn(self.messages)
        events.log_run_stopped(run_state, answer)
        app_log.log_warning(
            "Run %s stopped: %s", run_state.run_id, run_state.stop_reason
        )
        return answer
