"""SQLite repository for canonical safe ExecutionFeedback snapshots."""

from __future__ import annotations

import json
import sqlite3

from app.planning.models import PlanStep, PlanStepStatus
from app.recovery.errors import (
    RECOVERY_SOURCE_UNAVAILABLE,
    ExecutionFeedbackRepositoryError,
)
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
)
from app.recovery.ports import ExecutionFeedbackRepository
from app.tools.models import ToolEffect


class SqliteExecutionFeedbackRepository:
    """Persist feedback facts while leaving Plan lifecycle in Plan tables."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save(self, feedback: ExecutionFeedback) -> None:
        if not isinstance(feedback, ExecutionFeedback):
            raise ValueError("feedback must be an ExecutionFeedback.")
        if feedback.validation is None:
            raise ExecutionFeedbackRepositoryError(
                "Only finalized feedback can be persisted.",
                code="execution_feedback_source_incomplete",
            )
        try:
            existing_row = self._conn.execute(
                "SELECT id, session_id FROM execution_feedback WHERE run_id = ?",
                (feedback.run_id,),
            ).fetchone()
            if existing_row is not None:
                existing = self.get_for_run(
                    str(existing_row["session_id"]), feedback.run_id
                )
                if existing == feedback:
                    return
                raise _conflict()
            same_id = self._conn.execute(
                "SELECT run_id FROM execution_feedback WHERE id = ?",
                (feedback.feedback_id,),
            ).fetchone()
            if same_id is not None:
                raise _conflict()
            if feedback.path is ExecutionPath.PLANNING:
                stored_steps = self._load_plan_steps(
                    feedback.session_id,
                    feedback.plan_id or "",
                    feedback.revision or 0,
                )
                if stored_steps != feedback.plan_steps:
                    raise ExecutionFeedbackRepositoryError(
                        "Planning feedback does not match canonical Plan rows.",
                        code="execution_feedback_source_conflict",
                    )
            with self._conn:
                self._conn.execute(
                    """INSERT INTO execution_feedback (
                           id, trace_id, run_id, session_id, path, goal_summary,
                           overall_status, stop_reason, error_code,
                           executor_invocation_ids_json, plan_id, revision,
                           stop_step_id, validation_claim_status,
                           validation_output_mode, validation_reason_codes_json,
                           validation_accepted_claim_ids_json, created_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    _feedback_values(feedback),
                )
                self._conn.executemany(
                    """INSERT INTO execution_feedback_actions (
                           feedback_id, sequence, executor_invocation_id,
                           source_span_id, call_id, tool_name, tool_effect,
                           outcome, error_code, retryable, plan_revision,
                           plan_step_id
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        _action_values(feedback.feedback_id, action)
                        for action in feedback.actions
                    ),
                )
                if feedback.path is ExecutionPath.PLANNING:
                    self._conn.executemany(
                        """INSERT INTO execution_feedback_plan_steps (
                               feedback_id, revision, step_id, position,
                               objective, expected_outcome, original_status,
                               outcome, stop_reason, error_code,
                               safe_result_summary, evidence_refs_json
                           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            _feedback_plan_step_values(feedback.feedback_id, step)
                            for step in feedback.plan_steps
                        ),
                    )
                self._conn.executemany(
                    """INSERT INTO execution_feedback_evidence (
                           feedback_id, action_sequence, source_evidence_index,
                           evidence_type, summary, reference, source_call_id
                       ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        _evidence_values(feedback.feedback_id, action.sequence, evidence)
                        for action in feedback.actions
                        for evidence in action.evidence
                    ),
                )
        except ExecutionFeedbackRepositoryError:
            raise
        except sqlite3.IntegrityError as exc:
            raise _conflict() from exc
        except sqlite3.Error as exc:
            raise _persistence_failure() from exc

    def get_for_run(self, session_id: str, run_id: str) -> ExecutionFeedback:
        _required_text(session_id, "session_id")
        _required_text(run_id, "run_id")
        try:
            row = self._conn.execute(
                """SELECT * FROM execution_feedback
                   WHERE session_id = ? AND run_id = ?""",
                (session_id, run_id),
            ).fetchone()
            if row is None:
                raise ExecutionFeedbackRepositoryError(
                    "Execution feedback is unavailable.",
                    code=RECOVERY_SOURCE_UNAVAILABLE,
                )
            return self._feedback_from_row(row)
        except ExecutionFeedbackRepositoryError:
            raise
        except (KeyError, TypeError, ValueError, sqlite3.Error) as exc:
            raise _persistence_failure() from exc

    def get_latest(self, session_id: str) -> ExecutionFeedback | None:
        _required_text(session_id, "session_id")
        try:
            row = self._conn.execute(
                """SELECT * FROM execution_feedback
                   WHERE session_id = ?
                   ORDER BY created_at DESC, id DESC LIMIT 1""",
                (session_id,),
            ).fetchone()
            return self._feedback_from_row(row) if row is not None else None
        except ExecutionFeedbackRepositoryError:
            raise
        except (KeyError, TypeError, ValueError, sqlite3.Error) as exc:
            raise _persistence_failure() from exc

    def _feedback_from_row(self, row: sqlite3.Row) -> ExecutionFeedback:
        feedback_id = str(row["id"])
        action_rows = self._conn.execute(
            """SELECT * FROM execution_feedback_actions
               WHERE feedback_id = ? ORDER BY sequence""",
            (feedback_id,),
        ).fetchall()
        actions = tuple(
            self._action_from_row(feedback_id, action_row)
            for action_row in action_rows
        )
        path = ExecutionPath(str(row["path"]))
        plan_id = str(row["plan_id"]) if row["plan_id"] is not None else None
        revision = int(row["revision"]) if row["revision"] is not None else None
        plan_steps = (
            self._load_feedback_plan_steps(feedback_id)
            if path is ExecutionPath.PLANNING
            else ()
        )
        validation = FinalAnswerValidation(
            claim_status=ClaimStatus(str(row["validation_claim_status"])),
            output_mode=AnswerOutputMode(str(row["validation_output_mode"])),
            reason_codes=_read_string_tuple(row["validation_reason_codes_json"]),
            accepted_claim_ids=_read_string_tuple(
                row["validation_accepted_claim_ids_json"]
            ),
        )
        return ExecutionFeedback(
            feedback_id=feedback_id,
            trace_id=str(row["trace_id"]),
            run_id=str(row["run_id"]),
            session_id=str(row["session_id"]),
            path=path,
            goal_summary=str(row["goal_summary"]),
            overall_status=FeedbackOverallStatus(str(row["overall_status"])),
            stop_reason=(
                str(row["stop_reason"]) if row["stop_reason"] is not None else None
            ),
            error_code=(
                str(row["error_code"]) if row["error_code"] is not None else None
            ),
            executor_invocation_ids=_read_string_tuple(
                row["executor_invocation_ids_json"]
            ),
            actions=actions,
            plan_steps=plan_steps,
            created_at=str(row["created_at"]),
            plan_id=plan_id,
            revision=revision,
            stop_step_id=(
                str(row["stop_step_id"])
                if row["stop_step_id"] is not None
                else None
            ),
            validation=validation,
        )

    def _action_from_row(
        self, feedback_id: str, row: sqlite3.Row
    ) -> ExecutionActionFeedback:
        evidence_rows = self._conn.execute(
            """SELECT * FROM execution_feedback_evidence
               WHERE feedback_id = ? AND action_sequence = ?
               ORDER BY source_evidence_index""",
            (feedback_id, int(row["sequence"])),
        ).fetchall()
        evidence = tuple(
            ExecutionFeedbackEvidence(
                evidence_type=str(item["evidence_type"]),
                summary=str(item["summary"]),
                reference=(
                    str(item["reference"]) if item["reference"] is not None else None
                ),
                source_call_id=str(item["source_call_id"]),
                source_evidence_index=int(item["source_evidence_index"]),
            )
            for item in evidence_rows
        )
        return ExecutionActionFeedback(
            sequence=int(row["sequence"]),
            executor_invocation_id=str(row["executor_invocation_id"]),
            source_span_id=str(row["source_span_id"]),
            call_id=str(row["call_id"]),
            tool_name=str(row["tool_name"]),
            tool_effect=ToolEffect(str(row["tool_effect"])),
            outcome=ExecutionOutcome(str(row["outcome"])),
            error_code=(
                str(row["error_code"]) if row["error_code"] is not None else None
            ),
            retryable=(
                bool(int(row["retryable"])) if row["retryable"] is not None else None
            ),
            evidence=evidence,
            plan_revision=(
                int(row["plan_revision"])
                if row["plan_revision"] is not None
                else None
            ),
            plan_step_id=(
                str(row["plan_step_id"])
                if row["plan_step_id"] is not None
                else None
            ),
        )

    def _load_plan_steps(
        self, session_id: str, plan_id: str, through_revision: int
    ) -> tuple[ExecutionPlanStepFeedback, ...]:
        plan = self._conn.execute(
            "SELECT session_id FROM plan_runs WHERE id = ?", (plan_id,)
        ).fetchone()
        if plan is None or str(plan["session_id"]) != session_id:
            raise ExecutionFeedbackRepositoryError(
                "Canonical Plan lifecycle is unavailable.",
                code="execution_feedback_source_incomplete",
            )
        rows = self._conn.execute(
            """SELECT * FROM plan_steps
               WHERE plan_id = ? AND revision <= ?
               ORDER BY revision, position""",
            (plan_id, through_revision),
        ).fetchall()
        if not rows:
            raise ExecutionFeedbackRepositoryError(
                "Canonical Plan lifecycle is unavailable.",
                code="execution_feedback_source_incomplete",
            )
        return tuple(_plan_feedback_from_row(row) for row in rows)

    def _load_feedback_plan_steps(
        self, feedback_id: str
    ) -> tuple[ExecutionPlanStepFeedback, ...]:
        rows = self._conn.execute(
            """SELECT * FROM execution_feedback_plan_steps
               WHERE feedback_id = ? ORDER BY revision, position""",
            (feedback_id,),
        ).fetchall()
        if not rows:
            raise ExecutionFeedbackRepositoryError(
                "Execution feedback PlanStep snapshot is unavailable.",
                code="execution_feedback_source_incomplete",
            )
        return tuple(_feedback_plan_step_from_row(row) for row in rows)


def _feedback_values(feedback: ExecutionFeedback) -> tuple[object, ...]:
    validation = feedback.validation
    if validation is None:
        raise ValueError("validation must be finalized.")
    return (
        feedback.feedback_id,
        feedback.trace_id,
        feedback.run_id,
        feedback.session_id,
        feedback.path.value,
        feedback.goal_summary,
        feedback.overall_status.value,
        feedback.stop_reason,
        feedback.error_code,
        _json_tuple(feedback.executor_invocation_ids),
        feedback.plan_id,
        feedback.revision,
        feedback.stop_step_id,
        validation.claim_status.value,
        validation.output_mode.value,
        _json_tuple(validation.reason_codes),
        _json_tuple(validation.accepted_claim_ids),
        feedback.created_at,
    )


def _action_values(
    feedback_id: str, action: ExecutionActionFeedback
) -> tuple[object, ...]:
    return (
        feedback_id,
        action.sequence,
        action.executor_invocation_id,
        action.source_span_id,
        action.call_id,
        action.tool_name,
        action.tool_effect.value,
        action.outcome.value,
        action.error_code,
        int(action.retryable) if action.retryable is not None else None,
        action.plan_revision,
        action.plan_step_id,
    )


def _evidence_values(
    feedback_id: str,
    action_sequence: int,
    evidence: ExecutionFeedbackEvidence,
) -> tuple[object, ...]:
    return (
        feedback_id,
        action_sequence,
        evidence.source_evidence_index,
        evidence.evidence_type,
        evidence.summary,
        evidence.reference,
        evidence.source_call_id,
    )


def _feedback_plan_step_values(
    feedback_id: str,
    step: ExecutionPlanStepFeedback,
) -> tuple[object, ...]:
    return (
        feedback_id,
        step.revision,
        step.step_id,
        step.position,
        step.objective,
        step.expected_outcome,
        step.original_status.value,
        step.outcome.value,
        step.stop_reason,
        step.error_code,
        step.safe_result_summary,
        _json_tuple(step.evidence_refs),
    )


def _feedback_plan_step_from_row(row: sqlite3.Row) -> ExecutionPlanStepFeedback:
    return ExecutionPlanStepFeedback(
        revision=int(row["revision"]),
        step_id=str(row["step_id"]),
        position=int(row["position"]),
        objective=str(row["objective"]),
        expected_outcome=str(row["expected_outcome"]),
        original_status=PlanStepStatus(str(row["original_status"])),
        outcome=PlanStepOutcome(str(row["outcome"])),
        stop_reason=(
            str(row["stop_reason"]) if row["stop_reason"] is not None else None
        ),
        error_code=(
            str(row["error_code"]) if row["error_code"] is not None else None
        ),
        safe_result_summary=(
            str(row["safe_result_summary"])
            if row["safe_result_summary"] is not None
            else None
        ),
        evidence_refs=_read_string_tuple(row["evidence_refs_json"]),
    )


def _plan_feedback_from_row(row: sqlite3.Row) -> ExecutionPlanStepFeedback:
    step = PlanStep(
        plan_id=str(row["plan_id"]),
        revision=int(row["revision"]),
        step_id=str(row["step_id"]),
        position=int(row["position"]),
        objective=str(row["objective"]),
        expected_outcome=str(row["expected_outcome"]),
        dependency_step_ids=_read_string_tuple(row["dependency_step_ids_json"]),
        status=PlanStepStatus(str(row["status"])),
        stop_reason=(
            str(row["stop_reason"]) if row["stop_reason"] is not None else None
        ),
        safe_result_summary=(
            str(row["safe_result_summary"])
            if row["safe_result_summary"] is not None
            else None
        ),
        error_code=(
            str(row["error_code"]) if row["error_code"] is not None else None
        ),
        evidence_refs=_read_string_tuple(row["evidence_refs_json"]),
        executor_steps_used=int(row["executor_steps_used"]),
        started_at=(
            str(row["started_at"]) if row["started_at"] is not None else None
        ),
        completed_at=(
            str(row["completed_at"]) if row["completed_at"] is not None else None
        ),
    )
    return ExecutionPlanStepFeedback(
        revision=step.revision,
        step_id=step.step_id,
        position=step.position,
        objective=step.objective,
        expected_outcome=step.expected_outcome,
        original_status=step.status,
        outcome=_plan_step_outcome(step),
        stop_reason=step.stop_reason,
        error_code=step.error_code,
        safe_result_summary=step.safe_result_summary,
        evidence_refs=step.evidence_refs,
    )


def _plan_step_outcome(step: PlanStep) -> PlanStepOutcome:
    if step.status is PlanStepStatus.COMPLETED:
        return PlanStepOutcome.COMPLETED
    if step.status in {
        PlanStepStatus.PENDING,
        PlanStepStatus.SUPERSEDED,
        PlanStepStatus.CANCELLED,
    }:
        return PlanStepOutcome.NOT_RUN
    if step.status is PlanStepStatus.STOPPED:
        if step.stop_reason == "safety_denied":
            return PlanStepOutcome.DENIED
        if step.stop_reason == "confirmation_required":
            return PlanStepOutcome.REQUIRES_CONFIRMATION
    return PlanStepOutcome.FAILED


def _json_tuple(values: tuple[str, ...]) -> str:
    return json.dumps(list(values), ensure_ascii=False, separators=(",", ":"))


def _read_string_tuple(value: object) -> tuple[str, ...]:
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError as exc:
        raise _persistence_failure() from exc
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        raise _persistence_failure()
    return tuple(parsed)


def _required_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")


def _conflict() -> ExecutionFeedbackRepositoryError:
    return ExecutionFeedbackRepositoryError(
        "Execution feedback conflicts with an existing finalized snapshot.",
        code="execution_feedback_source_conflict",
    )


def _persistence_failure() -> ExecutionFeedbackRepositoryError:
    return ExecutionFeedbackRepositoryError(
        "Execution feedback persistence failed.",
        code="execution_feedback_persistence_failed",
    )
