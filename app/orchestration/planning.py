"""Planning nodes and result projections for outer runtime composition."""

from __future__ import annotations

from app.context.models import ContextAssembly
from app.context.projection import project_context_contributions
from app.executor.adapters import (
    AssemblyExecutorContextProvider,
    AssemblyExecutorMemoryProvider,
)
from app.observability.logger import LlmInteractionSink, TraceSink
from app.orchestration.state import GraphState, append_graph_path
from app.planning.controller import PlanControlResult, PlanController
from app.planning.models import (
    DirectRoute,
    NeedUserRoute,
    PlanCommand,
    PlanCommandAction,
    PlanPreview,
    PlanRoute,
    PlannerInput,
    PlannerNeedUser,
    PlanningLimits,
    PlanningRouteInput,
)
from app.planning.ports import PlanningRouteClient
from app.planning.service import PlanningService
from app.runtime.models import RuntimeRequest, RuntimeResult, RuntimeStatus
from app.tools.authorization import resolve_allowed_tools
from app.tools.runtime import ToolRuntime


def route_planning(
    state: GraphState,
    *,
    execution_scope: ToolRuntime,
    route_client: PlanningRouteClient,
    planning_service: PlanningService,
    limits: PlanningLimits,
    trace: TraceSink | None = None,
    llm_log: LlmInteractionSink | None = None,
    context_assembly: ContextAssembly | None = None,
) -> GraphState:
    """Select direct/plan/need-user after authorization and Skill preparation."""

    updated = dict(state)
    updated["graph_path"] = append_graph_path(state["graph_path"], "route_planning")
    request = state["request"]
    intent = state["intent"]
    policy = state["policy"]
    selection = state["skill_selection"]
    if intent is None or policy is None or selection is None:
        raise ValueError("intent, policy, and Skill selection must precede planning route.")
    allowed_tools = resolve_allowed_tools(
        selection.selected_skill_ids, policy, execution_scope.registry
    )
    catalog = execution_scope.registry.model_catalog(allowed_tools.tool_names)
    try:
        decision = route_client.decide(
            PlanningRouteInput(
                goal=request.user_input,
                intent_summary=intent.intent_type.value,
                prompt_contributions=tuple(state["prompt_contributions"]),
                tool_catalog=catalog,
                limits=limits,
                context_contributions=(
                    project_context_contributions(context_assembly)
                ),
            ),
            llm_log=llm_log,
        )
        updated["planning_route"] = decision
        if trace is not None:
            trace.append(
                "planning.route.selected",
                {"route": _route_name(decision)},
            )
        if isinstance(decision, PlanRoute):
            preview = planning_service.create_preview(
                request.session_id,
                _planner_input(
                    request,
                    state,
                    catalog,
                    limits,
                    context_assembly=context_assembly,
                ),
                llm_log=llm_log,
            )
            if isinstance(preview, PlannerNeedUser):
                updated["planning_route"] = NeedUserRoute(preview.question)
                updated["result"] = _need_user_result(request, preview.question)
            else:
                updated["result"] = runtime_result_from_preview(request, preview)
                if trace is not None:
                    trace.append(
                        "plan.preview.created",
                        {
                            "plan_id": preview.run.plan_id,
                            "revision": preview.run.current_revision,
                            "status": preview.run.status.value,
                            "step_count": len(preview.steps),
                        },
                    )
        elif isinstance(decision, NeedUserRoute):
            updated["result"] = _need_user_result(request, decision.question)
        elif not isinstance(decision, DirectRoute):
            raise ValueError("planning route decision is invalid.")
    except Exception as exc:
        updated["error_code"] = getattr(exc, "code", None) or "planning_route_failed"
        updated["error_stage"] = "planning"
        updated["result"] = RuntimeResult(
            request.run_id,
            request.session_id,
            RuntimeStatus.ERROR,
            "Planning failed.",
            error_code=updated["error_code"],
        )
    return updated  # type: ignore[return-value]


def execute_plan_command(
    state: GraphState,
    command: PlanCommand,
    *,
    execution_scope: ToolRuntime,
    planning_service: PlanningService,
    controller: PlanController,
    limits: PlanningLimits,
    trace: TraceSink | None = None,
    llm_log: LlmInteractionSink | None = None,
    context_assembly: ContextAssembly | None = None,
) -> GraphState:
    """Apply one revision-bound command using the already prepared request scope."""

    updated = dict(state)
    updated["graph_path"] = append_graph_path(state["graph_path"], "plan_command")
    request = state["request"]
    current = planning_service.get_preview(command.session_id, command.plan_id)
    if request.user_input != current.run.goal or request.session_id != command.session_id:
        raise ValueError("plan command request does not match the durable plan.")
    intent = state["intent"]
    policy = state["policy"]
    selection = state["skill_selection"]
    if intent is None or policy is None or selection is None:
        raise ValueError("plan command requires prepared intent, policy, and Skills.")
    allowed_tools = resolve_allowed_tools(
        selection.selected_skill_ids, policy, execution_scope.registry
    )
    catalog = execution_scope.registry.model_catalog(allowed_tools.tool_names)
    planner_input = _planner_input(
        request,
        state,
        catalog,
        limits,
        confirmed_constraints=current.run.confirmed_constraints,
        context_assembly=context_assembly,
    )
    if trace is not None:
        trace.append(
            "plan.command.received",
            {
                "plan_id": command.plan_id,
                "revision": command.revision,
                "action": command.action.value,
            },
        )
    if command.action == PlanCommandAction.CONFIRM:
        result = controller.confirm_and_execute(
            command,
            request,
            tuple(state["prompt_contributions"]),
            allowed_tools,
            execution_scope,
            planner_input=planner_input,
            trace=trace,
            llm_log=llm_log,
            context_provider=(
                AssemblyExecutorContextProvider(context_assembly)
                if context_assembly
                else None
            ),
            memory_provider=(
                AssemblyExecutorMemoryProvider(context_assembly)
                if context_assembly
                else None
            ),
        )
        updated["result"] = runtime_result_from_control(request, result)
        if trace is not None:
            trace.append(
                "plan.command.applied",
                {
                    "plan_id": result.run.plan_id,
                    "revision": result.run.current_revision,
                    "status": result.run.status.value,
                },
            )
    elif command.action == PlanCommandAction.CANCEL:
        cancelled = planning_service.cancel(command)
        updated["result"] = runtime_result_from_control(
            request, PlanControlResult(cancelled.run, cancelled.steps)
        )
    else:
        modified = planning_service.modify_preview(
            command, planner_input, llm_log=llm_log
        )
        if isinstance(modified, PlannerNeedUser):
            updated["result"] = _need_user_result(request, modified.question)
        else:
            updated["result"] = runtime_result_from_preview(request, modified)
            if trace is not None:
                trace.append(
                    "plan.revision.created",
                    {
                        "plan_id": modified.run.plan_id,
                        "revision": modified.run.current_revision,
                        "status": modified.run.status.value,
                        "step_count": len(modified.steps),
                    },
                )
    return updated  # type: ignore[return-value]


def runtime_result_from_preview(
    request: RuntimeRequest, preview: PlanPreview
) -> RuntimeResult:
    return RuntimeResult(
        request.run_id,
        request.session_id,
        RuntimeStatus.REQUIRES_CONFIRMATION,
        "Plan preview requires confirmation.",
        tool_result={
            "type": "plan_preview",
            "plan_id": preview.run.plan_id,
            "revision": preview.run.current_revision,
            "plan_status": preview.run.status.value,
            "goal": preview.run.goal,
            "steps": [
                {
                    "step_id": item.step_id,
                    "position": item.position,
                    "objective": item.objective,
                    "expected_outcome": item.expected_outcome,
                    "dependency_step_ids": list(item.dependency_step_ids),
                    "status": item.status.value,
                }
                for item in preview.steps
            ],
        },
    )


def runtime_result_from_control(
    request: RuntimeRequest, result: PlanControlResult
) -> RuntimeResult:
    if result.run.status.value == "completed":
        status = RuntimeStatus.OK
        message = result.final_message or "Plan completed."
        error_code = None
    elif result.run.status.value in {"awaiting_confirmation", "awaiting_replan_confirmation"}:
        return runtime_result_from_preview(request, PlanPreview(result.run, result.steps))
    elif result.run.status.value == "cancelled":
        status = RuntimeStatus.OK
        message = "Plan cancelled."
        error_code = None
    elif result.run.last_error_code in {
        "confirmation_required",
        "executor.confirmation_required",
    }:
        status = RuntimeStatus.REQUIRES_CONFIRMATION
        message = "Tool action requires confirmation."
        error_code = None
    else:
        status = RuntimeStatus.ERROR
        message = "Plan execution stopped."
        error_code = result.run.last_error_code or "plan_execution_stopped"
    return RuntimeResult(
        request.run_id,
        request.session_id,
        status,
        message,
        tool_result={
            "type": "plan_result",
            "plan_id": result.run.plan_id,
            "revision": result.run.current_revision,
            "plan_status": result.run.status.value,
        },
        error_code=error_code,
    )


def _planner_input(
    request: RuntimeRequest,
    state: GraphState,
    catalog: tuple[dict[str, object], ...],
    limits: PlanningLimits,
    *,
    confirmed_constraints: tuple[str, ...] = (),
    context_assembly: ContextAssembly | None = None,
) -> PlannerInput:
    return PlannerInput(
        goal=request.user_input,
        prompt_contributions=tuple(state["prompt_contributions"]),
        tool_catalog=catalog,
        limits=limits,
        confirmed_constraints=confirmed_constraints,
        context_contributions=(
            project_context_contributions(context_assembly)
        ),
    )


def _need_user_result(request: RuntimeRequest, question: str) -> RuntimeResult:
    return RuntimeResult(
        request.run_id,
        request.session_id,
        RuntimeStatus.REQUIRES_CONFIRMATION,
        question,
        tool_result={"type": "planning_clarification"},
    )


def _route_name(decision: object) -> str:
    if isinstance(decision, DirectRoute):
        return "direct"
    if isinstance(decision, PlanRoute):
        return "plan"
    if isinstance(decision, NeedUserRoute):
        return "need_user"
    raise ValueError("planning route decision is invalid.")
