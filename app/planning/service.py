"""Preview-first application service for structured plan commands."""

from __future__ import annotations

from dataclasses import replace

from app.observability.logger import LlmInteractionSink
from app.planning.errors import PlanContractError
from app.planning.models import (
    PlanCommand,
    PlanCommandAction,
    PlanDraft,
    PlanPreview,
    PlannerInput,
    PlannerNeedUser,
    PlanningLimits,
    PlanningScopeRef,
)
from app.planning.ports import (
    PlannerModelClient,
    PlanningSnapshotProvider,
    PlanRepository,
)


class PlanningService:
    """Create durable previews and apply explicit revision-bound commands."""

    def __init__(
        self,
        planner: PlannerModelClient,
        repository: PlanRepository,
        *,
        limits: PlanningLimits | None = None,
        snapshot_provider: PlanningSnapshotProvider | None = None,
    ) -> None:
        self._planner = planner
        self._repository = repository
        self._limits = limits or PlanningLimits()
        self._snapshot_provider = snapshot_provider

    def create_preview(
        self,
        session_id: str,
        planner_input: PlannerInput,
        *,
        scope_refs: tuple[PlanningScopeRef, ...] = (),
        llm_log: LlmInteractionSink | None = None,
    ) -> PlanPreview | PlannerNeedUser:
        self._validate_input_limits(planner_input)
        planner_input = self._with_snapshots(planner_input, scope_refs)
        result = self._planner.create_plan(planner_input, llm_log=llm_log)
        if isinstance(result, PlannerNeedUser):
            return result
        if not isinstance(result, PlanDraft):
            raise PlanContractError("Planner result is invalid.", code="plan_contract_invalid")
        run, steps = self._repository.create_initial_plan(
            session_id=session_id,
            goal=planner_input.goal,
            draft=result,
            limits=self._limits,
        )
        return PlanPreview(run, steps)

    def get_preview(self, session_id: str, plan_id: str) -> PlanPreview:
        run, steps = self._repository.get_plan(session_id, plan_id)
        return PlanPreview(run, steps)

    def confirm(self, command: PlanCommand) -> PlanPreview:
        self._require_action(command, PlanCommandAction.CONFIRM)
        run, steps = self._repository.apply_command(command)
        return PlanPreview(run, steps)

    def cancel(self, command: PlanCommand) -> PlanPreview:
        self._require_action(command, PlanCommandAction.CANCEL)
        run, steps = self._repository.apply_command(command)
        return PlanPreview(run, steps)

    def modify_preview(
        self,
        command: PlanCommand,
        planner_input: PlannerInput,
        *,
        scope_refs: tuple[PlanningScopeRef, ...] = (),
        llm_log: LlmInteractionSink | None = None,
    ) -> PlanPreview | PlannerNeedUser:
        self._require_action(command, PlanCommandAction.MODIFY)
        self._validate_input_limits(planner_input)
        planner_input = self._with_snapshots(planner_input, scope_refs)
        current = self.get_preview(command.session_id, command.plan_id)
        if planner_input.goal != current.run.goal:
            raise PlanContractError(
                "Modify input must preserve the original plan goal.",
                code="plan_contract_invalid",
            )
        modified_input = replace(
            planner_input,
            confirmed_constraints=(
                *current.run.confirmed_constraints,
                *(
                    ()
                    if command.feedback in current.run.confirmed_constraints
                    else (command.feedback,)
                ),
            ),
        )
        result = self._planner.create_plan(modified_input, llm_log=llm_log)
        if isinstance(result, PlannerNeedUser):
            return result
        if not isinstance(result, PlanDraft):
            raise PlanContractError("Planner result is invalid.", code="plan_contract_invalid")
        run, steps = self._repository.apply_command(
            command,
            replacement_draft=result,
            limits=self._limits,
        )
        return PlanPreview(run, steps)

    def _validate_input_limits(self, planner_input: PlannerInput) -> None:
        if not isinstance(planner_input, PlannerInput):
            raise PlanContractError("Planner input is invalid.", code="plan_contract_invalid")
        if planner_input.limits != self._limits:
            raise PlanContractError(
                "Planner limits must match composition limits.",
                code="plan_contract_invalid",
            )

    def _with_snapshots(
        self,
        planner_input: PlannerInput,
        scope_refs: tuple[PlanningScopeRef, ...],
    ) -> PlannerInput:
        if not isinstance(scope_refs, tuple) or any(
            not isinstance(item, PlanningScopeRef) for item in scope_refs
        ):
            raise PlanContractError(
                "Planning scope references are invalid.", code="plan_contract_invalid"
            )
        if not scope_refs:
            return planner_input
        if self._snapshot_provider is None:
            raise PlanContractError(
                "Planning snapshot provider is unavailable.",
                code="plan_contract_invalid",
            )
        return replace(
            planner_input,
            snapshots=self._snapshot_provider.load(scope_refs),
        )

    @staticmethod
    def _require_action(command: PlanCommand, action: PlanCommandAction) -> None:
        if not isinstance(command, PlanCommand) or command.action != action:
            raise PlanContractError("Plan command action is invalid.", code="plan_contract_invalid")
