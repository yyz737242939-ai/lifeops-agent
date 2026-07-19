"""Typed RuntimeFactSource for canonical ExecutionFeedback."""

from __future__ import annotations

from app.observability.trace_reader import TraceGraph
from app.observability.trace_vocabulary import SpanLinkType
from app.recovery.errors import ExecutionFeedbackRepositoryError
from app.recovery.ports import ExecutionFeedbackRepository
from app.recovery.models import RecoveryResult
from app.runtime_reporting.models import (
    EvidenceReport,
    FactProjection,
    RuntimeFactBundle,
)


class ExecutionFeedbackFactSource:
    """Project safe feedback facts without parsing events or feedback tables."""

    def __init__(self, repository: ExecutionFeedbackRepository) -> None:
        self._repository = repository

    def load(self, trace: TraceGraph) -> RuntimeFactBundle:
        if not isinstance(trace, TraceGraph):
            raise ValueError("trace must be a TraceGraph.")
        try:
            feedback = self._repository.get_for_run(
                trace.trace.session_id,
                trace.trace.run_id,
            )
        except ExecutionFeedbackRepositoryError:
            return RuntimeFactBundle(
                fact_source_warnings=("execution_feedback_unavailable",)
            )
        if feedback.trace_id != trace.trace.trace_id:
            return RuntimeFactBundle(
                fact_source_warnings=("execution_feedback_trace_conflict",)
            )
        has_artifact = any(
            artifact.artifact_type == "execution_feedback"
            for artifact in trace.artifacts
        )
        warnings = () if has_artifact else ("execution_feedback_artifact_missing",)
        validation = feedback.validation
        if validation is None:
            return RuntimeFactBundle(
                fact_source_warnings=("execution_feedback_validation_missing",)
            )
        projection = FactProjection(
            "execution_feedback",
            feedback.feedback_id,
            feedback.overall_status.value,
            {
                "path": feedback.path.value,
                "action_count": len(feedback.actions),
                "step_count": len(feedback.plan_steps),
                "evidence_count": sum(len(action.evidence) for action in feedback.actions),
                "claim_status": validation.claim_status.value,
                "answer_mode": validation.output_mode.value,
            },
        )
        evidence = tuple(
            FactProjection(
                "execution_feedback_evidence",
                f"{feedback.feedback_id}:{action.sequence}:{item.source_evidence_index}",
                "available",
                {
                    "evidence_type": item.evidence_type,
                    "source_call_id": item.source_call_id,
                    "source_evidence_index": item.source_evidence_index,
                },
            )
            for action in feedback.actions
            for item in action.evidence
        )
        evidence_reports = tuple(
            EvidenceReport(
                "execution_feedback",
                f"{feedback.feedback_id}:{action.sequence}:{item.source_evidence_index}",
                item.reference,
            )
            for action in feedback.actions
            for item in action.evidence
        )
        validation_projection = FactProjection(
            "final_answer_validation",
            f"{feedback.feedback_id}:validation",
            validation.claim_status.value,
            {
                "answer_mode": validation.output_mode.value,
                "reason_count": len(validation.reason_codes),
                "accepted_claim_count": len(validation.accepted_claim_ids),
            },
        )
        stop_attributes: dict[str, object] = {
            "path": feedback.path.value,
            "action_count": len(feedback.actions),
            "step_count": len(feedback.plan_steps),
        }
        for name in ("stop_reason", "error_code", "plan_id", "revision", "stop_step_id"):
            value = getattr(feedback, name)
            if value is not None:
                stop_attributes[name] = value
        stop_point = FactProjection(
            "execution_stop_point",
            f"{feedback.feedback_id}:stop",
            feedback.overall_status.value,
            stop_attributes,
        )
        return RuntimeFactBundle(
            execution_feedback=projection,
            final_answer_validation=validation_projection,
            stop_point=stop_point,
            execution_feedback_evidence=evidence,
            evidence_reports=evidence_reports,
            fact_source_warnings=warnings,
        )


class RecoveryResultFactSource:
    """Project one request-local RecoveryResult into its Recovery trace report."""

    def __init__(self, result: RecoveryResult) -> None:
        if not isinstance(result, RecoveryResult):
            raise ValueError("result must be a RecoveryResult.")
        self._result = result

    def load(self, trace: TraceGraph) -> RuntimeFactBundle:
        if not isinstance(trace, TraceGraph):
            raise ValueError("trace must be a TraceGraph.")
        context = self._result.context
        if trace.trace.session_id != context.session_id:
            return RuntimeFactBundle(
                fact_source_warnings=("recovery_result_session_conflict",)
            )
        has_source_link = any(
            link.link_type is SpanLinkType.RECOVERY_OF
            and link.target_trace_id == context.source_trace_id
            for link in trace.links
        )
        warnings = () if has_source_link else ("recovery_source_link_missing",)
        return RuntimeFactBundle(
            recovery_result=FactProjection(
                "recovery_result",
                f"{trace.trace.run_id}:result",
                context.stop_point.overall_status.value,
                {
                    "source_run_id": context.source_run_id,
                    "path": context.path.value,
                    "recovery_mode": self._result.output_mode.value,
                    "succeeded_action_count": len(context.succeeded_actions),
                    "failed_action_count": len(context.failed_actions),
                    "completed_step_count": len(context.completed_steps),
                    "failed_step_count": len(context.failed_steps),
                    "not_run_step_count": len(context.not_run_steps),
                },
            ),
            fact_source_warnings=warnings,
        )
