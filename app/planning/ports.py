"""Narrow public ports for Plan-and-Execute model boundaries."""

from __future__ import annotations

from typing import Protocol

from app.observability.logger import LlmInteractionSink
from app.observability.logger import TraceSink
from app.executor.models import ExecutorResult, PlanStepExecutionInput
from app.runtime.models import RuntimeRequest
from app.skills.models import PromptContribution
from app.tools.models import AllowedToolSet
from app.tools.runtime import ToolRuntime
from app.planning.models import (
    PlanCommand,
    PlanDraft,
    PlanDraftResult,
    PlanFinalizerInput,
    PlanFinalizerOutput,
    PlanRun,
    PlanRunStatus,
    PlanStep,
    PlanStepStatus,
    PlannerInput,
    PlanningLimits,
    PlanningRouteDecision,
    PlanningRouteInput,
    PlanningScopeRef,
    PlanningSnapshotEnvelope,
    ReplanInput,
)


class PlanningRouteClient(Protocol):
    def decide(
        self,
        route_input: PlanningRouteInput,
        *,
        llm_log: LlmInteractionSink | None = None,
    ) -> PlanningRouteDecision:
        ...


class PlannerModelClient(Protocol):
    def create_plan(
        self,
        planner_input: PlannerInput,
        *,
        llm_log: LlmInteractionSink | None = None,
    ) -> PlanDraftResult:
        ...

    def replan(
        self,
        replan_input: ReplanInput,
        *,
        llm_log: LlmInteractionSink | None = None,
    ) -> PlanDraftResult:
        ...


class PlanningSnapshotProvider(Protocol):
    def load(
        self, scope_refs: tuple[PlanningScopeRef, ...]
    ) -> tuple[PlanningSnapshotEnvelope, ...]:
        ...


class PlanRepository(Protocol):
    def create_initial_plan(
        self,
        *,
        session_id: str,
        goal: str,
        draft: PlanDraft,
        limits: PlanningLimits,
        plan_id: str | None = None,
    ) -> tuple[PlanRun, tuple[PlanStep, ...]]:
        ...

    def get_plan(
        self, session_id: str, plan_id: str, *, recover_interrupted: bool = False
    ) -> tuple[PlanRun, tuple[PlanStep, ...]]:
        ...

    def list_steps(self, plan_id: str, revision: int) -> tuple[PlanStep, ...]:
        ...

    def list_completed_steps(
        self, plan_id: str, through_revision: int
    ) -> tuple[PlanStep, ...]:
        ...

    def apply_command(
        self,
        command: PlanCommand,
        *,
        replacement_draft: PlanDraft | None = None,
        limits: PlanningLimits | None = None,
    ) -> tuple[PlanRun, tuple[PlanStep, ...]]:
        ...

    def claim_ready_step(
        self, session_id: str, plan_id: str, revision: int
    ) -> PlanStep | None:
        ...

    def record_step_result(
        self,
        *,
        session_id: str,
        plan_id: str,
        revision: int,
        step_id: str,
        status: PlanStepStatus,
        executor_steps_used: int,
        limits: PlanningLimits,
        safe_result_summary: str | None = None,
        stop_reason: str | None = None,
        error_code: str | None = None,
        evidence_refs: tuple[str, ...] = (),
    ) -> tuple[PlanRun, PlanStep]:
        ...

    def create_replan_revision(
        self,
        *,
        session_id: str,
        plan_id: str,
        expected_revision: int,
        draft: PlanDraft,
        limits: PlanningLimits,
    ) -> tuple[PlanRun, tuple[PlanStep, ...]]:
        ...

    def finish_plan(
        self,
        session_id: str,
        plan_id: str,
        revision: int,
        status: PlanRunStatus,
        *,
        error_code: str | None = None,
    ) -> PlanRun:
        ...


class PlanStepExecutor(Protocol):
    def execute_step(
        self,
        request: RuntimeRequest,
        step_input: PlanStepExecutionInput,
        prompt_contributions: tuple[PromptContribution, ...],
        allowed_tools: AllowedToolSet,
        execution_scope: ToolRuntime,
        trace: TraceSink | None = None,
        llm_log: LlmInteractionSink | None = None,
    ) -> ExecutorResult:
        ...


class PlanFinalizerClient(Protocol):
    def finalize(
        self,
        finalizer_input: PlanFinalizerInput,
        *,
        llm_log: LlmInteractionSink | None = None,
    ) -> PlanFinalizerOutput:
        ...
