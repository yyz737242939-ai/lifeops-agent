"""Main Orchestrator route policy for Plan and Execute v0."""

from dataclasses import dataclass
from enum import StrEnum
import re

from app.planning.plan_types import PlanRun, PlanStep
from app.planning.planner_agent import PlannerAgent, PlannerResult
from app.planning.planning_state import PlanningState
from app.runtime.interaction_policy import detect_high_risk_operation


class PlanningRoute(StrEnum):
    """Deterministic route selected before direct execution."""

    DIRECT_EXECUTE = "direct_execute"
    PLAN_PREVIEW = "plan_preview"
    CONFIRM_PLAN = "confirm_plan"
    EXECUTE_STEP = "execute_step"
    MODIFY_PLAN = "modify_plan"
    CANCEL_PLAN = "cancel_plan"
    CLARIFY = "clarify"
    SAFETY_PENDING = "safety_pending"


@dataclass(frozen=True)
class OrchestratorResult:
    """Result of a planning route decision."""

    route: PlanningRoute
    handled: bool = False
    answer: str | None = None
    execute_current_step: bool = False


class PlanningOrchestrator:
    """Route user turns between direct execution and transient planning."""

    def __init__(
        self,
        *,
        planning_state: PlanningState,
        planner_agent: PlannerAgent,
    ) -> None:
        self.planning_state = planning_state
        self.planner_agent = planner_agent

    def route(self, user_input: str) -> OrchestratorResult:
        text = _normalize(user_input)

        if detect_high_risk_operation(user_input) is not None:
            return OrchestratorResult(route=PlanningRoute.SAFETY_PENDING)

        if self.planning_state.pending_plan is not None:
            if _has_cancel_plan_cue(text):
                plan = self.planning_state.cancel_pending_plan()
                return OrchestratorResult(
                    route=PlanningRoute.CANCEL_PLAN,
                    handled=True,
                    answer=f"已取消计划 `{plan.plan_id}`，不会执行其中任何步骤。",
                )
            if _has_modify_plan_cue(text):
                return self._preview_plan(user_input, route=PlanningRoute.MODIFY_PLAN)
            if _has_confirm_plan_cue(text):
                plan = self.planning_state.confirm_pending_plan()
                current_step = plan.current_step
                current_summary = (
                    f"当前步骤是：{current_step.title}。"
                    if current_step is not None
                    else "当前没有可执行步骤。"
                )
                return OrchestratorResult(
                    route=PlanningRoute.CONFIRM_PLAN,
                    execute_current_step=True,
                    answer=f"已确认计划 `{plan.plan_id}`，计划已进入 active。{current_summary}",
                )

        if self.planning_state.active_plan is not None:
            if _has_cancel_plan_cue(text):
                plan = self.planning_state.cancel_active_plan()
                return OrchestratorResult(
                    route=PlanningRoute.CANCEL_PLAN,
                    handled=True,
                    answer=f"已取消 active 计划 `{plan.plan_id}`，不会继续执行后续步骤。",
                )
            if _has_continue_step_cue(text):
                return OrchestratorResult(
                    route=PlanningRoute.EXECUTE_STEP,
                    execute_current_step=True,
                )

        if _is_ambiguous_request(text):
            return OrchestratorResult(
                route=PlanningRoute.CLARIFY,
                handled=True,
                answer="这个目标还不够明确。请补充要处理的对象、范围和期望结果。",
            )

        if _is_direct_single_turn_request(text):
            return OrchestratorResult(route=PlanningRoute.DIRECT_EXECUTE)

        if _is_complex_planning_request(text):
            return self._preview_plan(user_input, route=PlanningRoute.PLAN_PREVIEW)

        return OrchestratorResult(route=PlanningRoute.DIRECT_EXECUTE)

    def _preview_plan(
        self,
        user_input: str,
        *,
        route: PlanningRoute,
    ) -> OrchestratorResult:
        planner_result = self.planner_agent.plan(goal=user_input)
        if planner_result.output_type != "plan" or planner_result.plan is None:
            return _planner_fallback_result(planner_result)

        plan = self.planning_state.set_pending_plan(planner_result.plan)
        return OrchestratorResult(
            route=route,
            handled=True,
            answer=_format_plan_preview(plan_id=plan.plan_id, planner_result=planner_result),
        )

    def replan_after_step_failure(
        self,
        *,
        failed_plan: PlanRun,
        failed_step: PlanStep,
        failure_summary: str,
    ) -> OrchestratorResult:
        """Create a new pending plan after a step fails, without executing it."""

        replan_goal = _build_replan_goal(
            failed_plan=failed_plan,
            failed_step=failed_step,
            failure_summary=failure_summary,
        )
        return self._preview_plan(replan_goal, route=PlanningRoute.MODIFY_PLAN)


def _planner_fallback_result(planner_result: PlannerResult) -> OrchestratorResult:
    if planner_result.output_type == "need_user":
        return OrchestratorResult(
            route=PlanningRoute.CLARIFY,
            handled=True,
            answer=planner_result.message,
        )
    if planner_result.output_type == "unsafe_or_needs_confirmation":
        return OrchestratorResult(
            route=PlanningRoute.SAFETY_PENDING,
            handled=True,
            answer=planner_result.message,
        )
    return OrchestratorResult(
        route=PlanningRoute.CLARIFY,
        handled=True,
        answer=planner_result.message,
    )


def _format_plan_preview(*, plan_id: str, planner_result: PlannerResult) -> str:
    plan = planner_result.plan
    if plan is None:
        return planner_result.message
    lines = [
        planner_result.message,
        f"计划 `{plan_id}` 等待确认：",
    ]
    for index, step in enumerate(plan.steps, start=1):
        risk = "" if step.risk_level == "low" else f" 风险：{step.risk_level}。"
        confirmation = " 需要确认。" if step.requires_user_confirmation else ""
        lines.append(f"{index}. {step.title}：{step.intent}{risk}{confirmation}")
    lines.append("请回复“确认”启用计划，回复“修改...”调整计划，或回复“取消”放弃。")
    return "\n".join(lines)


def _build_replan_goal(
    *,
    failed_plan: PlanRun,
    failed_step: PlanStep,
    failure_summary: str,
) -> str:
    remaining_steps = [
        f"- {step.title}: {step.intent}"
        for step in failed_plan.steps
        if not step.is_terminal
    ]
    remaining_summary = "\n".join(remaining_steps) or "(none)"
    return (
        "Replan after a failed Plan and Execute step.\n"
        f"Original goal: {failed_plan.goal}\n"
        f"Failed step: {failed_step.title}\n"
        f"Failed step intent: {failed_step.intent}\n"
        f"Failure summary: {failure_summary.strip() or '(none)'}\n"
        f"Remaining unfinished steps:\n{remaining_summary}\n"
        "Create a revised transient plan. Do not claim the failed step succeeded."
    )


def _normalize(user_input: str) -> str:
    return user_input.strip().lower()


def _has_confirm_plan_cue(text: str) -> bool:
    return bool(
        re.search(
            r"^\s*(确认|确定|可以|没问题|按这个计划|就这样|开始)\s*[。.!！]*$"
            r"|\b(?:confirm|confirmed|ok|okay|start|proceed)\b",
            text,
        )
    )


def _has_continue_step_cue(text: str) -> bool:
    return bool(
        re.search(
            r"^\s*(继续|继续执行|执行下一步|下一步|确认|开始)\s*[。.!！]*$"
            r"|\b(?:continue|next|proceed|start)\b",
            text,
        )
    )


def _has_cancel_plan_cue(text: str) -> bool:
    return bool(re.search(r"取消|放弃|不要了|算了|停止|\b(?:cancel|stop|abort)\b", text))


def _has_modify_plan_cue(text: str) -> bool:
    return bool(
        re.search(
            r"修改|调整|改成|改为|换成|补充|重新计划|\b(?:modify|change|revise)\b",
            text,
        )
    )


def _is_ambiguous_request(text: str) -> bool:
    return bool(re.fullmatch(r"(帮我)?(处理|弄|搞|安排|规划)(一下)?[。.!！]?", text))


def _is_direct_single_turn_request(text: str) -> bool:
    return bool(
        re.search(
            r"(?:添加|新增|创建|记录|保存|查看|列出|显示|完成|更新|删除).{0,24}"
            r"(?:待办|todo|任务|task|记忆|memory|消费|expense|预算|budget|心情|睡眠|能量)",
            text,
        )
        or re.search(
            r"(?:add|create|record|save|list|show|complete|update|delete).{0,24}"
            r"(?:todo|task|memory|expense|budget)",
            text,
        )
    )


def _is_complex_planning_request(text: str) -> bool:
    has_plan_cue = bool(
        re.search(
            r"计划|规划|步骤|分步骤|拆解|路线|方案|step(?:s)?|plan|roadmap",
            text,
        )
    )
    has_execution_goal = bool(
        re.search(r"帮我|我要|我想|完成|实现|推进|build|implement|finish", text)
    )
    return has_plan_cue and has_execution_goal
