"""In-memory PlanningState for Plan and Execute v0."""

from pydantic import BaseModel, Field, field_validator

from app.planning.plan_types import PlanRun, PlanStep


class PlanningState(BaseModel):
    """Transient pending and active plan holder for one Agent instance."""

    pending_plan: PlanRun | None = None
    active_plan: PlanRun | None = None
    turn_index: int = 0

    @field_validator("turn_index")
    @classmethod
    def turn_index_must_not_be_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("turn_index cannot be negative")
        return value

    def create_pending_plan(
        self,
        *,
        goal: str,
        steps: list[PlanStep],
        source_user_input_summary: str,
    ) -> PlanRun:
        if self.pending_plan is not None and not self.pending_plan.is_terminal:
            self.pending_plan.supersede()
        plan = PlanRun(
            goal=goal,
            steps=steps,
            source_user_input_summary=source_user_input_summary,
        )
        self.pending_plan = plan
        return plan

    def set_pending_plan(self, plan: PlanRun) -> PlanRun:
        if plan.status != "pending_confirmation":
            raise RuntimeError("Only pending plans can be stored as pending")
        if self.pending_plan is not None and not self.pending_plan.is_terminal:
            self.pending_plan.supersede()
        self.pending_plan = plan
        return plan

    def confirm_pending_plan(self) -> PlanRun:
        plan = self._require_pending_plan()
        plan.confirm()
        if self.active_plan is not None and not self.active_plan.is_terminal:
            self.active_plan.supersede()
        self.active_plan = plan
        self.pending_plan = None
        return plan

    def cancel_pending_plan(self) -> PlanRun:
        plan = self._require_pending_plan()
        plan.cancel()
        self.pending_plan = None
        return plan

    def expire_pending_plan(self) -> PlanRun:
        plan = self._require_pending_plan()
        plan.expire()
        self.pending_plan = None
        return plan

    def cancel_active_plan(self) -> PlanRun:
        plan = self._require_active_plan()
        plan.cancel()
        self.active_plan = None
        return plan

    def supersede_active_plan(
        self,
        *,
        goal: str,
        steps: list[PlanStep],
        source_user_input_summary: str,
    ) -> PlanRun:
        active_plan = self._require_active_plan()
        active_plan.supersede()
        self.active_plan = None
        return self.create_pending_plan(
            goal=goal,
            steps=steps,
            source_user_input_summary=source_user_input_summary,
        )

    @property
    def current_step(self) -> PlanStep | None:
        if self.active_plan is None:
            return None
        return self.active_plan.current_step

    def start_current_step(self) -> PlanStep:
        return self._require_active_plan().start_current_step()

    def mark_current_step_done(
        self,
        *,
        last_run_id: str | None = None,
        result_summary: str | None = None,
    ) -> PlanStep:
        return self._require_active_plan().mark_current_step_done(
            last_run_id=last_run_id,
            result_summary=result_summary,
        )

    def mark_current_step_blocked(self, blocker: str) -> PlanStep:
        return self._require_active_plan().mark_current_step_blocked(blocker)

    def mark_current_step_failed(self, summary: str | None = None) -> PlanStep:
        return self._require_active_plan().mark_current_step_failed(summary)

    def advance_turn(self) -> int:
        self.turn_index += 1
        return self.turn_index

    def _require_pending_plan(self) -> PlanRun:
        if self.pending_plan is None:
            raise RuntimeError("No pending plan")
        if self.pending_plan.is_terminal:
            raise RuntimeError("Pending plan is terminal")
        return self.pending_plan

    def _require_active_plan(self) -> PlanRun:
        if self.active_plan is None:
            raise RuntimeError("No active plan")
        if self.active_plan.is_terminal:
            raise RuntimeError("Active plan is terminal")
        return self.active_plan
