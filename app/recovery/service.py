"""Deterministic read-only Recovery context construction and explanation."""

from __future__ import annotations

from app.common.time import utc_now_iso
from app.observability.logger import LlmInteractionSink, TraceSink
from app.observability.recovery_trace import (
    record_recovery_context_reference,
    record_recovery_of,
)
from app.observability.telemetry import add_span_event, optional_span
from app.observability.trace_vocabulary import LifeOpsSpanKind
from app.recovery.errors import (
    RECOVERY_EXPLAINER_FAILED,
    RECOVERY_SOURCE_UNAVAILABLE,
    ExecutionFeedbackRepositoryError,
)
from app.recovery.models import (
    ExecutionFeedback,
    ExecutionOutcome,
    FeedbackOverallStatus,
    PlanStepOutcome,
    RecoveryContext,
    RecoveryOutputMode,
    RecoveryResult,
    RecoveryStopPoint,
)
from app.recovery.ports import ExecutionFeedbackRepository


class RecoveryContextBuilder:
    """Build immutable explanation input from canonical safe feedback only."""

    def build(self, feedback: ExecutionFeedback) -> RecoveryContext:
        if not isinstance(feedback, ExecutionFeedback):
            raise ValueError("feedback must be ExecutionFeedback.")
        succeeded = tuple(
            item
            for item in feedback.actions
            if item.outcome is ExecutionOutcome.SUCCEEDED
        )
        failed = tuple(
            item
            for item in feedback.actions
            if item.outcome is not ExecutionOutcome.SUCCEEDED
        )
        completed_steps = tuple(
            item
            for item in feedback.plan_steps
            if item.outcome is PlanStepOutcome.COMPLETED
        )
        failed_steps = tuple(
            item
            for item in feedback.plan_steps
            if item.outcome
            not in {PlanStepOutcome.COMPLETED, PlanStepOutcome.NOT_RUN}
        )
        not_run = tuple(
            item
            for item in feedback.plan_steps
            if item.outcome is PlanStepOutcome.NOT_RUN
        )
        evidence = tuple(
            evidence
            for action in feedback.actions
            for evidence in action.evidence
        )
        stop_action = failed[0] if failed else None
        return RecoveryContext(
            source_trace_id=feedback.trace_id,
            source_run_id=feedback.run_id,
            session_id=feedback.session_id,
            goal_summary=feedback.goal_summary,
            path=feedback.path,
            stop_point=RecoveryStopPoint(
                feedback.overall_status,
                feedback.stop_reason,
                feedback.error_code,
                stop_action.call_id if stop_action is not None else None,
                feedback.stop_step_id,
            ),
            succeeded_actions=succeeded,
            failed_actions=failed,
            completed_steps=completed_steps,
            failed_steps=failed_steps,
            not_run_steps=not_run,
            durable_evidence=evidence,
            safe_next_steps=_safe_next_steps(feedback.overall_status),
            generated_at=utc_now_iso(),
        )


class RecoveryService:
    """Explain one session-owned durable run without any execution dependency."""

    def __init__(
        self,
        repository: ExecutionFeedbackRepository,
        *,
        context_builder: RecoveryContextBuilder | None = None,
    ) -> None:
        self._repository = repository
        self._context_builder = context_builder or RecoveryContextBuilder()

    def explain_run(
        self,
        session_id: str,
        run_id: str | None = None,
        *,
        trace: TraceSink | None = None,
        llm_log: LlmInteractionSink | None = None,
    ) -> RecoveryResult:
        del llm_log  # V1 is deliberately deterministic-only.
        with optional_span(
            trace,
            name="recovery.explain",
            kind=LifeOpsSpanKind.RECOVERY,
            attributes={"lifeops.recovery.lookup": "explicit" if run_id else "latest"},
        ) as span:
            try:
                feedback = (
                    self._repository.get_for_run(session_id, run_id)
                    if run_id is not None
                    else self._repository.get_latest(session_id)
                )
                if feedback is None:
                    raise ExecutionFeedbackRepositoryError(
                        "Execution feedback is unavailable.",
                        code=RECOVERY_SOURCE_UNAVAILABLE,
                    )
            except Exception as exc:
                error_code = getattr(exc, "code", None) or RECOVERY_SOURCE_UNAVAILABLE
                span.fail(error_code)
                add_span_event(
                    trace,
                    "recovery.context.failed",
                    {"error_code": error_code},
                )
                raise
            span.set_attributes(
                {
                    "lifeops.recovery.source_run_id": feedback.run_id,
                    "lifeops.recovery.path": feedback.path.value,
                    "lifeops.recovery.status": feedback.overall_status.value,
                }
            )
            record_recovery_of(trace, source_trace_id=feedback.trace_id)
            try:
                context = self._context_builder.build(feedback)
                add_span_event(
                    trace,
                    "recovery.context.loaded",
                    {
                        "source_run_id": feedback.run_id,
                        "path": feedback.path.value,
                        "status": feedback.overall_status.value,
                        "succeeded_action_count": len(context.succeeded_actions),
                        "failed_action_count": len(context.failed_actions),
                        "completed_step_count": len(context.completed_steps),
                        "failed_step_count": len(context.failed_steps),
                        "not_run_step_count": len(context.not_run_steps),
                        "evidence_count": len(context.durable_evidence),
                    },
                )
                record_recovery_context_reference(
                    trace,
                    safe_reference=f"recovery-context/{feedback.run_id}",
                )
                explanation = deterministic_recovery_explanation(context)
                add_span_event(
                    trace,
                    "recovery.explanation.completed",
                    {
                        "source_run_id": feedback.run_id,
                        "recovery_mode": RecoveryOutputMode.DETERMINISTIC.value,
                        "fallback": False,
                    },
                )
                return RecoveryResult(
                    context,
                    explanation,
                    RecoveryOutputMode.DETERMINISTIC,
                )
            except Exception:
                add_span_event(
                    trace,
                    "recovery.explanation.failed",
                    {
                        "source_run_id": feedback.run_id,
                        "error_code": RECOVERY_EXPLAINER_FAILED,
                    },
                )
                raise


def deterministic_recovery_explanation(context: RecoveryContext) -> str:
    if not isinstance(context, RecoveryContext):
        raise ValueError("context must be RecoveryContext.")
    lines = [
        f"上次目标：{context.goal_summary}",
        (
            f"执行路径与停点：{context.path.value} / "
            f"{context.stop_point.overall_status.value}。"
        ),
        "已成功动作：" + _action_list(context.succeeded_actions, succeeded=True),
        "失败或未获准动作：" + _action_list(context.failed_actions, succeeded=False),
        "已完成计划步骤：" + _step_list(context.completed_steps),
        "失败或停止计划步骤：" + _step_list(context.failed_steps),
        "未执行计划步骤：" + _step_list(context.not_run_steps),
        "Durable evidence：" + _evidence_list(context),
        "安全下一步：" + "；".join(context.safe_next_steps),
    ]
    return "\n".join(lines)


def _action_list(actions, *, succeeded: bool) -> str:
    if not actions:
        return "无。"
    return "；".join(
        f"{item.tool_name} ({item.call_id}{'' if succeeded else ', ' + item.outcome.value})"
        for item in actions
    ) + "。"


def _step_list(steps) -> str:
    if not steps:
        return "无。"
    return "；".join(
        f"r{item.revision}/{item.step_id} ({item.outcome.value})" for item in steps
    ) + "。"


def _evidence_list(context: RecoveryContext) -> str:
    if not context.durable_evidence:
        return "无。"
    return "；".join(
        f"{item.evidence_type} ({item.source_call_id})"
        for item in context.durable_evidence
    ) + "。"


def _safe_next_steps(status: FeedbackOverallStatus) -> tuple[str, ...]:
    steps = ["查看并确认以上只读执行事实"]
    if status in {
        FeedbackOverallStatus.PARTIAL,
        FeedbackOverallStatus.FAILED,
        FeedbackOverallStatus.DENIED,
        FeedbackOverallStatus.NOT_RUN,
    }:
        steps.append("如需重试，请发起一个全新的请求并重新经过授权")
    elif status is FeedbackOverallStatus.REQUIRES_CONFIRMATION:
        steps.append("如需继续，请发起一个全新的请求并重新确认")
    else:
        steps.append("如需追加工作，请发起一个全新的请求")
    return tuple(steps)
