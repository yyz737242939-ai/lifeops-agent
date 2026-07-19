"""Evidence-grounded claim validation and deterministic safe fallback."""

from __future__ import annotations

from app.planning.models import PlanFinalizerOutput
from app.recovery.models import (
    AnswerOutputMode,
    ClaimStatus,
    ExecutionActionFeedback,
    ExecutionClaim,
    ExecutionClaimKind,
    ExecutionFeedback,
    ExecutionOutcome,
    FinalAnswerDraft,
    FinalAnswerValidation,
    PlanStepOutcome,
    ValidatedFinalAnswer,
)
from app.tools.models import ToolEffect


CLAIM_ACTION_NOT_SUCCEEDED = "claim_action_not_succeeded"
CLAIM_STEP_NOT_COMPLETED = "claim_step_not_completed"
CLAIM_EVIDENCE_MISSING = "claim_evidence_missing"
CLAIM_REFERENCE_UNKNOWN = "claim_reference_unknown"
CLAIM_SCOPE_MISMATCH = "claim_scope_mismatch"
CLAIM_DECLARATION_MISSING = "claim_declaration_missing"
VALIDATOR_FAILED = "validator_failed"


class FinalAnswerValidator:
    """Validate structured claims against one current canonical-safe snapshot."""

    def validate(
        self, draft: FinalAnswerDraft, feedback: ExecutionFeedback
    ) -> ValidatedFinalAnswer:
        if not isinstance(draft, FinalAnswerDraft):
            raise ValueError("draft must be a FinalAnswerDraft.")
        if not isinstance(feedback, ExecutionFeedback):
            raise ValueError("feedback must be ExecutionFeedback.")
        try:
            return self._validate(draft, feedback)
        except Exception:
            validation = FinalAnswerValidation(
                claim_status=ClaimStatus.INVALID,
                output_mode=AnswerOutputMode.DETERMINISTIC_FALLBACK,
                reason_codes=(VALIDATOR_FAILED,),
            )
            return ValidatedFinalAnswer(
                message=deterministic_execution_fallback(feedback),
                validation=validation,
            )

    def _validate(
        self, draft: FinalAnswerDraft, feedback: ExecutionFeedback
    ) -> ValidatedFinalAnswer:
        accepted: list[str] = []
        reasons: set[str] = set()
        if feedback.actions and not draft.execution_claims:
            reasons.add(CLAIM_DECLARATION_MISSING)
        for claim in draft.execution_claims:
            claim_reasons = self._validate_claim(claim, feedback)
            if claim_reasons:
                reasons.update(claim_reasons)
            else:
                accepted.append(claim.claim_id)
        if reasons:
            validation = FinalAnswerValidation(
                claim_status=ClaimStatus.INVALID,
                output_mode=AnswerOutputMode.DETERMINISTIC_FALLBACK,
                reason_codes=tuple(sorted(reasons)),
                accepted_claim_ids=tuple(accepted),
            )
            return ValidatedFinalAnswer(
                message=deterministic_execution_fallback(feedback),
                validation=validation,
            )
        return ValidatedFinalAnswer(
            message=draft.message,
            validation=FinalAnswerValidation(
                claim_status=ClaimStatus.VALID,
                output_mode=AnswerOutputMode.MODEL,
                accepted_claim_ids=tuple(accepted),
            ),
        )

    def _validate_claim(
        self, claim: ExecutionClaim, feedback: ExecutionFeedback
    ) -> set[str]:
        reasons: set[str] = set()
        if (
            claim.source_run_id != feedback.run_id
            or claim.session_id != feedback.session_id
        ):
            return {CLAIM_SCOPE_MISMATCH}
        if claim.kind is ExecutionClaimKind.ACTION_SUCCESS:
            action = next(
                (item for item in feedback.actions if item.call_id == claim.call_id),
                None,
            )
            if action is None:
                return {CLAIM_REFERENCE_UNKNOWN}
            reasons.update(_action_scope_reasons(claim, feedback, action))
            if action.outcome is not ExecutionOutcome.SUCCEEDED:
                reasons.add(CLAIM_ACTION_NOT_SUCCEEDED)
            available = set(action.evidence_refs)
            if not set(claim.evidence_refs) <= available:
                reasons.add(CLAIM_EVIDENCE_MISSING)
            if action.tool_effect is ToolEffect.WRITE and not claim.evidence_refs:
                reasons.add(CLAIM_EVIDENCE_MISSING)
            return reasons

        step = next(
            (
                item
                for item in feedback.plan_steps
                if item.revision == claim.plan_revision
                and item.step_id == claim.plan_step_id
            ),
            None,
        )
        if step is None:
            return {CLAIM_REFERENCE_UNKNOWN}
        if feedback.plan_id != claim.plan_id:
            reasons.add(CLAIM_SCOPE_MISMATCH)
        if step.outcome is not PlanStepOutcome.COMPLETED:
            reasons.add(CLAIM_STEP_NOT_COMPLETED)
        if not set(claim.evidence_refs) <= set(step.evidence_refs):
            reasons.add(CLAIM_EVIDENCE_MISSING)
        step_actions = tuple(
            item
            for item in feedback.actions
            if item.plan_revision == claim.plan_revision
            and item.plan_step_id == claim.plan_step_id
        )
        if any(item.tool_effect is ToolEffect.WRITE for item in step_actions) and not claim.evidence_refs:
            reasons.add(CLAIM_EVIDENCE_MISSING)
        return reasons


def draft_from_plan_finalizer(
    output: PlanFinalizerOutput, feedback: ExecutionFeedback
) -> FinalAnswerDraft:
    """Adapt the current evidence-aware PlanFinalizer output to shared claims.

    The current Planning contract only declares WRITE success plus evidence refs.
    Read-only Step claims remain absent until the later structured-output wiring.
    """

    if not isinstance(output, PlanFinalizerOutput):
        raise ValueError("output must be a PlanFinalizerOutput.")
    if not isinstance(feedback, ExecutionFeedback):
        raise ValueError("feedback must be ExecutionFeedback.")
    if not output.claims_write_success:
        return FinalAnswerDraft(output.message)
    owners: dict[str, tuple[int, str]] = {}
    for step in feedback.plan_steps:
        for reference in step.evidence_refs:
            if reference in owners and owners[reference] != (
                step.revision,
                step.step_id,
            ):
                raise ValueError("Plan evidence reference has multiple Step owners.")
            owners[reference] = (step.revision, step.step_id)
    grouped: dict[tuple[int, str], list[str]] = {}
    for reference in output.evidence_refs:
        owner = owners.get(reference)
        if owner is None:
            raise ValueError("PlanFinalizer cited an unknown evidence reference.")
        grouped.setdefault(owner, []).append(reference)
    if not grouped:
        raise ValueError("WRITE success requires owned evidence references.")
    claims = tuple(
        ExecutionClaim(
            claim_id=f"plan_finalizer:{revision}:{step_id}",
            kind=ExecutionClaimKind.PLAN_STEP_SUCCESS,
            source_run_id=feedback.run_id,
            session_id=feedback.session_id,
            plan_id=feedback.plan_id,
            plan_revision=revision,
            plan_step_id=step_id,
            evidence_refs=tuple(references),
        )
        for (revision, step_id), references in sorted(grouped.items())
    )
    return FinalAnswerDraft(output.message, claims)


def deterministic_execution_fallback(feedback: ExecutionFeedback) -> str:
    """Render only facts already present in ExecutionFeedback."""

    if not isinstance(feedback, ExecutionFeedback):
        raise ValueError("feedback must be ExecutionFeedback.")
    lines = [f"执行结果：{feedback.overall_status.value}。"]
    succeeded_actions = tuple(
        item for item in feedback.actions if item.outcome is ExecutionOutcome.SUCCEEDED
    )
    unsuccessful_actions = tuple(
        item for item in feedback.actions if item.outcome is not ExecutionOutcome.SUCCEEDED
    )
    completed_steps = tuple(
        item for item in feedback.plan_steps if item.outcome is PlanStepOutcome.COMPLETED
    )
    incomplete_steps = tuple(
        item
        for item in feedback.plan_steps
        if item.outcome not in {PlanStepOutcome.COMPLETED, PlanStepOutcome.NOT_RUN}
    )
    not_run_steps = tuple(
        item for item in feedback.plan_steps if item.outcome is PlanStepOutcome.NOT_RUN
    )
    if succeeded_actions:
        lines.append(
            "已验证成功的动作："
            + "；".join(
                f"{item.tool_name} ({item.call_id})" for item in succeeded_actions
            )
            + "。"
        )
    if completed_steps:
        lines.append(
            "已完成的计划步骤："
            + "；".join(
                f"{item.position}. {item.expected_outcome}" for item in completed_steps
            )
            + "。"
        )
    if unsuccessful_actions:
        lines.append(
            "失败或未获准的动作："
            + "；".join(
                f"{item.tool_name} ({item.call_id}, {item.outcome.value})"
                for item in unsuccessful_actions
            )
            + "。"
        )
    if incomplete_steps:
        lines.append(
            "失败或停止的计划步骤："
            + "；".join(
                f"{item.position}. {item.expected_outcome} ({item.outcome.value})"
                for item in incomplete_steps
            )
            + "。"
        )
    if not_run_steps:
        lines.append(
            "未执行的计划步骤："
            + "；".join(
                f"{item.position}. {item.expected_outcome}" for item in not_run_steps
            )
            + "。"
        )
    if not feedback.actions and not feedback.plan_steps:
        lines.append("本次没有已记录的工具动作。")
    lines.append("后续动作仅为建议，尚未执行。")
    return "\n".join(lines)


def _action_scope_reasons(
    claim: ExecutionClaim,
    feedback: ExecutionFeedback,
    action: ExecutionActionFeedback,
) -> set[str]:
    if action.plan_step_id is None:
        if any(
            value is not None
            for value in (claim.plan_id, claim.plan_revision, claim.plan_step_id)
        ):
            return {CLAIM_SCOPE_MISMATCH}
        return set()
    if (
        claim.plan_id != feedback.plan_id
        or claim.plan_revision != action.plan_revision
        or claim.plan_step_id != action.plan_step_id
    ):
        return {CLAIM_SCOPE_MISMATCH}
    return set()
