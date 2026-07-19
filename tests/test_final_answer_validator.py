from __future__ import annotations

import unittest

from app.executor.models import (
    ExecutorResult,
    ExecutorStatus,
    ExecutorStopReason,
    ToolObservation,
)
from app.planning.models import (
    PlanFinalizerOutput,
    PlanRun,
    PlanRunStatus,
    PlanStep,
    PlanStepStatus,
)
from app.recovery.builder import (
    DirectExecutionFacts,
    ExecutionFeedbackBuilder,
    PlanExecutorInvocationFacts,
    PlanningExecutionFacts,
    ToolEffectBinding,
)
from app.recovery.models import (
    AnswerOutputMode,
    ClaimStatus,
    ExecutionClaim,
    ExecutionClaimKind,
    FinalAnswerDraft,
)
from app.recovery.validator import (
    CLAIM_ACTION_NOT_SUCCEEDED,
    CLAIM_EVIDENCE_MISSING,
    CLAIM_REFERENCE_UNKNOWN,
    CLAIM_SCOPE_MISMATCH,
    CLAIM_STEP_NOT_COMPLETED,
    FinalAnswerValidator,
    VALIDATOR_FAILED,
    draft_from_plan_finalizer,
)
from app.tools.models import (
    ExecutionEvidence,
    ToolCallStatus,
    ToolEffect,
    ToolError,
)


NOW = "2026-07-17T00:00:00Z"


class FinalAnswerValidatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = ExecutionFeedbackBuilder()
        self.validator = FinalAnswerValidator()

    def test_direct_write_success_requires_matching_evidence(self) -> None:
        feedback = self._direct_feedback(
            ToolCallStatus.SUCCEEDED,
            effect=ToolEffect.WRITE,
            evidence=(
                ExecutionEvidence("write_effect", "Saved.", "source/ref_1"),
            ),
        )
        valid = self.validator.validate(
            FinalAnswerDraft(
                "已保存。",
                (
                    _action_claim(
                        "claim_1", evidence_refs=("source/ref_1",)
                    ),
                ),
            ),
            feedback,
        )
        missing = self.validator.validate(
            FinalAnswerDraft("已保存。", (_action_claim("claim_2"),)), feedback
        )

        self.assertEqual(valid.message, "已保存。")
        self.assertEqual(valid.validation.claim_status, ClaimStatus.VALID)
        self.assertEqual(valid.validation.accepted_claim_ids, ("claim_1",))
        self.assertEqual(missing.validation.claim_status, ClaimStatus.INVALID)
        self.assertIn(CLAIM_EVIDENCE_MISSING, missing.validation.reason_codes)
        self.assertEqual(
            missing.validation.output_mode, AnswerOutputMode.DETERMINISTIC_FALLBACK
        )

    def test_failed_action_false_success_claim_uses_deterministic_fallback(self) -> None:
        feedback = self._direct_feedback(
            ToolCallStatus.FAILED,
            effect=ToolEffect.EXTERNAL_READ,
            error=ToolError("research_provider_failed", "safe"),
        )
        result = self.validator.validate(
            FinalAnswerDraft("查询已经成功。", (_action_claim("claim_1"),)),
            feedback,
        )

        self.assertEqual(result.validation.claim_status, ClaimStatus.INVALID)
        self.assertIn(
            CLAIM_ACTION_NOT_SUCCEEDED, result.validation.reason_codes
        )
        self.assertNotEqual(result.message, "查询已经成功。")
        self.assertIn("failed", result.message)
        self.assertIn("尚未执行", result.message)

    def test_read_success_can_claim_call_success_without_evidence(self) -> None:
        feedback = self._direct_feedback(
            ToolCallStatus.SUCCEEDED, effect=ToolEffect.READ
        )
        result = self.validator.validate(
            FinalAnswerDraft("读取调用成功。", (_action_claim("claim_1"),)),
            feedback,
        )
        self.assertEqual(result.validation.claim_status, ClaimStatus.VALID)

    def test_unknown_and_cross_scope_claims_fail_closed(self) -> None:
        feedback = self._direct_feedback(
            ToolCallStatus.SUCCEEDED, effect=ToolEffect.READ
        )
        unknown = self.validator.validate(
            FinalAnswerDraft(
                "done",
                (
                    ExecutionClaim(
                        "claim_1",
                        ExecutionClaimKind.ACTION_SUCCESS,
                        "run_1",
                        "session_1",
                        call_id="call_unknown",
                    ),
                ),
            ),
            feedback,
        )
        cross_run = self.validator.validate(
            FinalAnswerDraft(
                "done",
                (
                    ExecutionClaim(
                        "claim_2",
                        ExecutionClaimKind.ACTION_SUCCESS,
                        "run_old",
                        "session_1",
                        call_id="call_1",
                    ),
                ),
            ),
            feedback,
        )
        self.assertIn(CLAIM_REFERENCE_UNKNOWN, unknown.validation.reason_codes)
        self.assertIn(CLAIM_SCOPE_MISMATCH, cross_run.validation.reason_codes)

    def test_planning_partial_accepts_completed_claim_and_rejects_stopped_and_pending(self) -> None:
        feedback = self._planning_partial_feedback()
        draft = FinalAnswerDraft(
            "全部完成。",
            (
                _step_claim("claim_done", "done"),
                _step_claim("claim_failed", "failed"),
                _step_claim("claim_pending", "pending"),
            ),
        )
        result = self.validator.validate(draft, feedback)

        self.assertEqual(result.validation.claim_status, ClaimStatus.INVALID)
        self.assertEqual(result.validation.accepted_claim_ids, ("claim_done",))
        self.assertIn(CLAIM_STEP_NOT_COMPLETED, result.validation.reason_codes)
        self.assertIn("已完成的计划步骤", result.message)
        self.assertIn("失败或停止的计划步骤", result.message)
        self.assertIn("未执行的计划步骤", result.message)
        self.assertNotEqual(result.message, draft.message)

    def test_plan_step_evidence_cannot_cross_step(self) -> None:
        feedback = self._planning_completed_write_feedback()
        result = self.validator.validate(
            FinalAnswerDraft(
                "保存完成。",
                (
                    _step_claim(
                        "claim_1", "save", evidence_refs=("other/ref",)
                    ),
                ),
            ),
            feedback,
        )
        self.assertIn(CLAIM_EVIDENCE_MISSING, result.validation.reason_codes)

    def test_current_plan_finalizer_write_output_reuses_shared_validator(self) -> None:
        feedback = self._planning_completed_write_feedback()
        draft = draft_from_plan_finalizer(
            PlanFinalizerOutput("保存完成。", True, ("source/ref_1",)), feedback
        )
        result = self.validator.validate(draft, feedback)

        self.assertEqual(result.validation.claim_status, ClaimStatus.VALID)
        self.assertEqual(
            result.validation.accepted_claim_ids,
            ("plan_finalizer:1:save",),
        )
        with self.assertRaises(ValueError):
            draft_from_plan_finalizer(
                PlanFinalizerOutput("保存完成。", True, ("unknown/ref",)), feedback
            )

    def test_zero_claim_text_after_execution_falls_back(self) -> None:
        feedback = self._direct_feedback(
            ToolCallStatus.FAILED,
            effect=ToolEffect.READ,
            error=ToolError("read_failed", "safe"),
        )
        result = self.validator.validate(
            FinalAnswerDraft("可以稍后重新发起一个新请求。"), feedback
        )
        self.assertEqual(result.validation.claim_status, ClaimStatus.INVALID)
        self.assertEqual(
            result.validation.reason_codes, ("claim_declaration_missing",)
        )
        self.assertNotEqual(result.message, "可以稍后重新发起一个新请求。")

    def test_zero_claim_text_without_execution_remains_compatible(self) -> None:
        feedback = ExecutionFeedbackBuilder().from_direct(
            DirectExecutionFacts(
                "feedback_no_action",
                "trace_1",
                "run_1",
                "session_1",
                "Answer an informational request.",
                NOW,
                ExecutorResult(
                    "run_1",
                    ExecutorStatus.COMPLETED,
                    ExecutorStopReason.FINAL_ANSWER,
                    "普通说明。",
                    1,
                ),
                "execinv_1",
                "span_1",
            )
        )
        result = self.validator.validate(FinalAnswerDraft("普通说明。"), feedback)
        self.assertEqual(result.validation.claim_status, ClaimStatus.VALID)
        self.assertEqual(result.message, "普通说明。")

    def test_validator_internal_failure_is_fail_closed(self) -> None:
        class ExplodingValidator(FinalAnswerValidator):
            def _validate_claim(self, claim, feedback):
                raise RuntimeError("sensitive internal failure")

        feedback = self._direct_feedback(
            ToolCallStatus.SUCCEEDED, effect=ToolEffect.READ
        )
        result = ExplodingValidator().validate(
            FinalAnswerDraft("done", (_action_claim("claim_1"),)), feedback
        )
        self.assertEqual(result.validation.reason_codes, (VALIDATOR_FAILED,))
        self.assertEqual(
            result.validation.output_mode, AnswerOutputMode.DETERMINISTIC_FALLBACK
        )
        self.assertNotIn("sensitive internal failure", result.message)

    def _direct_feedback(
        self,
        status: ToolCallStatus,
        *,
        effect: ToolEffect,
        evidence: tuple[ExecutionEvidence, ...] = (),
        error: ToolError | None = None,
    ):
        observation = ToolObservation(
            1,
            "call_1",
            "research.fixture",
            status,
            error=error,
            evidence=evidence,
        )
        result = ExecutorResult(
            "run_1",
            ExecutorStatus.COMPLETED,
            ExecutorStopReason.FINAL_ANSWER,
            "draft",
            1,
            (observation,),
        )
        return self.builder.from_direct(
            DirectExecutionFacts(
                "feedback_1",
                "trace_1",
                "run_1",
                "session_1",
                "Safe goal.",
                NOW,
                result=result,
                executor_invocation_id="execinv_1",
                source_span_id="span_1",
                tool_effects=(ToolEffectBinding("research.fixture", effect),),
            )
        )

    def _planning_partial_feedback(self):
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
        invocations = (
            PlanExecutorInvocationFacts(
                "execinv_1", "span_1", 1, "done", _completed()
            ),
            PlanExecutorInvocationFacts(
                "execinv_2",
                "span_2",
                1,
                "failed",
                ExecutorResult(
                    "run_1",
                    ExecutorStatus.STOPPED,
                    ExecutorStopReason.LIMIT_REACHED,
                    None,
                    1,
                ),
            ),
        )
        return self.builder.from_plan(
            PlanningExecutionFacts(
                "feedback_1",
                "trace_1",
                "run_1",
                "session_1",
                "Safe plan goal.",
                NOW,
                PlanRun(
                    "plan_1",
                    "session_1",
                    "goal",
                    PlanRunStatus.STOPPED,
                    last_error_code="executor.limit_reached",
                ),
                steps,
                invocations,
            )
        )

    def _planning_completed_write_feedback(self):
        observation = ToolObservation(
            1,
            "call_1",
            "research.save_source",
            ToolCallStatus.SUCCEEDED,
            evidence=(ExecutionEvidence("write_effect", "Saved.", "source/ref_1"),),
        )
        return self.builder.from_plan(
            PlanningExecutionFacts(
                "feedback_1",
                "trace_1",
                "run_1",
                "session_1",
                "Safe plan goal.",
                NOW,
                PlanRun("plan_1", "session_1", "goal", PlanRunStatus.COMPLETED),
                (
                    _step(
                        "save",
                        1,
                        PlanStepStatus.COMPLETED,
                        summary="Saved.",
                        evidence_refs=("source/ref_1",),
                    ),
                ),
                (
                    PlanExecutorInvocationFacts(
                        "execinv_1",
                        "span_1",
                        1,
                        "save",
                        _completed(observation),
                    ),
                ),
                (ToolEffectBinding("research.save_source", ToolEffect.WRITE),),
            )
        )


def _action_claim(
    claim_id: str, *, evidence_refs: tuple[str, ...] = ()
) -> ExecutionClaim:
    return ExecutionClaim(
        claim_id,
        ExecutionClaimKind.ACTION_SUCCESS,
        "run_1",
        "session_1",
        call_id="call_1",
        evidence_refs=evidence_refs,
    )


def _step_claim(
    claim_id: str, step_id: str, *, evidence_refs: tuple[str, ...] = ()
) -> ExecutionClaim:
    return ExecutionClaim(
        claim_id,
        ExecutionClaimKind.PLAN_STEP_SUCCESS,
        "run_1",
        "session_1",
        plan_id="plan_1",
        plan_revision=1,
        plan_step_id=step_id,
        evidence_refs=evidence_refs,
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
        "draft",
        max(1, len(observations)),
        observations,
    )


if __name__ == "__main__":
    unittest.main()
