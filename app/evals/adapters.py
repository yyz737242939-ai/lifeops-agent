"""Typed Eval-owned fact adapters over existing isolated repository Ports."""

from __future__ import annotations

from app.common.validation import require_non_empty_string
from app.observability.trace_reader import TraceGraph
from app.planning.errors import PlanRepositoryError
from app.planning.ports import PlanRepository
from app.runtime_reporting import FactProjection, RuntimeFactBundle


class PlanLifecycleFactSource:
    """Project one isolated PlanRepository result into shared runtime facts."""

    def __init__(self, repository: PlanRepository, plan_id: str) -> None:
        require_non_empty_string(plan_id, "plan_id")
        self._repository = repository
        self._plan_id = plan_id

    def load(self, trace: TraceGraph) -> RuntimeFactBundle:
        if not isinstance(trace, TraceGraph):
            raise ValueError("trace must be a TraceGraph.")
        try:
            plan, steps = self._repository.get_plan(
                trace.trace.session_id,
                self._plan_id,
                recover_interrupted=False,
            )
        except PlanRepositoryError:
            return RuntimeFactBundle(
                fact_source_warnings=("plan_lifecycle_unavailable",)
            )
        if (
            plan.plan_id != self._plan_id
            or plan.session_id != trace.trace.session_id
            or any(step.plan_id != plan.plan_id for step in steps)
        ):
            return RuntimeFactBundle(
                fact_source_warnings=("plan_lifecycle_identity_conflict",)
            )
        plan_projection = FactProjection(
            source_kind="plan_run",
            source_id=plan.plan_id,
            status=plan.status.value,
            attributes={
                "current_revision": plan.current_revision,
                "replan_count": plan.replan_count,
                "executor_steps_used": plan.executor_steps_used,
                "step_count": len(steps),
            },
        )
        step_projections = tuple(
            FactProjection(
                source_kind="plan_step",
                source_id=f"{step.plan_id}:{step.revision}:{step.step_id}",
                status=step.status.value,
                attributes={
                    "plan_id": step.plan_id,
                    "revision": step.revision,
                    "step_id": step.step_id,
                    "position": step.position,
                    "dependency_count": len(step.dependency_step_ids),
                    "executor_steps_used": step.executor_steps_used,
                    "evidence_count": len(step.evidence_refs),
                    **(
                        {"dependency_step_ids": step.dependency_step_ids}
                        if step.dependency_step_ids
                        else {}
                    ),
                    **(
                        {"stop_reason": step.stop_reason}
                        if step.stop_reason is not None
                        else {}
                    ),
                    **(
                        {"error_code": step.error_code}
                        if step.error_code is not None
                        else {}
                    ),
                },
            )
            for step in sorted(steps, key=lambda item: (item.revision, item.position))
        )
        return RuntimeFactBundle(
            plan_runs_and_steps=(plan_projection, *step_projections)
        )
