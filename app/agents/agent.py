import json
import time
from dataclasses import dataclass
from typing import Any

from app.config import (
    LLM_MAX_OUTPUT_TOKENS,
    LLM_MODEL,
    LLM_TEMPERATURE,
)
from app.agents.action_recorder import ActionRecorder
from app.agents.request_context import RequestLocalContextBuilder
from app.observability import app_log, events, llm_io
from app.prompts.prompt_builder import build_system_prompt
from app.context.context_engine import ContextEngine
from app.context.context_manager import (
    compact_tool_output,
    summarize_context_messages,
)
from app.memory.memory_context import (
    profile_context_message,
    profile_context_report,
    semantic_memory_context_message,
)
from app.memory.memory_retriever import MemoryRetriever
from app.memory.profile_loader import ProfileLoader
from app.tasks.task_context import TaskContextBuilder
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
from app.runtime.recovery_store import RunRecordStore
from app.runtime.recovery_context import RecoveryContextBuilder
from app.runtime.interaction_policy import (
    HighRiskOperation,
    PendingReplyIntent,
    classify_reply_to_pending,
    detect_high_risk_operation,
)
from app.runtime.interaction_state import (
    InteractionState,
    PendingConfirmation,
    PendingConfirmationStatus,
)
from app.runtime.write_policy import (
    authorized_write_tools,
    has_write_success_claim,
    has_recovery_execution_claim,
    requires_bulk_delete_confirmation,
)
from app.skills.skill_loader import discover_skills
from app.skills.skill_router import route_skills
from app.skills.skill_state import resolve_skill_state
from app.tools.capability_builder import SKILL_TOOL_NAMES, build_capabilities
from app.tools.tool import TOOLS, ToolEffect, call_tool
from app.utils.json_file import parse_json_object
from app.utils.llm import client
from app.utils.serialization import json_safe
from app.planning.orchestrator import PlanningOrchestrator
from app.planning.executor_agent import ExecutorAgent, StepExecutionContext
from app.planning.planner_agent import PlannerAgent
from app.planning.plan_types import PlanStep
from app.planning.planning_state import PlanningState


DEFAULT_LOOP_LIMITS = LoopLimits()


@dataclass(frozen=True)
class TurnContext:
    """Prompt and capability snapshot that stays fixed during one user turn."""

    instructions: str
    tool_schemas: tuple[dict[str, Any], ...]
    allowed_tool_names: frozenset[str]
    loaded_skills: tuple[str, ...]
    bulk_delete_confirmation_required: bool
    user_input: str
    confirmed_pending: PendingConfirmation | None = None


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


def _llm_input_diagnostics(messages: list[Any]) -> dict[str, Any]:
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


def _plan_step_user_input(goal: str, step: PlanStep) -> str:
    return (
        "Execute exactly one confirmed plan step.\n"
        f"Plan goal: {goal}\n"
        f"Step title: {step.title}\n"
        f"Step intent: {step.intent}\n"
        "Do not continue to later plan steps in this turn."
    )


def _plan_step_success_answer(answer: str, *, current_plan: Any) -> str:
    if current_plan is None:
        return answer
    next_step = current_plan.current_step
    if current_plan.status == "completed":
        return f"{answer}\n\n计划已完成。"
    if next_step is None:
        return answer
    return (
        f"{answer}\n\n当前 step 已完成。下一步是：{next_step.title}。"
        "请回复“继续”或明确确认后再执行下一步。"
    )


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


def _unique_tuple(items: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(items))


def _skill_owner_for_tool(tool_name: str) -> str | None:
    for skill_name, tool_names in SKILL_TOOL_NAMES.items():
        if tool_name in tool_names:
            return skill_name
    return None


def _confirmed_pending_instructions(pending: PendingConfirmation) -> str:
    payload = {
        "pending_id": pending.id,
        "operation": pending.operation,
        "tool_name": pending.tool_name,
        "scope_summary": pending.scope_summary,
        "arguments": pending.arguments,
    }
    return (
        "\n\nInteraction safety state for this turn:\n"
        "- The user confirmed this pending high-risk operation in the current turn.\n"
        "- Only proceed within the confirmed scope below; do not expand it.\n"
        "- If exact item identifiers are missing, inspect with available read tools or ask a clarifying question.\n"
        "- Do not claim deletion succeeded unless a WRITE tool action succeeds.\n"
        f"- Confirmed pending operation: {json.dumps(payload, ensure_ascii=False)}"
    )


def _authorized_writes_for_turn(
    user_input: str,
    confirmed_pending: PendingConfirmation | None,
) -> frozenset[str]:
    if confirmed_pending is not None:
        if confirmed_pending.tool_name is None:
            return frozenset()
        return frozenset({confirmed_pending.tool_name})

    authorized = set(authorized_write_tools(user_input))
    risky_operation = detect_high_risk_operation(user_input)
    if risky_operation is not None:
        authorized.discard(risky_operation.tool_name)
    return frozenset(authorized)


def _after_turn_safe_tool_result(result_json: str) -> str:
    parsed = parse_json_object(result_json)
    if not isinstance(parsed, dict) or parsed.get("ok") is not True:
        return result_json

    action = parsed.get("action")
    if action == "read_skill_reference":
        return _history_safe_tool_result("read_skill_reference", result_json)
    if action != "fetch_news_source":
        return result_json

    payload = {
        "ok": True,
        "action": "fetch_news_source",
        "skill": parsed.get("skill"),
        "source_id": parsed.get("source_id"),
        "name": parsed.get("name"),
        "url": parsed.get("url"),
        "kind": parsed.get("kind"),
        "fetched_at": parsed.get("fetched_at"),
        "status": parsed.get("status"),
        "content_type": parsed.get("content_type"),
        "chars": parsed.get("chars"),
        "truncated": parsed.get("truncated"),
        "content_omitted": True,
        "compaction_strategy": "ephemeral_source",
    }
    return json.dumps(payload, ensure_ascii=False)


class Agent:
    """Coordinate skill routing, LLM rounds, tools, and per-request RunState."""

    def __init__(
        self,
        *,
        loop_limits: LoopLimits | None = None,
        recovery_store: RunRecordStore | None = None,
        planner_agent: PlannerAgent | None = None,
    ) -> None:
        self.messages: list[Any] = []
        self.skills = discover_skills()
        self.active_skills: tuple[str, ...] = ()
        self.loop_limits = loop_limits or DEFAULT_LOOP_LIMITS
        self.last_run_state: RunState | None = None
        self.context_engine = ContextEngine()
        self.profile_loader = ProfileLoader()
        self.memory_retriever = MemoryRetriever()
        self.task_context_builder = TaskContextBuilder()
        self.interaction_state = InteractionState()
        self.planning_state = PlanningState()
        self.planner_agent = planner_agent or PlannerAgent()
        self.planning_orchestrator = PlanningOrchestrator(
            planning_state=self.planning_state,
            planner_agent=self.planner_agent,
        )
        self.executor_agent = ExecutorAgent(self)
        self.recovery_store = recovery_store or RunRecordStore()
        self.recovery_context_builder = RecoveryContextBuilder(self.recovery_store)
        self.action_recorder = ActionRecorder(
            recovery_store=self.recovery_store,
            append_tool_output=self._append_tool_output,
        )

    def cancel_current_run(self) -> bool:
        """Request cooperative cancellation at the next runtime checkpoint."""
        if self.last_run_state is None:
            return False
        if self.last_run_state.status != RunStatus.RUNNING:
            return False
        self.last_run_state.request_cancel()
        return True

    def compact_context(self) -> str:
        """Manually compact old context and add a soft LLM-written summary."""
        run_state = RunState()
        self.last_run_state = run_state
        events.log_run_started(run_state, self.loop_limits.to_dict())
        events.log_user_input(run_state, "/compact")
        app_log.log_info("Manual context compaction %s started", run_state.run_id)

        first_report = self.context_engine.manual_compact(
            self.messages,
            natural_language_status="pending",
        )
        if not first_report["compacted"]:
            run_state.complete()
            events.log_context_compaction(run_state, first_report)
            events.log_run_completed(run_state)
            return "没有需要压缩的窗口外上下文。"

        natural_summary = None
        natural_status = "failed"
        try:
            natural_summary = self._request_manual_context_summary(run_state)
            natural_status = "generated" if natural_summary else "empty"
        except Exception as exception:
            events.log_llm_failed(
                run_state,
                1,
                run_state.chat_llm_request_count,
                {
                    "type": "manual_context_summary_failed",
                    "message": str(exception),
                },
            )
            app_log.log_warning(
                "Manual context summary failed for %s: %s",
                run_state.run_id,
                exception,
            )

        final_report = self.context_engine.manual_compact(
            self.messages,
            natural_language_summary=natural_summary,
            natural_language_status=natural_status,
        )
        events.log_context_compaction(run_state, final_report)
        run_state.complete()
        events.log_run_completed(run_state)
        return (
            "已完成手动压缩：deterministic summary 已更新，"
            f"LLM natural_language_summary 状态为 {natural_status}。"
        )

    def chat(self, user_input: str) -> str:
        """Execute one user turn and return either an answer or stop summary."""
        self.recovery_store.mark_stale_running_as_interrupted()
        run_state = RunState()
        self.last_run_state = run_state
        self.recovery_store.start_run(
            run_state,
            user_input_summary=user_input,
        )
        events.log_run_started(run_state, self.loop_limits.to_dict())
        events.log_user_input(run_state, user_input)
        app_log.log_info("Run %s started", run_state.run_id)

        pending_before_turn = self.interaction_state.active_pending_confirmation
        self.interaction_state.advance_turn()
        self.planning_state.advance_turn()
        if (
            pending_before_turn is not None
            and pending_before_turn.status == PendingConfirmationStatus.EXPIRED
        ):
            events.log_interaction_pending(
                run_state,
                "expired",
                pending_before_turn,
                current_turn_index=self.interaction_state.turn_index,
                reason="turn_window_expired",
            )
        pending_reply = classify_reply_to_pending(
            user_input,
            self.interaction_state.active_pending_confirmation,
        )
        if pending_reply.intent == PendingReplyIntent.CANCEL:
            cancelled = self.interaction_state.cancel_pending()
            if cancelled is not None:
                events.log_interaction_pending(
                    run_state,
                    "cancelled",
                    cancelled,
                    current_turn_index=self.interaction_state.turn_index,
                    reason=pending_reply.reason,
                )
            return self._complete_interaction_only_run(
                run_state,
                "已取消这次待确认操作，不会执行删除或修改。",
            )
        if pending_reply.intent == PendingReplyIntent.MODIFY:
            pending = self.interaction_state.active_pending_confirmation
            if pending is not None:
                pending.supersede()
                events.log_interaction_pending(
                    run_state,
                    "superseded",
                    pending,
                    current_turn_index=self.interaction_state.turn_index,
                    reason=pending_reply.reason,
                )
            risky_operation = detect_high_risk_operation(user_input)
            if risky_operation is not None:
                return self._create_pending_confirmation_answer(
                    run_state,
                    user_input,
                    risky_operation,
                )
            return self._complete_interaction_only_run(
                run_state,
                "已作废上一次待确认操作。请重新说明要执行的操作和范围。",
            )
        if (
            pending_reply.intent == PendingReplyIntent.ISOLATED_CONFIRM
            and self.planning_state.pending_plan is None
            and self.planning_state.active_plan is None
        ):
            expired_pending = (
                self.interaction_state.pending_confirmation
                if self.interaction_state.pending_confirmation is not None
                and self.interaction_state.pending_confirmation.status
                == PendingConfirmationStatus.EXPIRED
                else None
            )
            answer = (
                "之前等待确认的操作已经过期，请重新说明要执行的操作和范围。"
                if expired_pending is not None
                else "当前没有等待确认的操作，请重新说明要执行什么。"
            )
            return self._complete_interaction_only_run(run_state, answer)

        confirmed_pending = None
        if pending_reply.intent == PendingReplyIntent.CONFIRM:
            confirmed_pending = self.interaction_state.confirm_pending()
            if confirmed_pending is not None:
                events.log_interaction_pending(
                    run_state,
                    "confirmed",
                    confirmed_pending,
                    current_turn_index=self.interaction_state.turn_index,
                    reason=pending_reply.reason,
                )

        if confirmed_pending is None:
            risky_operation = detect_high_risk_operation(user_input)
            if risky_operation is not None:
                return self._create_pending_confirmation_answer(
                    run_state,
                    user_input,
                    risky_operation,
                )

        if confirmed_pending is None:
            planning_result = self.planning_orchestrator.route(user_input)
            if planning_result.execute_current_step:
                return self._execute_active_plan_step(run_state)
            if planning_result.handled:
                return self._complete_interaction_only_run(
                    run_state,
                    planning_result.answer or "",
                )

        turn = self._prepare_turn(
            user_input,
            run_state,
            confirmed_pending=confirmed_pending,
        )
        answer = self._run_agent_loop(run_state, turn)
        if confirmed_pending is not None:
            consumed = self.interaction_state.consume_confirmed_pending()
            if consumed is not None:
                events.log_interaction_pending(
                    run_state,
                    "consumed",
                    consumed,
                    current_turn_index=self.interaction_state.turn_index,
                    reason="agent_loop_finished",
                )
        return answer

    def _execute_active_plan_step(self, run_state: RunState) -> str:
        active_plan = self.planning_state.active_plan
        if active_plan is None or active_plan.current_step is None:
            return self._complete_interaction_only_run(
                run_state,
                "计划已确认，但当前没有可执行步骤。",
            )

        step = active_plan.current_step
        run_state.plan_id = active_plan.plan_id
        run_state.plan_step_id = step.step_id
        step.start()
        step_input = _plan_step_user_input(active_plan.goal, step)
        turn = self._prepare_turn(
            step_input,
            run_state,
            authorization_user_input="",
        )
        result = self.executor_agent.execute_step(
            StepExecutionContext(
                run_state=run_state,
                turn=turn,
                plan_id=active_plan.plan_id,
                plan_step_id=step.step_id,
            )
        )
        if run_state.status == RunStatus.COMPLETED:
            self.planning_state.mark_current_step_done(
                last_run_id=run_state.run_id,
                result_summary=result.answer,
            )
            return _plan_step_success_answer(
                result.answer,
                current_plan=self.planning_state.active_plan,
            )

        failed_step = self.planning_state.mark_current_step_failed(result.answer)
        replan_result = self.planning_orchestrator.replan_after_step_failure(
            failed_plan=active_plan,
            failed_step=failed_step,
            failure_summary=result.answer,
        )
        if replan_result.handled and replan_result.answer:
            return (
                f"{result.answer}\n\n当前 step 执行失败，已生成修订计划等待确认：\n"
                f"{replan_result.answer}"
            )
        if replan_result.answer:
            return f"{result.answer}\n\n当前 step 执行失败，暂时无法生成修订计划：{replan_result.answer}"
        return result.answer

    def _prepare_turn(
        self,
        user_input: str,
        run_state: RunState,
        *,
        confirmed_pending: PendingConfirmation | None = None,
        authorization_user_input: str | None = None,
    ) -> TurnContext:
        """Resolve skills and freeze the prompt/tool boundary for this turn."""
        write_authorization_input = (
            user_input if authorization_user_input is None else authorization_user_input
        )
        routing = route_skills(user_input, self.skills)
        skill_state = resolve_skill_state(
            user_input,
            routing.selected,
            self.active_skills,
        )
        loaded_skills = skill_state.loaded_skills
        next_active_skills = skill_state.next_active_skills
        if confirmed_pending is not None and confirmed_pending.tool_name is not None:
            owner_skill = _skill_owner_for_tool(confirmed_pending.tool_name)
            if owner_skill is not None:
                loaded_skills = _unique_tuple((*loaded_skills, owner_skill))
                next_active_skills = _unique_tuple((*next_active_skills, owner_skill))
        self.active_skills = next_active_skills
        prompt_result = build_system_prompt(
            self.skills,
            loaded_skills,
        )
        authorized_writes = _authorized_writes_for_turn(
            write_authorization_input,
            confirmed_pending,
        )
        bulk_delete_confirmation_required = (
            confirmed_pending is None
            and (
                requires_bulk_delete_confirmation(write_authorization_input)
                or detect_high_risk_operation(write_authorization_input) is not None
            )
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
        if confirmed_pending is not None:
            instructions += _confirmed_pending_instructions(confirmed_pending)
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
            user_input=user_input,
            confirmed_pending=confirmed_pending,
        )

    def _create_pending_confirmation_answer(
        self,
        run_state: RunState,
        user_input: str,
        operation: HighRiskOperation,
    ) -> str:
        self._preserve_skill_state_for_interaction(user_input)
        pending = self.interaction_state.create_pending_confirmation(
            operation=operation.operation,
            tool_name=operation.tool_name,
            risk_level=operation.risk_level,
            scope_summary=operation.scope_summary,
            arguments=operation.arguments,
            source_user_input=user_input,
        )
        events.log_interaction_pending(
            run_state,
            "created",
            pending,
            current_turn_index=self.interaction_state.turn_index,
            reason=operation.reason,
        )
        return self._complete_interaction_only_run(
            run_state,
            (
                f"这是一项高风险操作：{pending.scope_summary}。"
                "请回复“确认”继续，或回复“取消”放弃。"
            ),
        )

    def _complete_interaction_only_run(self, run_state: RunState, answer: str) -> str:
        run_state.complete()
        self.recovery_store.finish_run(run_state)
        events.log_final_answer(run_state, answer)
        events.log_run_completed(run_state)
        app_log.log_info("Run %s completed", run_state.run_id)
        return answer

    def _preserve_skill_state_for_interaction(self, user_input: str) -> None:
        routing = route_skills(user_input, self.skills)
        skill_state = resolve_skill_state(
            user_input,
            routing.selected,
            self.active_skills,
        )
        self.active_skills = skill_state.next_active_skills

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
                user_input=turn.user_input,
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
                self._sanitize_ephemeral_tool_outputs()
                run_state.complete()
                self._record_after_turn_compaction(run_state)
                self.recovery_store.finish_run(run_state)
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
        if (
            has_recovery_execution_claim(answer)
            and not run_state.completed_action_records
        ):
            return (
                "我只能根据 Recovery Context 说明上次停在哪里；"
                "本轮没有成功的 Tool Observation，因此不能确认已经恢复执行。"
            )
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
        user_input: str,
    ) -> Any | None:
        """Call the model with explicit retry accounting and boundary logs."""
        request_context = RequestLocalContextBuilder(
            context_engine=self.context_engine,
            profile_loader=self.profile_loader,
            memory_retriever=self.memory_retriever,
            task_context_builder=self.task_context_builder,
            recovery_context_builder=self.recovery_context_builder,
        ).build(
            messages=self.messages,
            instructions=instructions,
            tool_schemas=tool_schemas,
            user_input=user_input,
        )
        events.log_llm_requested(run_state, loop_number, request_context.diagnostics)
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
                input_messages=request_context.input_messages,
                parameters={
                    "temperature": LLM_TEMPERATURE,
                    "max_output_tokens": LLM_MAX_OUTPUT_TOKENS,
                    **request_context.log_parameters(),
                },
            )
            try:
                return client.responses.create(
                    model=LLM_MODEL,
                    instructions=instructions,
                    input=request_context.input_messages,
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

    def _request_manual_context_summary(self, run_state: RunState) -> str:
        """Use the normal model boundary for a manual context-maintenance task."""
        summary = self.context_engine.store.summary or {}
        instructions = (
            "You are summarizing prior conversation for an agent runtime. "
            "Write a concise natural-language continuity summary. "
            "Do not invent facts. Treat structured fields as the source of truth. "
            "Return plain text only."
        )
        input_messages = [
            {
                "role": "user",
                "content": (
                    "Summarize this deterministic context summary for future "
                    "conversation continuity:\n"
                    + json.dumps(json_safe(summary), ensure_ascii=False, sort_keys=True)
                ),
            }
        ]
        request_number = run_state.start_llm_request()
        events.log_llm_attempted(run_state, 1, request_number, 0)
        llm_io.log_request(
            run_state,
            1,
            request_number,
            model=LLM_MODEL,
            instructions=instructions,
            tools=(),
            input_messages=input_messages,
            parameters={
                "temperature": 0.0,
                "max_output_tokens": LLM_MAX_OUTPUT_TOKENS,
                "purpose": "manual_context_compaction",
            },
        )
        response = client.responses.create(
            model=LLM_MODEL,
            instructions=instructions,
            input=input_messages,
            tools=[],
            temperature=0.0,
            max_output_tokens=LLM_MAX_OUTPUT_TOKENS,
        )
        events.log_llm_responded(run_state, 1, _response_summary(response.output))
        llm_io.log_response(run_state, 1, response)
        output_text = getattr(response, "output_text", None)
        return output_text.strip() if isinstance(output_text, str) else ""

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
        return self.action_recorder.record_tool_result(
            run_state=run_state,
            loop_number=loop_number,
            function_call=function_call,
            arguments=arguments,
            signature=signature,
            idempotency_key=idempotency_key,
            execution=execution,
        )

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
        return self.action_recorder.record_invalid_arguments(
            run_state=run_state,
            loop_number=loop_number,
            function_call=function_call,
            exception=exception,
            calls_started_this_round=calls_started_this_round,
            start_tool_call=lambda: run_state.start_tool_call(
                self.loop_limits,
                calls_started_this_round=calls_started_this_round,
            ),
        )

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
        self.action_recorder.skip_calls(
            run_state=run_state,
            loop_number=loop_number,
            calls=calls,
            error_type=error_type,
            code=code,
            message=message,
        )

    def _append_tool_output(self, call_id: str, output: str) -> None:
        """Append the Responses API observation paired to a function call."""
        self.messages.append(
            {
                "type": "function_call_output",
                "call_id": call_id,
                "output": output,
            }
        )

    def _record_after_turn_compaction(self, run_state: RunState) -> None:
        report = self.context_engine.after_turn(self.messages)
        events.log_context_compaction(run_state, report)

    def _stopped_answer(self, run_state: RunState) -> str:
        """Log and format a controlled runtime stop exactly once."""
        answer = _runtime_stop_answer(run_state)
        self._sanitize_ephemeral_tool_outputs()
        self._record_after_turn_compaction(run_state)
        self.recovery_store.finish_run(run_state)
        events.log_run_stopped(run_state, answer)
        app_log.log_warning(
            "Run %s stopped: %s", run_state.run_id, run_state.stop_reason
        )
        return answer

    def _record_recovery_action(
        self,
        run_state: RunState,
        action: ActionRecord,
    ) -> None:
        tool = TOOLS.get(action.tool_name)
        tool_effect = tool.effect.value if tool is not None else ToolEffect.READ.value
        self.recovery_store.record_action(
            run_state.run_id,
            action,
            tool_effect=tool_effect,
            plan_id=run_state.plan_id,
            plan_step_id=run_state.plan_step_id,
        )

    def _sanitize_ephemeral_tool_outputs(self) -> None:
        for message in self.messages:
            if not isinstance(message, dict):
                continue
            if message.get("type") != "function_call_output":
                continue
            output = message.get("output")
            if not isinstance(output, str):
                continue
            message["output"] = _after_turn_safe_tool_result(output)
