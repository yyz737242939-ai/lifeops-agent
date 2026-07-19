"""Request-local collection through the existing Executor feedback sink."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock

from app.common.validation import require_non_empty_string
from app.executor.models import (
    ExecutorFeedbackItem,
    ExecutorResult,
    PlanStepExecutionInput,
    ToolObservation,
)
from app.recovery.builder import ToolEffectBinding
from app.recovery.errors import ExecutionFeedbackCollectionError
from app.tools.models import ToolEffect


@dataclass(frozen=True)
class CollectedExecutorInvocation:
    run_id: str
    executor_invocation_id: str
    source_span_id: str
    observations: tuple[ToolObservation, ...]
    result: ExecutorResult
    tool_effects: tuple[ToolEffectBinding, ...]
    plan_step: PlanStepExecutionInput | None = None

    def __post_init__(self) -> None:
        for name in ("run_id", "executor_invocation_id", "source_span_id"):
            require_non_empty_string(getattr(self, name), name)
        if not isinstance(self.observations, tuple) or any(
            not isinstance(item, ToolObservation) for item in self.observations
        ):
            raise ValueError("observations must contain ToolObservation values.")
        if not isinstance(self.result, ExecutorResult):
            raise ValueError("result must be an ExecutorResult.")
        if self.result.run_id != self.run_id or self.result.observations != self.observations:
            raise ValueError("result must match collected run and observations.")
        if not isinstance(self.tool_effects, tuple) or any(
            not isinstance(item, ToolEffectBinding) for item in self.tool_effects
        ):
            raise ValueError("tool_effects must contain ToolEffectBinding values.")
        if self.plan_step is not None and not isinstance(
            self.plan_step, PlanStepExecutionInput
        ):
            raise ValueError("plan_step must be PlanStepExecutionInput when provided.")


@dataclass(frozen=True)
class CollectedExecutionFacts:
    run_id: str
    invocations: tuple[CollectedExecutorInvocation, ...]

    def __post_init__(self) -> None:
        require_non_empty_string(self.run_id, "run_id")
        if not isinstance(self.invocations, tuple) or any(
            not isinstance(item, CollectedExecutorInvocation)
            for item in self.invocations
        ):
            raise ValueError("invocations must contain CollectedExecutorInvocation values.")
        if not self.invocations:
            raise ValueError("invocations must not be empty.")
        if any(item.run_id != self.run_id for item in self.invocations):
            raise ValueError("every invocation must belong to run_id.")
        if len({item.executor_invocation_id for item in self.invocations}) != len(
            self.invocations
        ):
            raise ValueError("executor_invocation_id values must be unique.")


@dataclass
class _InvocationBuffer:
    run_id: str
    executor_invocation_id: str
    source_span_id: str
    plan_step: PlanStepExecutionInput | None
    observations: list[ToolObservation] = field(default_factory=list)
    tool_effects: dict[str, ToolEffect] = field(default_factory=dict)
    result: ExecutorResult | None = None


class RequestExecutionFeedbackCollector:
    """Buffer one request's ordered Executor facts; never persists run feedback."""

    def __init__(self) -> None:
        self._runs: dict[str, dict[str, _InvocationBuffer]] = {}
        self._invocation_runs: dict[str, str] = {}
        self._lock = RLock()

    def record(
        self,
        step_or_result: ExecutorFeedbackItem,
        *,
        run_id: str | None = None,
        executor_invocation_id: str | None = None,
        source_span_id: str | None = None,
        tool_effect: ToolEffect | None = None,
        plan_step: PlanStepExecutionInput | None = None,
    ) -> None:
        with self._lock:
            self._record(
                step_or_result,
                run_id=run_id,
                executor_invocation_id=executor_invocation_id,
                source_span_id=source_span_id,
                tool_effect=tool_effect,
                plan_step=plan_step,
            )

    def _record(
        self,
        step_or_result: ExecutorFeedbackItem,
        *,
        run_id: str | None = None,
        executor_invocation_id: str | None = None,
        source_span_id: str | None = None,
        tool_effect: ToolEffect | None = None,
        plan_step: PlanStepExecutionInput | None = None,
    ) -> None:
        require_non_empty_string(run_id, "run_id")
        require_non_empty_string(
            executor_invocation_id, "executor_invocation_id"
        )
        require_non_empty_string(source_span_id, "source_span_id")
        if not isinstance(step_or_result, (ToolObservation, ExecutorResult)):
            raise ValueError("step_or_result must be an Executor feedback item.")
        existing_run = self._invocation_runs.get(executor_invocation_id)
        if existing_run is not None and existing_run != run_id:
            raise _conflict("Executor invocation identity was reused across runs.")
        self._invocation_runs[executor_invocation_id] = run_id
        run_buffers = self._runs.setdefault(run_id, {})
        buffer = run_buffers.get(executor_invocation_id)
        if buffer is None:
            buffer = _InvocationBuffer(
                run_id,
                executor_invocation_id,
                source_span_id,
                plan_step,
            )
            run_buffers[executor_invocation_id] = buffer
        elif buffer.source_span_id != source_span_id or buffer.plan_step != plan_step:
            raise _conflict("Executor invocation correlation changed while collecting.")
        if buffer.result is not None:
            if isinstance(step_or_result, ExecutorResult) and buffer.result == step_or_result:
                return
            raise _conflict("Executor invocation received facts after terminal result.")

        if isinstance(step_or_result, ToolObservation):
            if not isinstance(tool_effect, ToolEffect):
                raise _incomplete("ToolObservation is missing ToolEffect.")
            if any(item.call_id == step_or_result.call_id for item in buffer.observations):
                raise _conflict("ToolObservation call_id was collected twice.")
            if buffer.observations and (
                step_or_result.step_index <= buffer.observations[-1].step_index
            ):
                raise _conflict("ToolObservation order is not strictly increasing.")
            previous_effect = buffer.tool_effects.get(step_or_result.tool_name)
            if previous_effect is not None and previous_effect is not tool_effect:
                raise _conflict("Tool effect changed within one Executor invocation.")
            buffer.tool_effects[step_or_result.tool_name] = tool_effect
            buffer.observations.append(step_or_result)
            return

        if tool_effect is not None:
            raise _conflict("terminal ExecutorResult must not carry ToolEffect.")
        if step_or_result.run_id != run_id:
            raise _conflict("ExecutorResult run_id does not match collector scope.")
        if step_or_result.observations != tuple(buffer.observations):
            raise _incomplete(
                "Collected observations do not match terminal ExecutorResult."
            )
        buffer.result = step_or_result

    def snapshot(self, run_id: str) -> CollectedExecutionFacts:
        with self._lock:
            return self._snapshot(run_id)

    def _snapshot(self, run_id: str) -> CollectedExecutionFacts:
        require_non_empty_string(run_id, "run_id")
        buffers = self._runs.get(run_id)
        if not buffers:
            raise _incomplete("No Execution Feedback facts were collected for run.")
        if any(item.result is None for item in buffers.values()):
            raise _incomplete("An Executor invocation is missing terminal result.")
        invocations = tuple(
            CollectedExecutorInvocation(
                run_id=item.run_id,
                executor_invocation_id=item.executor_invocation_id,
                source_span_id=item.source_span_id,
                observations=tuple(item.observations),
                result=item.result,
                tool_effects=tuple(
                    ToolEffectBinding(tool_name, effect)
                    for tool_name, effect in sorted(item.tool_effects.items())
                ),
                plan_step=item.plan_step,
            )
            for item in buffers.values()
            if item.result is not None
        )
        return CollectedExecutionFacts(run_id, invocations)

    def discard(self, run_id: str) -> None:
        with self._lock:
            require_non_empty_string(run_id, "run_id")
            removed = self._runs.pop(run_id, {})
            for invocation_id in removed:
                self._invocation_runs.pop(invocation_id, None)


def _conflict(message: str) -> ExecutionFeedbackCollectionError:
    return ExecutionFeedbackCollectionError(
        message, code="execution_feedback_source_conflict"
    )


def _incomplete(message: str) -> ExecutionFeedbackCollectionError:
    return ExecutionFeedbackCollectionError(
        message, code="execution_feedback_source_incomplete"
    )
