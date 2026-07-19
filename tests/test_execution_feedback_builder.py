from __future__ import annotations

import unittest

from app.executor.models import (
    ExecutorResult,
    ExecutorStatus,
    ExecutorStopReason,
    ToolObservation,
)
from app.planning.models import PlanRun, PlanRunStatus, PlanStep, PlanStepStatus
from app.recovery.builder import (
    DirectExecutionFacts,
    ExecutionFeedbackBuilder,
    PlanExecutorInvocationFacts,
    PlanningExecutionFacts,
    ToolEffectBinding,
)
from app.recovery.errors import ExecutionFeedbackBuildError
from app.recovery.models import (
    ExecutionOutcome,
    FeedbackOverallStatus,
    PlanStepOutcome,
    RunGateOutcome,
)
from app.tools.models import (
    ExecutionEvidence,
    ToolCallStatus,
    ToolEffect,
    ToolError,
)


NOW = "2026-07-17T00:00:00Z"


class ExecutionFeedbackBuilderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = ExecutionFeedbackBuilder()

    def test_direct_success_projects_safe_source_linked_evidence(self) -> None:
        result = _completed(
            _observation(
                1,
                "call_1",
                "research.save_source",
                ToolCallStatus.SUCCEEDED,
                evidence=(
                    ExecutionEvidence(
                        "write_effect", "A source was saved.", "source/ref_1"
                    ),
                ),
            )
        )
        feedback = self.builder.from_direct(
            _direct_facts(
                result,
                ToolEffectBinding("research.save_source", ToolEffect.WRITE),
            )
        )

        self.assertEqual(feedback.overall_status, FeedbackOverallStatus.COMPLETED)
        self.assertEqual(feedback.executor_invocation_ids, ("execinv_1",))
        self.assertEqual(feedback.actions[0].outcome, ExecutionOutcome.SUCCEEDED)
        self.assertEqual(
            feedback.actions[0].evidence[0].source_evidence_index, 0
        )
        self.assertFalse(hasattr(feedback.actions[0], "output"))

    def test_direct_failed_action_outweighs_model_final_text(self) -> None:
        result = _completed(
            _observation(
                1,
                "call_1",
                "research.search_papers",
                ToolCallStatus.FAILED,
                error=ToolError("research_provider_failed", "safe", True),
            )
        )
        feedback = self.builder.from_direct(
            _direct_facts(
                result,
                ToolEffectBinding("research.search_papers", ToolEffect.EXTERNAL_READ),
            )
        )

        self.assertEqual(feedback.overall_status, FeedbackOverallStatus.FAILED)
        self.assertEqual(feedback.actions[0].error_code, "research_provider_failed")
        self.assertEqual(feedback.actions[0].evidence, ())

    def test_direct_first_success_then_failure_is_partial(self) -> None:
        result = _completed(
            _observation(
                1,
                "call_1",
                "research.search_knowledge",
                ToolCallStatus.SUCCEEDED,
                evidence=(ExecutionEvidence("read", "One item was read.", "read/ref_1"),),
            ),
            _observation(
                2,
                "call_2",
                "research.search_papers",
                ToolCallStatus.FAILED,
                error=ToolError("provider_failed", "safe"),
            ),
        )
        feedback = self.builder.from_direct(
            _direct_facts(
                result,
                ToolEffectBinding("research.search_knowledge", ToolEffect.READ),
                ToolEffectBinding("research.search_papers", ToolEffect.EXTERNAL_READ),
            )
        )
        self.assertEqual(feedback.overall_status, FeedbackOverallStatus.PARTIAL)
        self.assertEqual(
            tuple(item.outcome for item in feedback.actions),
            (ExecutionOutcome.SUCCEEDED, ExecutionOutcome.FAILED),
        )

    def test_outer_gate_has_no_synthetic_action_or_executor_identity(self) -> None:
        feedback = self.builder.from_direct(
            DirectExecutionFacts(
                "feedback_1",
                "trace_1",
                "run_1",
                "session_1",
                "A denied request.",
                NOW,
                gate_outcome=RunGateOutcome.DENIED,
            )
        )
        self.assertEqual(feedback.overall_status, FeedbackOverallStatus.DENIED)
        self.assertEqual(feedback.actions, ())
        self.assertEqual(feedback.executor_invocation_ids, ())

    def test_planning_completed_builds_one_ordered_run_level_feedback(self) -> None:
        steps = (
            _step("read", 1, PlanStepStatus.COMPLETED, summary="Read complete."),
            _step(
                "save",
                2,
                PlanStepStatus.COMPLETED,
                summary="Save complete.",
                evidence_refs=("source/ref_1",),
            ),
        )
        facts = _planning_facts(
            PlanRun("plan_1", "session_1", "goal", PlanRunStatus.COMPLETED),
            steps,
            (
                _invocation(
                    "execinv_1",
                    "read",
                    _completed(
                        _observation(
                            1,
                            "call_1",
                            "research.search_knowledge",
                            ToolCallStatus.SUCCEEDED,
                        )
                    ),
                ),
                _invocation(
                    "execinv_2",
                    "save",
                    _completed(
                        _observation(
                            1,
                            "call_2",
                            "research.save_source",
                            ToolCallStatus.SUCCEEDED,
                            evidence=(
                                ExecutionEvidence(
                                    "write_effect", "Saved.", "source/ref_1"
                                ),
                            ),
                        )
                    ),
                ),
            ),
        )
        feedback = self.builder.from_plan(facts)

        self.assertEqual(feedback.overall_status, FeedbackOverallStatus.COMPLETED)
        self.assertEqual(feedback.executor_invocation_ids, ("execinv_1", "execinv_2"))
        self.assertEqual(tuple(item.sequence for item in feedback.actions), (1, 2))
        self.assertEqual(
            tuple(item.outcome for item in feedback.plan_steps),
            (PlanStepOutcome.COMPLETED, PlanStepOutcome.COMPLETED),
        )

    def test_planning_completed_failed_and_pending_is_partial(self) -> None:
        steps = (
            _step("done", 1, PlanStepStatus.COMPLETED, summary="Done."),
            _step(
                "failed",
                2,
                PlanStepStatus.STOPPED,
                stop_reason=ExecutorStopReason.LIMIT_REACHED.value,
                error_code="executor.limit_reached",
            ),
            _step("pending", 3, PlanStepStatus.PENDING),
        )
        stopped = PlanRun(
            "plan_1",
            "session_1",
            "goal",
            PlanRunStatus.STOPPED,
            last_error_code="executor.limit_reached",
        )
        feedback = self.builder.from_plan(
            _planning_facts(
                stopped,
                steps,
                (
                    _invocation("execinv_1", "done", _completed()),
                    _invocation(
                        "execinv_2",
                        "failed",
                        ExecutorResult(
                            "run_1",
                            ExecutorStatus.STOPPED,
                            ExecutorStopReason.LIMIT_REACHED,
                            None,
                            2,
                        ),
                    ),
                ),
            )
        )

        self.assertEqual(feedback.overall_status, FeedbackOverallStatus.PARTIAL)
        self.assertEqual(feedback.stop_step_id, "failed")
        self.assertEqual(
            tuple(item.outcome for item in feedback.plan_steps),
            (
                PlanStepOutcome.COMPLETED,
                PlanStepOutcome.FAILED,
                PlanStepOutcome.NOT_RUN,
            ),
        )

    def test_completed_plan_with_earlier_failed_action_remains_partial(self) -> None:
        step = _step("done", 1, PlanStepStatus.COMPLETED, summary="Done.")
        result = _completed(
            _observation(
                1,
                "call_1",
                "research.search_knowledge",
                ToolCallStatus.SUCCEEDED,
            ),
            _observation(
                2,
                "call_2",
                "research.save_source",
                ToolCallStatus.FAILED,
                error=ToolError("provider_failed", "safe failure"),
            ),
        )

        feedback = self.builder.from_plan(
            _planning_facts(
                PlanRun(
                    "plan_1", "session_1", "goal", PlanRunStatus.COMPLETED
                ),
                (step,),
                (_invocation("execinv_1", "done", result),),
            )
        )

        self.assertEqual(feedback.overall_status, FeedbackOverallStatus.PARTIAL)

    def test_missing_tool_effect_and_not_run_invocation_fail_closed(self) -> None:
        result = _completed(
            _observation(
                1,
                "call_1",
                "research.search_knowledge",
                ToolCallStatus.SUCCEEDED,
            )
        )
        with self.assertRaises(ExecutionFeedbackBuildError) as missing:
            self.builder.from_direct(_direct_facts(result))
        self.assertEqual(missing.exception.code, "execution_feedback_source_incomplete")

        pending = _step("pending", 1, PlanStepStatus.PENDING)
        with self.assertRaises(ExecutionFeedbackBuildError) as conflict:
            self.builder.from_plan(
                _planning_facts(
                    PlanRun(
                        "plan_1", "session_1", "goal", PlanRunStatus.STOPPED
                    ),
                    (pending,),
                    (_invocation("execinv_1", "pending", _completed()),),
                )
            )
        self.assertEqual(conflict.exception.code, "execution_feedback_source_conflict")

    def test_plan_step_evidence_must_come_from_the_same_step_actions(self) -> None:
        step = _step(
            "save",
            1,
            PlanStepStatus.COMPLETED,
            summary="Saved.",
            evidence_refs=("other/ref",),
        )
        invocation = _invocation(
            "execinv_1",
            "save",
            _completed(
                _observation(
                    1,
                    "call_1",
                    "research.save_source",
                    ToolCallStatus.SUCCEEDED,
                    evidence=(
                        ExecutionEvidence("write_effect", "Saved.", "source/ref_1"),
                    ),
                )
            ),
        )
        with self.assertRaises(ExecutionFeedbackBuildError) as raised:
            self.builder.from_plan(
                _planning_facts(
                    PlanRun(
                        "plan_1", "session_1", "goal", PlanRunStatus.COMPLETED
                    ),
                    (step,),
                    (invocation,),
                )
            )
        self.assertEqual(raised.exception.code, "execution_feedback_source_conflict")


def _direct_facts(
    result: ExecutorResult, *effects: ToolEffectBinding
) -> DirectExecutionFacts:
    return DirectExecutionFacts(
        "feedback_1",
        "trace_1",
        "run_1",
        "session_1",
        "Safe goal.",
        NOW,
        result=result,
        executor_invocation_id="execinv_1",
        source_span_id="span_executor_1",
        tool_effects=effects,
    )


def _planning_facts(
    run: PlanRun,
    steps: tuple[PlanStep, ...],
    invocations: tuple[PlanExecutorInvocationFacts, ...],
) -> PlanningExecutionFacts:
    return PlanningExecutionFacts(
        "feedback_1",
        "trace_1",
        "run_1",
        "session_1",
        "Safe plan goal.",
        NOW,
        run,
        steps,
        invocations,
        (
            ToolEffectBinding("research.search_knowledge", ToolEffect.READ),
            ToolEffectBinding("research.save_source", ToolEffect.WRITE),
        ),
    )


def _invocation(
    invocation_id: str, step_id: str, result: ExecutorResult
) -> PlanExecutorInvocationFacts:
    return PlanExecutorInvocationFacts(
        invocation_id, f"span_{invocation_id}", 1, step_id, result
    )


def _step(
    step_id: str,
    position: int,
    status: PlanStepStatus,
    *,
    summary: str | None = None,
    stop_reason: str | None = None,
    error_code: str | None = None,
    evidence_refs: tuple[str, ...] = (),
) -> PlanStep:
    return PlanStep(
        "plan_1",
        1,
        step_id,
        position,
        step_id,
        f"{step_id} expected",
        (),
        status,
        stop_reason,
        summary,
        error_code,
        evidence_refs,
    )


def _completed(*observations: ToolObservation) -> ExecutorResult:
    return ExecutorResult(
        "run_1",
        ExecutorStatus.COMPLETED,
        ExecutorStopReason.FINAL_ANSWER,
        "Model draft.",
        max(len(observations), 1),
        observations,
    )


def _observation(
    step_index: int,
    call_id: str,
    tool_name: str,
    status: ToolCallStatus,
    *,
    evidence: tuple[ExecutionEvidence, ...] = (),
    error: ToolError | None = None,
) -> ToolObservation:
    return ToolObservation(
        step_index,
        call_id,
        tool_name,
        status,
        error=error,
        evidence=evidence,
    )


if __name__ == "__main__":
    unittest.main()
