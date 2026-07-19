from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from app.observability.file_logs import SessionLogWriter
from app.observability.logger import OptionalLogAppender
from app.observability.telemetry import RequestTelemetry
from app.observability.trace_vocabulary import TraceStatus
from app.planning.models import PlanStepStatus
from app.recovery.errors import ExecutionFeedbackRepositoryError
from app.recovery.models import (
    AnswerOutputMode,
    ClaimStatus,
    ExecutionActionFeedback,
    ExecutionFeedback,
    ExecutionFeedbackEvidence,
    ExecutionOutcome,
    ExecutionPath,
    ExecutionPlanStepFeedback,
    FeedbackOverallStatus,
    FinalAnswerValidation,
    PlanStepOutcome,
    RecoveryOutputMode,
)
from app.recovery.service import RecoveryContextBuilder, RecoveryService
from app.tools.models import ToolEffect


class RecoveryServiceTest(unittest.TestCase):
    def test_planning_partial_explanation_keeps_completed_failed_and_not_run(self) -> None:
        feedback = _partial_feedback()
        service = RecoveryService(_Repository(feedback))

        result = service.explain_run("session_1", "run_source")

        self.assertEqual(result.output_mode, RecoveryOutputMode.DETERMINISTIC)
        self.assertEqual(
            tuple(item.step_id for item in result.context.completed_steps), ("step_1",)
        )
        self.assertEqual(
            tuple(item.step_id for item in result.context.failed_steps), ("step_2",)
        )
        self.assertEqual(
            tuple(item.step_id for item in result.context.not_run_steps), ("step_3",)
        )
        self.assertIn("r1/step_3 (not_run)", result.explanation)
        self.assertIn("发起一个全新的请求并重新经过授权", result.explanation)
        for forbidden in ("allowed_tools", "confirmation", "tool_call", "write_scope"):
            self.assertFalse(hasattr(result.context, forbidden))

    def test_latest_is_session_scoped_and_unknown_fails_closed(self) -> None:
        feedback = _partial_feedback()
        repository = _Repository(feedback)
        service = RecoveryService(repository)

        result = service.explain_run("session_1")
        self.assertEqual(result.context.source_run_id, "run_source")
        self.assertEqual(repository.latest_sessions, ["session_1"])

        with self.assertRaises(ExecutionFeedbackRepositoryError) as caught:
            RecoveryService(_Repository(None)).explain_run("session_other")
        self.assertEqual(caught.exception.code, "recovery_source_unavailable")

    def test_service_trace_has_recovery_link_safe_events_and_no_execution_spans(self) -> None:
        feedback = _partial_feedback()
        with tempfile.TemporaryDirectory() as tmpdir:
            logs = SessionLogWriter.create(tmpdir, session_id="session_1")
            telemetry = RequestTelemetry(
                run_id="recovery_run",
                session_id="session_1",
                turn_id="turn_recovery",
                legacy_sink=OptionalLogAppender(None),
                exporter=logs.trace_exporter,
            )
            result = RecoveryService(_Repository(feedback)).explain_run(
                "session_1", "run_source", trace=telemetry
            )
            telemetry.finish(status=TraceStatus.OK)
            rows = logs.trace_exporter.read_all()

        self.assertEqual(result.context.source_trace_id, "trace_source")
        kinds = {
            row["lifeops_span_kind"]
            for row in rows
            if row["record_type"] == "span"
        }
        self.assertEqual(kinds, {"RUNTIME", "RECOVERY"})
        link = next(row for row in rows if row["record_type"] == "span_link")
        self.assertEqual(link["target_trace_id"], "trace_source")
        self.assertEqual(link["link_type"], "recovery_of")
        serialized = repr(rows)
        self.assertNotIn("private raw output", serialized)
        self.assertNotIn(feedback.goal_summary, serialized)
        self.assertNotIn(feedback.actions[0].evidence[0].summary, serialized)

    def test_service_dependency_graph_has_no_execution_or_authorization_module(self) -> None:
        forbidden = (
            "app.executor",
            "app.policy",
            "app.planning.controller",
            "app.tools.runtime",
            "app.tools.gateway",
            "app.inspector",
            "app.eval",
        )
        tree = ast.parse(Path("app/recovery/service.py").read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        self.assertEqual(
            [
                name
                for name in imports
                if any(name == item or name.startswith(item + ".") for item in forbidden)
            ],
            [],
        )

    def test_unknown_source_emits_safe_recovery_failure_without_guessing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logs = SessionLogWriter.create(tmpdir, session_id="session_1")
            telemetry = RequestTelemetry(
                run_id="recovery_run",
                session_id="session_1",
                turn_id="turn_recovery",
                legacy_sink=OptionalLogAppender(None),
                exporter=logs.trace_exporter,
            )
            with self.assertRaises(ExecutionFeedbackRepositoryError):
                RecoveryService(_Repository(None)).explain_run(
                    "session_1", "unknown_run", trace=telemetry
                )
            telemetry.finish(
                status=TraceStatus.ERROR,
                error_code="recovery_source_unavailable",
            )
            rows = logs.trace_exporter.read_all()

        recovery_span = next(
            row
            for row in rows
            if row["record_type"] == "span"
            and row["lifeops_span_kind"] == "RECOVERY"
        )
        self.assertEqual(recovery_span["status"], "error")
        failure = next(
            row
            for row in rows
            if row["record_type"] == "span_event"
            and row["name"] == "recovery.context.failed"
        )
        self.assertEqual(failure["attributes"]["error_code"], "recovery_source_unavailable")
        self.assertNotIn("unknown_run", repr(rows))


class _Repository:
    def __init__(self, feedback: ExecutionFeedback | None) -> None:
        self.feedback = feedback
        self.latest_sessions: list[str] = []

    def get_for_run(self, session_id: str, run_id: str):
        if (
            self.feedback is None
            or self.feedback.session_id != session_id
            or self.feedback.run_id != run_id
        ):
            raise ExecutionFeedbackRepositoryError(
                "Execution feedback is unavailable.",
                code="recovery_source_unavailable",
            )
        return self.feedback

    def get_latest(self, session_id: str):
        self.latest_sessions.append(session_id)
        if self.feedback is None or self.feedback.session_id != session_id:
            return None
        return self.feedback

    def save(self, feedback: ExecutionFeedback) -> None:
        raise AssertionError("Recovery must never save feedback")


def _partial_feedback() -> ExecutionFeedback:
    evidence = ExecutionFeedbackEvidence(
        "read_result", "One safe source was read.", "artifact/ref_1", "call_1", 0
    )
    actions = (
        ExecutionActionFeedback(
            1, "execinv_1", "span_1", "call_1", "research.read",
            ToolEffect.READ, ExecutionOutcome.SUCCEEDED, evidence=(evidence,),
            plan_revision=1, plan_step_id="step_1",
        ),
        ExecutionActionFeedback(
            2, "execinv_2", "span_2", "call_2", "research.search",
            ToolEffect.EXTERNAL_READ, ExecutionOutcome.FAILED,
            error_code="provider_failed", retryable=True,
            plan_revision=1, plan_step_id="step_2",
        ),
    )
    steps = (
        ExecutionPlanStepFeedback(
            1, "step_1", 1, "Read", "Read complete", PlanStepStatus.COMPLETED,
            PlanStepOutcome.COMPLETED, safe_result_summary="Read complete",
            evidence_refs=("artifact/ref_1",),
        ),
        ExecutionPlanStepFeedback(
            1, "step_2", 2, "Search", "Search complete", PlanStepStatus.STOPPED,
            PlanStepOutcome.FAILED, stop_reason="limit_reached",
            error_code="provider_failed",
        ),
        ExecutionPlanStepFeedback(
            1, "step_3", 3, "Save", "Save complete", PlanStepStatus.PENDING,
            PlanStepOutcome.NOT_RUN,
        ),
    )
    return ExecutionFeedback(
        "feedback_1", "trace_source", "run_source", "session_1",
        ExecutionPath.PLANNING, "Safe summarized goal", FeedbackOverallStatus.PARTIAL,
        "limit_reached", "provider_failed", ("execinv_1", "execinv_2"),
        actions, steps, "2026-07-17T00:00:00Z", plan_id="plan_1", revision=1,
        stop_step_id="step_2",
        validation=FinalAnswerValidation(
            ClaimStatus.INVALID,
            AnswerOutputMode.DETERMINISTIC_FALLBACK,
            ("claim_plan_step_not_completed",),
        ),
    )


if __name__ == "__main__":
    unittest.main()
