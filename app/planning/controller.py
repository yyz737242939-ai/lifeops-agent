"""LifeOps-owned serial controller for one confirmed PlanRun."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.executor.models import (
    ExecutorResult,
    ExecutorStatus,
    ExecutorStopReason,
    PlanStepDependencyResult,
    PlanStepExecutionInput,
)
from app.observability.logger import LlmInteractionSink, TraceSink
from app.planning.errors import PlanContractError, PlanningError
from app.planning.finalizer import deterministic_finalizer_fallback
from app.planning.lifecycle import is_replan_eligible, remaining_step_limit
from app.planning.models import (
    PlanCommand,
    PlanCommandAction,
    PlanDraft,
    PlanFinalizerInput,
    PlanFinalizerOutput,
    PlanFinalizerStepResult,
    PlanRun,
    PlanRunStatus,
    PlanStep,
    PlanStepStatus,
    PlanningLimits,
    PlannerInput,
    PlannerNeedUser,
    ReplanInput,
)
from app.planning.ports import (
    PlanFinalizerClient,
    PlannerModelClient,
    PlanRepository,
    PlanStepExecutor,
)
from app.runtime.models import RuntimeRequest
from app.skills.models import PromptContribution
from app.tools.models import AllowedToolSet, ToolEffect
from app.tools.runtime import ToolRuntime


@dataclass
class PlanExecutionContext:
    """Request-local handoff state; never persisted or copied to outer GraphState."""

    plan_id: str
    revision: int
    tool_runtime: ToolRuntime
    allowed_tools: AllowedToolSet
    prompt_contributions: tuple[PromptContribution, ...]
    dependency_results_by_step: dict[str, PlanStepDependencyResult] = field(
        default_factory=dict
    )
    total_executor_steps_used: int = 0

    def __post_init__(self) -> None:
        if not self.plan_id.strip():
            raise ValueError("plan_id must be non-empty.")
        if not isinstance(self.revision, int) or isinstance(self.revision, bool) or self.revision < 1:
            raise ValueError("revision must be a positive integer.")
        if not isinstance(self.tool_runtime, ToolRuntime):
            raise ValueError("tool_runtime must be ToolRuntime.")
        if not isinstance(self.allowed_tools, AllowedToolSet):
            raise ValueError("allowed_tools must be AllowedToolSet.")
        if not isinstance(self.prompt_contributions, tuple) or any(
            not isinstance(item, PromptContribution) for item in self.prompt_contributions
        ):
            raise ValueError("prompt_contributions must contain PromptContribution values.")
        if not isinstance(self.dependency_results_by_step, dict) or any(
            not isinstance(key, str) or not isinstance(value, PlanStepDependencyResult)
            for key, value in self.dependency_results_by_step.items()
        ):
            raise ValueError("dependency_results_by_step is invalid.")
        if (
            not isinstance(self.total_executor_steps_used, int)
            or isinstance(self.total_executor_steps_used, bool)
            or self.total_executor_steps_used < 0
        ):
            raise ValueError("total_executor_steps_used must be non-negative.")


@dataclass(frozen=True)
class PlanControlResult:
    run: PlanRun
    steps: tuple[PlanStep, ...]
    final_message: str | None = None
    used_finalizer_fallback: bool = False


class PlanController:
    def __init__(
        self,
        repository: PlanRepository,
        executor: PlanStepExecutor,
        *,
        limits: PlanningLimits | None = None,
        planner: PlannerModelClient | None = None,
        finalizer: PlanFinalizerClient | None = None,
    ) -> None:
        self._repository = repository
        self._executor = executor
        self._limits = limits or PlanningLimits()
        self._planner = planner
        self._finalizer = finalizer

    def confirm_and_execute(
        self,
        command: PlanCommand,
        request: RuntimeRequest,
        prompt_contributions: tuple[PromptContribution, ...],
        allowed_tools: AllowedToolSet,
        execution_scope: ToolRuntime,
        *,
        planner_input: PlannerInput | None = None,
        trace: TraceSink | None = None,
        llm_log: LlmInteractionSink | None = None,
    ) -> PlanControlResult:
        if command.action != PlanCommandAction.CONFIRM:
            raise PlanContractError("Controller requires a confirm command.", code="plan_contract_invalid")
        before, _ = self._repository.get_plan(command.session_id, command.plan_id)
        if before.status not in {
            PlanRunStatus.AWAITING_CONFIRMATION,
            PlanRunStatus.AWAITING_REPLAN_CONFIRMATION,
        }:
            run, steps = self._repository.apply_command(command)
            return PlanControlResult(run, steps)
        run, _ = self._repository.apply_command(command)
        context = PlanExecutionContext(
            plan_id=run.plan_id,
            revision=run.current_revision,
            tool_runtime=execution_scope,
            allowed_tools=allowed_tools,
            prompt_contributions=prompt_contributions,
            total_executor_steps_used=run.executor_steps_used,
        )
        return self._execute_running_plan(
            run,
            request,
            context,
            planner_input=planner_input,
            trace=trace,
            llm_log=llm_log,
        )

    def _execute_running_plan(
        self,
        run: PlanRun,
        request: RuntimeRequest,
        context: PlanExecutionContext,
        *,
        planner_input: PlannerInput | None,
        trace: TraceSink | None,
        llm_log: LlmInteractionSink | None,
    ) -> PlanControlResult:
        while True:
            step_limit = remaining_step_limit(run, self._limits)
            if step_limit < 1:
                stopped = self._repository.finish_plan(
                    run.session_id,
                    run.plan_id,
                    run.current_revision,
                    PlanRunStatus.STOPPED,
                    error_code="plan_budget_exhausted",
                )
                self._trace_stop(trace, stopped, "plan_budget_exhausted")
                return PlanControlResult(
                    stopped,
                    self._repository.list_steps(stopped.plan_id, stopped.current_revision),
                )
            step = self._repository.claim_ready_step(
                run.session_id, run.plan_id, run.current_revision
            )
            if step is None:
                steps = self._repository.list_steps(run.plan_id, run.current_revision)
                if steps and all(item.status == PlanStepStatus.COMPLETED for item in steps):
                    completed = self._repository.finish_plan(
                        run.session_id,
                        run.plan_id,
                        run.current_revision,
                        PlanRunStatus.COMPLETED,
                    )
                    completed_history = self._repository.list_completed_steps(
                        completed.plan_id, completed.current_revision
                    )
                    if trace is not None:
                        trace.append(
                            "plan.finalize.started",
                            {
                                "plan_id": completed.plan_id,
                                "revision": completed.current_revision,
                                "step_count": len(completed_history),
                            },
                        )
                    final_output, used_fallback = self._finalize(
                        completed, completed_history, llm_log=llm_log
                    )
                    if trace is not None:
                        trace.append(
                            "plan.finalize.completed",
                            {
                                "plan_id": completed.plan_id,
                                "revision": completed.current_revision,
                                "used_fallback": used_fallback,
                                "evidence_count": len(final_output.evidence_refs),
                            },
                        )
                    return PlanControlResult(
                        completed,
                        steps,
                        final_message=final_output.message,
                        used_finalizer_fallback=used_fallback,
                    )
                stopped = self._repository.finish_plan(
                    run.session_id,
                    run.plan_id,
                    run.current_revision,
                    PlanRunStatus.STOPPED,
                    error_code="plan_dependency_invalid",
                )
                self._trace_stop(trace, stopped, "plan_dependency_invalid")
                return PlanControlResult(stopped, steps)
            dependency_results = self._dependency_results(step, context)
            if trace is not None:
                trace.append(
                    "plan.step.started",
                    {
                        "plan_id": run.plan_id,
                        "revision": run.current_revision,
                        "step_id": step.step_id,
                        "position": step.position,
                        "max_steps": step_limit,
                    },
                )
            result = self._executor.execute_step(
                request,
                PlanStepExecutionInput(
                    plan_id=run.plan_id,
                    revision=run.current_revision,
                    step_id=step.step_id,
                    plan_goal=run.goal,
                    current_objective=step.objective,
                    expected_outcome=step.expected_outcome,
                    dependency_results=dependency_results,
                    max_steps=step_limit,
                ),
                context.prompt_contributions,
                context.allowed_tools,
                context.tool_runtime,
                trace,
                llm_log,
            )
            run, saved_step = self._record_result(run, step, result, context)
            if trace is not None:
                trace.append(
                    "plan.step.finished",
                    {
                        "plan_id": run.plan_id,
                        "revision": run.current_revision,
                        "step_id": saved_step.step_id,
                        "position": saved_step.position,
                        "status": saved_step.status.value,
                        "executor_steps_used": saved_step.executor_steps_used,
                        "evidence_count": len(saved_step.evidence_refs),
                        "error_code": saved_step.error_code,
                    },
                )
            if saved_step.status == PlanStepStatus.COMPLETED:
                context.dependency_results_by_step[saved_step.step_id] = (
                    PlanStepDependencyResult(
                        saved_step.step_id,
                        saved_step.safe_result_summary or saved_step.expected_outcome,
                        result.observations,
                    )
                )
                context.total_executor_steps_used = run.executor_steps_used
                continue
            replanned = self._try_replan(
                run,
                saved_step,
                planner_input,
                trace=trace,
                llm_log=llm_log,
            )
            if replanned is not None:
                return replanned
            terminal = (
                PlanRunStatus.FAILED
                if saved_step.status == PlanStepStatus.FAILED
                else PlanRunStatus.STOPPED
            )
            finished = self._repository.finish_plan(
                run.session_id,
                run.plan_id,
                run.current_revision,
                terminal,
                error_code=self._terminal_error_code(run, saved_step),
            )
            self._trace_stop(trace, finished, finished.last_error_code)
            return PlanControlResult(
                finished,
                self._repository.list_steps(finished.plan_id, finished.current_revision),
            )

    def _try_replan(
        self,
        run: PlanRun,
        failed_step: PlanStep,
        planner_input: PlannerInput | None,
        *,
        trace: TraceSink | None,
        llm_log: LlmInteractionSink | None,
    ) -> PlanControlResult | None:
        if not is_replan_eligible(run, failed_step, self._limits):
            return None
        if self._planner is None or planner_input is None:
            return None
        if planner_input.limits != self._limits or planner_input.goal != run.goal:
            raise PlanContractError(
                "Replan input does not match the confirmed plan.",
                code="plan_contract_invalid",
            )
        old_steps = self._repository.list_steps(run.plan_id, run.current_revision)
        completed = tuple(
            item for item in old_steps if item.status == PlanStepStatus.COMPLETED
        )
        try:
            result = self._planner.replan(
                ReplanInput(
                    planner_input=planner_input,
                    completed_steps=completed,
                    failed_step=failed_step,
                    confirmed_constraints=planner_input.confirmed_constraints,
                ),
                llm_log=llm_log,
            )
        except PlanningError as exc:
            return self._stop_replan_failure(run, old_steps, exc.code, trace)
        if isinstance(result, PlannerNeedUser):
            stopped = self._repository.finish_plan(
                run.session_id,
                run.plan_id,
                run.current_revision,
                PlanRunStatus.STOPPED,
                error_code="planning_clarification_required",
            )
            return PlanControlResult(stopped, old_steps)
        if not isinstance(result, PlanDraft):
            return self._stop_replan_failure(
                run, old_steps, "plan_contract_invalid", trace
            )
        completed_ids = {item.step_id for item in completed}
        if completed_ids & {item.step_id for item in result.steps}:
            return self._stop_replan_failure(
                run, old_steps, "plan_contract_invalid", trace
            )
        replanned_run, replanned_steps = self._repository.create_replan_revision(
            session_id=run.session_id,
            plan_id=run.plan_id,
            expected_revision=run.current_revision,
            draft=result,
            limits=self._limits,
        )
        if trace is not None:
            trace.append(
                "plan.replan.created",
                {
                    "plan_id": replanned_run.plan_id,
                    "from_revision": run.current_revision,
                    "revision": replanned_run.current_revision,
                    "step_count": len(replanned_steps),
                    "replan_count": replanned_run.replan_count,
                },
            )
        return PlanControlResult(replanned_run, replanned_steps)

    def _stop_replan_failure(
        self,
        run: PlanRun,
        steps: tuple[PlanStep, ...],
        error_code: str,
        trace: TraceSink | None,
    ) -> PlanControlResult:
        stopped = self._repository.finish_plan(
            run.session_id,
            run.plan_id,
            run.current_revision,
            PlanRunStatus.STOPPED,
            error_code=error_code,
        )
        self._trace_stop(trace, stopped, error_code)
        return PlanControlResult(stopped, steps)

    def _finalize(
        self,
        run: PlanRun,
        steps: tuple[PlanStep, ...],
        *,
        llm_log: LlmInteractionSink | None,
    ) -> tuple[PlanFinalizerOutput, bool]:
        finalizer_input = PlanFinalizerInput(
            goal=run.goal,
            revision=run.current_revision,
            step_results=tuple(
                PlanFinalizerStepResult(
                    step_id=item.step_id,
                    position=position,
                    status=item.status,
                    safe_result_summary=item.safe_result_summary,
                    stop_reason=item.stop_reason,
                    error_code=item.error_code,
                    evidence_refs=item.evidence_refs,
                )
                for position, item in enumerate(steps, start=1)
            ),
        )
        if self._finalizer is not None:
            try:
                return self._finalizer.finalize(
                    finalizer_input, llm_log=llm_log
                ), False
            except Exception:
                pass
        return deterministic_finalizer_fallback(finalizer_input), True

    @staticmethod
    def _trace_stop(
        trace: TraceSink | None, run: PlanRun, error_code: str | None
    ) -> None:
        if trace is not None:
            trace.append(
                "plan.stopped",
                {
                    "plan_id": run.plan_id,
                    "revision": run.current_revision,
                    "status": run.status.value,
                    "error_code": error_code,
                },
            )

    def _terminal_error_code(self, run: PlanRun, step: PlanStep) -> str | None:
        if step.status in {PlanStepStatus.GOAL_NOT_ACHIEVED, PlanStepStatus.STOPPED}:
            if run.executor_steps_used >= self._limits.max_total_executor_steps:
                return "plan_budget_exhausted"
            if (
                step.status == PlanStepStatus.GOAL_NOT_ACHIEVED
                or step.stop_reason == "limit_reached"
            ) and run.replan_count >= self._limits.max_replans:
                return "plan_replan_exhausted"
        return step.error_code or step.stop_reason

    def _dependency_results(
        self, step: PlanStep, context: PlanExecutionContext
    ) -> tuple[PlanStepDependencyResult, ...]:
        try:
            return tuple(
                context.dependency_results_by_step[step_id]
                for step_id in step.dependency_step_ids
            )
        except KeyError as exc:
            raise PlanContractError(
                "Declared dependency result is unavailable.",
                code="plan_dependency_invalid",
            ) from exc

    def _record_result(
        self,
        run: PlanRun,
        step: PlanStep,
        result: ExecutorResult,
        context: PlanExecutionContext,
    ) -> tuple[PlanRun, PlanStep]:
        evidence_refs = tuple(
            evidence.reference
            for observation in result.observations
            for evidence in observation.evidence
            if evidence.reference is not None
        )
        used_write = any(
            context.tool_runtime.registry.contains(observation.tool_name)
            and context.tool_runtime.registry.get(observation.tool_name).effect
            == ToolEffect.WRITE
            for observation in result.observations
        )
        if (
            result.status == ExecutorStatus.COMPLETED
            and result.stop_reason == ExecutorStopReason.FINAL_ANSWER
            and (not used_write or evidence_refs)
        ):
            status = PlanStepStatus.COMPLETED
            safe_summary = f"Completed: {step.expected_outcome}"
            stop_reason = None
            error_code = None
        elif result.stop_reason == ExecutorStopReason.GOAL_NOT_ACHIEVED:
            status = PlanStepStatus.GOAL_NOT_ACHIEVED
            safe_summary = None
            stop_reason = result.stop_reason.value
            error_code = result.error_code or "plan_step_goal_not_achieved"
        elif result.status == ExecutorStatus.FAILED:
            status = PlanStepStatus.FAILED
            safe_summary = None
            stop_reason = result.stop_reason.value
            error_code = result.error_code or "executor_failed"
        else:
            status = PlanStepStatus.STOPPED
            safe_summary = None
            stop_reason = result.stop_reason.value
            error_code = (
                "plan_write_evidence_missing"
                if result.status == ExecutorStatus.COMPLETED and used_write and not evidence_refs
                else result.error_code or f"executor.{result.stop_reason.value}"
            )
        return self._repository.record_step_result(
            session_id=run.session_id,
            plan_id=run.plan_id,
            revision=run.current_revision,
            step_id=step.step_id,
            status=status,
            executor_steps_used=result.step_count,
            limits=self._limits,
            safe_result_summary=safe_summary,
            stop_reason=stop_reason,
            error_code=error_code,
            evidence_refs=evidence_refs,
        )
