from __future__ import annotations

import tempfile
import unittest

from app.executor.models import (
    ExecutorResult,
    ExecutorStatus,
    ExecutorStopReason,
    FinalAnswerActionClaim,
    PlanStepExecutionInput,
    ToolObservation,
    FinalAnswerDecision,
)
from app.executor.service import ReactExecutor
from app.observability.file_logs import SessionLogWriter
from app.observability.logger import OptionalLogAppender
from app.observability.telemetry import RequestTelemetry
from app.observability.trace_vocabulary import TraceStatus
from app.planning.models import (
    PlanCommand,
    PlanCommandAction,
    PlanDraft,
    PlanFinalizerOutput,
    PlanRoute,
    PlanRun,
    PlanRunStatus,
    PlanStep,
    PlanStepStatus,
    PlanStepDraft,
    PlanningLimits,
)
from app.planning.controller import PlanController
from app.planning.finalizer import FakePlanFinalizerClient
from app.planning.planner import FakePlannerModelClient
from app.planning.repository import SqlitePlanRepository
from app.planning.router import FakePlanningRouteClient
from app.planning.service import PlanningService
from app.recovery.collector import RequestExecutionFeedbackCollector
from app.recovery.finalizer import RuntimeOutcomeFinalizer
from app.recovery.models import (
    AnswerOutputMode,
    ClaimStatus,
    FeedbackOverallStatus,
    PlanStepOutcome,
    RunGateOutcome,
)
from app.recovery.repository import SqliteExecutionFeedbackRepository
from app.runtime.models import RuntimeRequest, RuntimeResult, RuntimeStatus
from app.runtime.service import RuntimeService
from app.tools.models import (
    ExecutionEvidence,
    ToolCallStatus,
    ToolEffect,
    ToolError,
)
from app.tools.registry import ToolRegistry
from app.tools.runtime import ToolRuntime
from tests.executor_fakes import FakeExecutorModelClient
from tests.helpers import create_test_connection, create_test_skill_service


class RuntimeOutcomeFinalizerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.collector = RequestExecutionFeedbackCollector()
        self.repository = _FeedbackRepository()
        self.request = RuntimeRequest(
            "goal",
            "session_1",
            turn_id="turn_1",
            run_id="run_1",
            created_at="2026-07-17T00:00:00Z",
        )

    def test_direct_finalizes_once_and_discards_request_local_facts(self) -> None:
        observation = _observation("call_1", ToolCallStatus.SUCCEEDED)
        self._collect("execinv_1", "span_1", _completed(observation))
        finalizer = RuntimeOutcomeFinalizer(self.collector, self.repository)

        result = finalizer.finalize(
            self.request,
            _runtime_result("model answer"),
            trace_id="trace_1",
        )

        self.assertEqual(result.message, "model answer")
        self.assertEqual(len(self.repository.saved), 1)
        feedback = self.repository.saved[0]
        self.assertEqual(feedback.trace_id, "trace_1")
        self.assertEqual(feedback.overall_status, FeedbackOverallStatus.COMPLETED)
        self.assertEqual(feedback.validation.claim_status, ClaimStatus.VALID)
        with self.assertRaises(Exception) as caught:
            self.collector.snapshot("run_1")
        self.assertEqual(caught.exception.code, "execution_feedback_source_incomplete")

    def test_feedback_trace_projects_safe_events_and_artifact(self) -> None:
        observation = _observation(
            "call_1",
            ToolCallStatus.SUCCEEDED,
            evidence=(ExecutionEvidence("read", "private evidence summary", None),),
        )
        self._collect("execinv_1", "span_1", _completed(observation))
        with tempfile.TemporaryDirectory() as tmpdir:
            logs = SessionLogWriter.create(tmpdir, session_id="session_1")
            trace = RequestTelemetry(
                run_id="run_1",
                session_id="session_1",
                turn_id="turn_1",
                legacy_sink=OptionalLogAppender(None),
                exporter=logs.trace_exporter,
            )
            result = RuntimeOutcomeFinalizer(self.collector, self.repository).finalize(
                self.request,
                _runtime_result("private assistant answer"),
                trace_id=trace.trace_context.trace_id,
                trace=trace,
            )
            trace.finish(status=TraceStatus.OK)
            rows = logs.trace_exporter.read_all()

        self.assertEqual(result.message, "private assistant answer")
        events = {
            row["name"]
            for row in rows
            if row["record_type"] == "span_event"
        }
        self.assertTrue(
            {
                "execution.feedback.built",
                "execution.final_answer.validated",
                "execution.feedback.persisted",
            }.issubset(events)
        )
        artifact = next(
            row
            for row in rows
            if row["record_type"] == "artifact_reference"
            and row["artifact_type"] == "execution_feedback"
        )
        feedback_span = next(
            row
            for row in rows
            if row["record_type"] == "span"
            and row["name"] == "execution.feedback.finalize"
        )
        self.assertEqual(artifact["span_id"], feedback_span["span_id"])
        serialized = repr(rows)
        self.assertNotIn("private assistant answer", serialized)
        self.assertNotIn("private evidence summary", serialized)

    def test_trace_recorder_failure_does_not_change_canonical_feedback(self) -> None:
        observation = _observation("call_1", ToolCallStatus.SUCCEEDED)
        self._collect("execinv_1", "span_1", _completed(observation))

        result = RuntimeOutcomeFinalizer(self.collector, self.repository).finalize(
            self.request,
            _runtime_result("safe result"),
            trace_id="trace_1",
            trace=_ExplodingTrace(),
        )

        self.assertEqual(result.message, "safe result")
        self.assertEqual(len(self.repository.saved), 1)
        self.assertEqual(
            self.repository.saved[0].overall_status,
            FeedbackOverallStatus.COMPLETED,
        )

    def test_runtime_composition_persists_feedback_before_finishing_run_record(self) -> None:
        conn = create_test_connection()
        collector = RequestExecutionFeedbackCollector()
        repository = SqliteExecutionFeedbackRepository(conn)
        request = RuntimeRequest(
            "hello",
            "session_1",
            turn_id="turn_runtime",
            run_id="run_runtime",
        )
        service = RuntimeService(
            create_test_skill_service(),
            conn=conn,
            execution_scope_factory=lambda: ToolRuntime.from_registry(ToolRegistry()),
            executor=ReactExecutor(
                FakeExecutorModelClient([FinalAnswerDecision("validated draft")]),
                feedback_sink=collector,
            ),
            outcome_finalizer=RuntimeOutcomeFinalizer(collector, repository),
        )
        try:
            result = service.handle(request)
            feedback = repository.get_for_run("session_1", "run_runtime")
            run_row = conn.execute(
                "SELECT status, summary FROM run_records WHERE id = ?",
                ("run_runtime",),
            ).fetchone()
        finally:
            service.close()

        self.assertEqual(result.message, "validated draft")
        self.assertEqual(feedback.run_id, "run_runtime")
        self.assertNotEqual(feedback.goal_summary, request.user_input)
        self.assertTrue(feedback.actions == ())
        self.assertTrue(feedback.executor_invocation_ids[0])
        self.assertEqual(run_row["status"], "ok")
        self.assertEqual(run_row["summary"], "validated draft")

    def test_runtime_plan_command_persists_one_run_level_aggregate(self) -> None:
        conn = create_test_connection()
        plan_repository = SqlitePlanRepository(conn)
        feedback_repository = SqliteExecutionFeedbackRepository(conn)
        collector = RequestExecutionFeedbackCollector()
        limits = PlanningLimits(max_plan_steps=2)
        planner = FakePlannerModelClient(
            PlanDraft((PlanStepDraft("read", 1, "Read", "Read complete"),))
        )
        executor = ReactExecutor(
            FakeExecutorModelClient([FinalAnswerDecision("step complete")]),
            feedback_sink=collector,
        )
        service = RuntimeService(
            create_test_skill_service(),
            conn=conn,
            execution_scope_factory=lambda: ToolRuntime.from_registry(ToolRegistry()),
            executor=executor,
            planning_route_client=FakePlanningRouteClient(PlanRoute("multi_step")),
            planning_service=PlanningService(planner, plan_repository, limits=limits),
            plan_controller=PlanController(
                plan_repository,
                executor,
                limits=limits,
                planner=planner,
                finalizer=FakePlanFinalizerClient(PlanFinalizerOutput("plan complete")),
            ),
            planning_limits=limits,
            outcome_finalizer=RuntimeOutcomeFinalizer(
                collector,
                feedback_repository,
                plan_repository=plan_repository,
            ),
        )
        try:
            preview_request = RuntimeRequest(
                "研究并总结",
                "session_1",
                turn_id="turn_preview",
                run_id="run_preview",
            )
            preview = service.handle(preview_request)
            command_request = RuntimeRequest(
                "研究并总结",
                "session_1",
                turn_id="turn_confirm",
                run_id="run_confirm",
            )
            result = service.handle_plan_command(
                PlanCommand(
                    "command_1",
                    preview.tool_result["plan_id"],
                    "session_1",
                    preview.tool_result["revision"],
                    PlanCommandAction.CONFIRM,
                ),
                command_request,
            )
            feedback = feedback_repository.get_for_run("session_1", "run_confirm")
            count = conn.execute(
                "SELECT COUNT(*) AS count FROM execution_feedback WHERE run_id = 'run_confirm'"
            ).fetchone()["count"]
        finally:
            service.close()

        self.assertEqual(result.message, "plan complete")
        self.assertIs(type(result), RuntimeResult)
        self.assertFalse(hasattr(result, "plan_finalizer_output"))
        self.assertEqual(count, 1)
        self.assertEqual(feedback.plan_id, preview.tool_result["plan_id"])
        self.assertEqual(feedback.overall_status, FeedbackOverallStatus.COMPLETED)
        self.assertEqual(feedback.executor_invocation_ids.__len__(), 1)

    def test_zero_execution_gate_is_durable_without_synthetic_action(self) -> None:
        RuntimeOutcomeFinalizer(self.collector, self.repository).finalize(
            self.request,
            RuntimeResult(
                "run_1",
                "session_1",
                RuntimeStatus.REQUIRES_CONFIRMATION,
                "confirmation required",
            ),
            trace_id="trace_1",
            gate_outcome=RunGateOutcome.REQUIRES_CONFIRMATION,
        )

        feedback = self.repository.saved[0]
        self.assertEqual(
            feedback.overall_status, FeedbackOverallStatus.REQUIRES_CONFIRMATION
        )
        self.assertEqual(feedback.actions, ())
        self.assertEqual(feedback.executor_invocation_ids, ())

    def test_repository_failure_keeps_validated_result_and_discards_collector(self) -> None:
        self._collect("execinv_1", "span_1", _completed())
        finalizer = RuntimeOutcomeFinalizer(
            self.collector, _FailingFeedbackRepository()
        )

        result = finalizer.finalize(
            self.request,
            _runtime_result("safe explanation"),
            trace_id="trace_1",
        )

        self.assertEqual(result.message, "safe explanation")
        with self.assertRaises(Exception):
            self.collector.snapshot("run_1")

    def test_direct_structured_write_claim_requires_matching_evidence(self) -> None:
        evidence = ExecutionEvidence("write_effect", "Saved.", "source/ref_1")
        observation = _observation(
            "call_1",
            ToolCallStatus.SUCCEEDED,
            tool_name="research.save_source",
            evidence=(evidence,),
        )
        result = ExecutorResult(
            "run_1",
            ExecutorStatus.COMPLETED,
            ExecutorStopReason.FINAL_ANSWER,
            "saved",
            2,
            (observation,),
            final_answer_claims=(
                FinalAnswerActionClaim("claim_1", "call_1", ("source/ref_1",)),
            ),
        )
        self._collect(
            "execinv_1", "span_1", result, effect=ToolEffect.WRITE
        )

        finalized = RuntimeOutcomeFinalizer(
            self.collector, self.repository
        ).finalize(
            self.request,
            _runtime_result("saved"),
            trace_id="trace_1",
        )

        self.assertEqual(finalized.message, "saved")
        self.assertEqual(
            self.repository.saved[0].validation.accepted_claim_ids,
            ("claim_1",),
        )

    def test_direct_failed_action_false_success_claim_uses_fallback(self) -> None:
        observation = _observation("call_1", ToolCallStatus.FAILED)
        result = ExecutorResult(
            "run_1",
            ExecutorStatus.COMPLETED,
            ExecutorStopReason.FINAL_ANSWER,
            "false success",
            2,
            (observation,),
            final_answer_claims=(FinalAnswerActionClaim("claim_1", "call_1"),),
        )
        self._collect("execinv_1", "span_1", result)

        finalized = RuntimeOutcomeFinalizer(
            self.collector, self.repository
        ).finalize(
            self.request,
            _runtime_result("false success"),
            trace_id="trace_1",
        )

        self.assertNotEqual(finalized.message, "false success")
        feedback = self.repository.saved[0]
        self.assertEqual(feedback.validation.claim_status, ClaimStatus.INVALID)
        self.assertEqual(
            feedback.validation.output_mode,
            AnswerOutputMode.DETERMINISTIC_FALLBACK,
        )

    def test_planning_completed_validates_finalizer_write_claim(self) -> None:
        step = _step(
            1,
            "save",
            PlanStepStatus.COMPLETED,
            summary="Saved.",
            evidence_refs=("source/ref_1",),
        )
        plan_repository = _PlanRepository(
            PlanRun("plan_1", "session_1", "goal", PlanRunStatus.COMPLETED),
            (step,),
        )
        observation = _observation(
            "call_save",
            ToolCallStatus.SUCCEEDED,
            tool_name="research.save_source",
            evidence=(ExecutionEvidence("write_effect", "Saved.", "source/ref_1"),),
        )
        self._collect(
            "execinv_save",
            "span_save",
            _completed(observation),
            plan_step=_step_input(1, "save"),
            effect=ToolEffect.WRITE,
        )
        finalizer = RuntimeOutcomeFinalizer(
            self.collector,
            self.repository,
            plan_repository=plan_repository,
        )

        result = finalizer.finalize(
            self.request,
            _plan_result("保存完成。", revision=1),
            trace_id="trace_1",
            plan_finalizer_output=PlanFinalizerOutput(
                "保存完成。",
                claims_write_success=True,
                evidence_refs=("source/ref_1",),
            ),
        )

        feedback = self.repository.saved[0]
        self.assertEqual(result.message, "保存完成。")
        self.assertEqual(feedback.validation.claim_status, ClaimStatus.VALID)
        self.assertEqual(
            feedback.validation.accepted_claim_ids,
            ("plan_finalizer:1:save",),
        )
        self.assertEqual(len(feedback.actions), 1)

    def test_planning_partial_aggregates_multiple_invocations_once(self) -> None:
        steps = (
            _step(1, "done", PlanStepStatus.COMPLETED, summary="Done."),
            _step(
                2,
                "failed",
                PlanStepStatus.STOPPED,
                stop_reason=ExecutorStopReason.LIMIT_REACHED.value,
                error_code="executor.limit_reached",
            ),
            _step(3, "pending", PlanStepStatus.PENDING),
        )
        plan_repository = _PlanRepository(
            PlanRun(
                "plan_1",
                "session_1",
                "goal",
                PlanRunStatus.STOPPED,
                last_error_code="executor.limit_reached",
            ),
            steps,
        )
        self._collect(
            "execinv_done",
            "span_done",
            _completed(),
            plan_step=_step_input(1, "done"),
        )
        self._collect(
            "execinv_failed",
            "span_failed",
            ExecutorResult(
                "run_1",
                ExecutorStatus.STOPPED,
                ExecutorStopReason.LIMIT_REACHED,
                None,
                1,
                error_code="executor.limit_reached",
            ),
            plan_step=_step_input(1, "failed"),
        )

        RuntimeOutcomeFinalizer(
            self.collector,
            self.repository,
            plan_repository=plan_repository,
        ).finalize(
            self.request,
            _plan_result("stopped", revision=1, status=RuntimeStatus.ERROR),
            trace_id="trace_1",
        )

        self.assertEqual(len(self.repository.saved), 1)
        feedback = self.repository.saved[0]
        self.assertEqual(feedback.overall_status, FeedbackOverallStatus.PARTIAL)
        self.assertEqual(
            tuple(item.outcome for item in feedback.plan_steps),
            (
                PlanStepOutcome.COMPLETED,
                PlanStepOutcome.FAILED,
                PlanStepOutcome.NOT_RUN,
            ),
        )
        self.assertEqual(
            feedback.executor_invocation_ids,
            ("execinv_done", "execinv_failed"),
        )

    def test_planning_multi_revision_keeps_completed_history(self) -> None:
        old = _step(1, "old", PlanStepStatus.COMPLETED, summary="Old done.")
        current = _step(
            1,
            "current",
            PlanStepStatus.COMPLETED,
            revision=2,
            summary="Current done.",
        )
        plan_repository = _PlanRepository(
            PlanRun(
                "plan_1",
                "session_1",
                "goal",
                PlanRunStatus.COMPLETED,
                current_revision=2,
            ),
            (current,),
            completed=(old, current),
        )
        self._collect(
            "execinv_old",
            "span_old",
            _completed(),
            plan_step=_step_input(1, "old"),
        )
        self._collect(
            "execinv_current",
            "span_current",
            _completed(),
            plan_step=_step_input(2, "current"),
        )

        RuntimeOutcomeFinalizer(
            self.collector,
            self.repository,
            plan_repository=plan_repository,
        ).finalize(
            self.request,
            _plan_result("done", revision=2),
            trace_id="trace_1",
        )

        feedback = self.repository.saved[0]
        self.assertEqual(
            tuple((item.revision, item.step_id) for item in feedback.plan_steps),
            ((1, "old"), (2, "current")),
        )
        self.assertEqual(feedback.overall_status, FeedbackOverallStatus.COMPLETED)

    def test_plan_preview_is_requires_confirmation_and_has_no_execution(self) -> None:
        pending = _step(1, "pending", PlanStepStatus.PENDING)
        plan_repository = _PlanRepository(
            PlanRun(
                "plan_1",
                "session_1",
                "goal",
                PlanRunStatus.AWAITING_CONFIRMATION,
            ),
            (pending,),
        )

        RuntimeOutcomeFinalizer(
            self.collector,
            self.repository,
            plan_repository=plan_repository,
        ).finalize(
            self.request,
            RuntimeResult(
                "run_1",
                "session_1",
                RuntimeStatus.REQUIRES_CONFIRMATION,
                "preview",
                tool_result={"type": "plan_preview", "plan_id": "plan_1", "revision": 1},
            ),
            trace_id="trace_1",
        )

        feedback = self.repository.saved[0]
        self.assertEqual(
            feedback.overall_status, FeedbackOverallStatus.REQUIRES_CONFIRMATION
        )
        self.assertEqual(feedback.actions, ())

    def test_invalid_plan_finalizer_claim_uses_and_persists_fallback(self) -> None:
        step = _step(1, "save", PlanStepStatus.COMPLETED, summary="Saved.")
        plan_repository = _PlanRepository(
            PlanRun("plan_1", "session_1", "goal", PlanRunStatus.COMPLETED),
            (step,),
        )
        self._collect(
            "execinv_save",
            "span_save",
            _completed(),
            plan_step=_step_input(1, "save"),
        )

        result = RuntimeOutcomeFinalizer(
            self.collector,
            self.repository,
            plan_repository=plan_repository,
        ).finalize(
            self.request,
            _plan_result("false write success", revision=1),
            trace_id="trace_1",
            plan_finalizer_output=PlanFinalizerOutput(
                "false write success",
                claims_write_success=True,
                evidence_refs=("unknown/ref",),
            ),
        )

        self.assertNotEqual(result.message, "false write success")
        feedback = self.repository.saved[0]
        self.assertEqual(feedback.validation.claim_status, ClaimStatus.INVALID)
        self.assertEqual(
            feedback.validation.output_mode,
            AnswerOutputMode.DETERMINISTIC_FALLBACK,
        )

    def _collect(
        self,
        invocation_id: str,
        span_id: str,
        result: ExecutorResult,
        *,
        plan_step: PlanStepExecutionInput | None = None,
        effect: ToolEffect = ToolEffect.READ,
    ) -> None:
        for observation in result.observations:
            self.collector.record(
                observation,
                run_id="run_1",
                executor_invocation_id=invocation_id,
                source_span_id=span_id,
                tool_effect=effect,
                plan_step=plan_step,
            )
        self.collector.record(
            result,
            run_id="run_1",
            executor_invocation_id=invocation_id,
            source_span_id=span_id,
            plan_step=plan_step,
        )


class _FeedbackRepository:
    def __init__(self) -> None:
        self.saved = []

    def save(self, feedback) -> None:
        self.saved.append(feedback)

    def get_for_run(self, session_id, run_id):
        raise NotImplementedError

    def get_latest(self, session_id):
        return self.saved[-1] if self.saved else None


class _FailingFeedbackRepository(_FeedbackRepository):
    def save(self, feedback) -> None:
        raise RuntimeError("private repository failure")


class _ExplodingTrace:
    def start_span(self, _input):
        raise RuntimeError("trace exporter failed")

    def end_span(self, _input):
        raise RuntimeError("trace exporter failed")

    def add_event(self, _input):
        raise RuntimeError("trace exporter failed")

    def add_artifact_reference(self, _input):
        raise RuntimeError("trace exporter failed")


class _PlanRepository:
    def __init__(self, run, current, *, completed=()) -> None:
        self.run = run
        self.current = current
        self.completed = completed

    def get_plan(self, session_id, plan_id, *, recover_interrupted=False):
        if session_id != self.run.session_id or plan_id != self.run.plan_id:
            raise ValueError("unknown plan")
        return self.run, self.current

    def list_steps(self, plan_id, revision):
        return self.current

    def list_completed_steps(self, plan_id, through_revision):
        return self.completed or tuple(
            item for item in self.current if item.status is PlanStepStatus.COMPLETED
        )


def _runtime_result(message: str) -> RuntimeResult:
    return RuntimeResult("run_1", "session_1", RuntimeStatus.OK, message)


def _plan_result(
    message: str, *, revision: int, status: RuntimeStatus = RuntimeStatus.OK
) -> RuntimeResult:
    return RuntimeResult(
        "run_1",
        "session_1",
        status,
        message,
        tool_result={"type": "plan_result", "plan_id": "plan_1", "revision": revision},
        error_code="plan_execution_stopped" if status is RuntimeStatus.ERROR else None,
    )


def _observation(
    call_id: str,
    status: ToolCallStatus,
    *,
    tool_name: str = "research.search_knowledge",
    evidence: tuple[ExecutionEvidence, ...] = (),
) -> ToolObservation:
    return ToolObservation(
        1,
        call_id,
        tool_name,
        status,
        error=(ToolError("provider_failed", "safe") if status is ToolCallStatus.FAILED else None),
        evidence=evidence,
    )


def _completed(*observations: ToolObservation) -> ExecutorResult:
    claims = tuple(
        FinalAnswerActionClaim(f"claim_{index}", observation.call_id)
        for index, observation in enumerate(observations, start=1)
        if observation.status is ToolCallStatus.SUCCEEDED
    )
    return ExecutorResult(
        "run_1",
        ExecutorStatus.COMPLETED,
        ExecutorStopReason.FINAL_ANSWER,
        "done",
        len(observations) + 1,
        observations,
        final_answer_claims=claims,
    )


def _step(
    position: int,
    step_id: str,
    status: PlanStepStatus,
    *,
    revision: int = 1,
    summary: str | None = None,
    stop_reason: str | None = None,
    error_code: str | None = None,
    evidence_refs: tuple[str, ...] = (),
) -> PlanStep:
    return PlanStep(
        "plan_1",
        revision,
        step_id,
        position,
        f"objective {step_id}",
        f"outcome {step_id}",
        (),
        status,
        stop_reason=stop_reason,
        safe_result_summary=summary,
        error_code=error_code,
        evidence_refs=evidence_refs,
    )


def _step_input(revision: int, step_id: str) -> PlanStepExecutionInput:
    return PlanStepExecutionInput(
        "plan_1",
        revision,
        step_id,
        "goal",
        f"objective {step_id}",
        f"outcome {step_id}",
    )


if __name__ == "__main__":
    unittest.main()
