"""Action recording helper shared by tool execution paths."""

import json
from collections.abc import Callable
from typing import Any

from app.context.context_manager import compact_tool_output
from app.observability import app_log, events
from app.runtime.errors import ErrorType, ExecutionError, error_result
from app.runtime.run_state import ActionRecord, ActionStatus, RunState
from app.tools.tool import TOOLS, ToolEffect
from app.utils.json_file import parse_json_object


AppendToolOutput = Callable[[str, str], None]


class ActionRecorder:
    """Create ActionRecords, sync Recovery records, and append observations."""

    def __init__(
        self,
        *,
        recovery_store: Any,
        append_tool_output: AppendToolOutput,
    ) -> None:
        self.recovery_store = recovery_store
        self.append_tool_output = append_tool_output

    def record_tool_result(
        self,
        *,
        run_state: RunState,
        loop_number: int,
        function_call: Any,
        arguments: dict[str, Any],
        signature: str,
        idempotency_key: str | None,
        execution: Any,
    ) -> int:
        """Compact a tool result, record its Action, and append its observation."""
        compacted_result, compaction = compact_tool_output(
            function_call.name,
            execution.content,
            requested_count=_requested_count_from_arguments(arguments),
        )
        recorded_result = _history_safe_tool_result(
            function_call.name,
            compacted_result,
        )
        if recorded_result != compacted_result:
            compaction = {
                **compaction,
                "strategy": "ephemeral_reference",
                "compacted_chars": len(recorded_result),
            }
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
            result=recorded_result,
            error=(execution.error.to_dict() if execution.error else None),
            tool_call_signature=signature,
            tool_observation_signature=observation_signature,
            tool_execution_attempt_count=execution.tool_execution_attempt_count,
            idempotency_key=idempotency_key,
        )
        self._record_action(run_state, action)
        events.log_tool_finished(
            run_state, loop_number, action, context_compaction=compaction
        )
        self.append_tool_output(function_call.call_id, compacted_result)
        return observation_count

    def record_invalid_arguments(
        self,
        *,
        run_state: RunState,
        loop_number: int,
        function_call: Any,
        exception: json.JSONDecodeError,
        calls_started_this_round: int,
        start_tool_call: Callable[[], None],
    ) -> int:
        """Turn malformed model arguments into a failed action and observation."""
        start_tool_call()
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
        self._record_action(run_state, failed_action)
        self.append_tool_output(function_call.call_id, tool_result)
        events.log_tool_failed(
            run_state,
            loop_number,
            function_call,
            tool_result,
            failed_action.error,
        )
        app_log.log_warning("Invalid JSON arguments for tool %s", function_call.name)
        return calls_started_this_round + 1

    def skip_calls(
        self,
        *,
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
            self._record_action(run_state, skipped_action)
            self.append_tool_output(call.call_id, output)
            events.log_tool_skipped(run_state, loop_number, skipped_action)

    def _record_action(self, run_state: RunState, action: ActionRecord) -> None:
        run_state.add_action(action)
        tool = TOOLS.get(action.tool_name)
        tool_effect = tool.effect.value if tool is not None else ToolEffect.READ.value
        self.recovery_store.record_action(
            run_state.run_id,
            action,
            tool_effect=tool_effect,
            plan_id=run_state.plan_id,
            plan_step_id=run_state.plan_step_id,
        )


def _parse_result_object(result: str) -> dict[str, Any] | None:
    return parse_json_object(result)


def _requested_count_from_arguments(arguments: dict[str, Any]) -> int | None:
    limit = arguments.get("limit")
    return limit if isinstance(limit, int) and limit > 0 else None


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


def _history_safe_tool_result(tool_name: str, result_json: str) -> str:
    """Remove ephemeral reference bodies before storing observations long term."""
    if tool_name != "read_skill_reference":
        return result_json
    parsed = parse_json_object(result_json)
    if not isinstance(parsed, dict) or parsed.get("ok") is not True:
        return result_json
    payload = {
        "ok": True,
        "action": "read_skill_reference",
        "skill": parsed.get("skill"),
        "ref_id": parsed.get("ref_id"),
        "path": parsed.get("path"),
        "description": parsed.get("description"),
        "chars": parsed.get("chars"),
        "content_omitted": True,
        "compaction_strategy": "ephemeral_reference",
    }
    return json.dumps(payload, ensure_ascii=False)
