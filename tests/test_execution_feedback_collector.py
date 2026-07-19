from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import unittest

from app.executor.models import (
    ExecutorResult,
    ExecutorStatus,
    ExecutorStopReason,
    PlanStepExecutionInput,
    ToolObservation,
)
from app.recovery.collector import RequestExecutionFeedbackCollector
from app.recovery.errors import ExecutionFeedbackCollectionError
from app.tools.models import ToolCallStatus, ToolEffect


class RequestExecutionFeedbackCollectorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.collector = RequestExecutionFeedbackCollector()

    def test_collects_ordered_direct_observations_and_terminal_result(self) -> None:
        observation = _observation(1, "call_1")
        result = _completed("run_1", observation)

        self.collector.record(
            observation,
            run_id="run_1",
            executor_invocation_id="execinv_1",
            source_span_id="span_1",
            tool_effect=ToolEffect.READ,
        )
        self.collector.record(
            result,
            run_id="run_1",
            executor_invocation_id="execinv_1",
            source_span_id="span_1",
        )

        snapshot = self.collector.snapshot("run_1")
        self.assertEqual(len(snapshot.invocations), 1)
        invocation = snapshot.invocations[0]
        self.assertEqual(invocation.observations, (observation,))
        self.assertEqual(invocation.result, result)
        self.assertEqual(invocation.tool_effects[0].tool_name, observation.tool_name)
        self.assertEqual(invocation.tool_effects[0].effect, ToolEffect.READ)

    def test_planning_invocations_keep_exact_step_identity_and_order(self) -> None:
        first_step = _plan_step("read")
        second_step = _plan_step("save")
        self._record_complete("run_1", "execinv_1", "span_1", first_step, "call_1")
        self._record_complete("run_1", "execinv_2", "span_2", second_step, "call_2")

        snapshot = self.collector.snapshot("run_1")

        self.assertEqual(
            tuple(item.executor_invocation_id for item in snapshot.invocations),
            ("execinv_1", "execinv_2"),
        )
        self.assertEqual(
            tuple(item.plan_step.step_id for item in snapshot.invocations if item.plan_step),
            ("read", "save"),
        )

    def test_runs_are_isolated_and_discard_removes_only_target_run(self) -> None:
        self._record_complete("run_1", "execinv_1", "span_1", None, "call_1")
        self._record_complete("run_2", "execinv_2", "span_2", None, "call_2")

        self.collector.discard("run_1")

        with self.assertRaises(ExecutionFeedbackCollectionError) as caught:
            self.collector.snapshot("run_1")
        self.assertEqual(caught.exception.code, "execution_feedback_source_incomplete")
        self.assertEqual(self.collector.snapshot("run_2").run_id, "run_2")

    def test_concurrent_runs_keep_request_facts_isolated(self) -> None:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = (
                executor.submit(
                    self._record_complete,
                    "run_1",
                    "execinv_1",
                    "span_1",
                    None,
                    "call_1",
                ),
                executor.submit(
                    self._record_complete,
                    "run_2",
                    "execinv_2",
                    "span_2",
                    None,
                    "call_2",
                ),
            )
            for future in futures:
                future.result()

        self.assertEqual(
            self.collector.snapshot("run_1").invocations[0].observations[0].call_id,
            "call_1",
        )
        self.assertEqual(
            self.collector.snapshot("run_2").invocations[0].observations[0].call_id,
            "call_2",
        )

    def test_missing_effect_and_missing_terminal_result_fail_closed(self) -> None:
        observation = _observation(1, "call_1")
        with self.assertRaises(ExecutionFeedbackCollectionError) as missing_effect:
            self.collector.record(
                observation,
                run_id="run_1",
                executor_invocation_id="execinv_1",
                source_span_id="span_1",
            )
        self.assertEqual(
            missing_effect.exception.code, "execution_feedback_source_incomplete"
        )

        self.collector.record(
            observation,
            run_id="run_1",
            executor_invocation_id="execinv_1",
            source_span_id="span_1",
            tool_effect=ToolEffect.READ,
        )
        with self.assertRaises(ExecutionFeedbackCollectionError) as incomplete:
            self.collector.snapshot("run_1")
        self.assertEqual(incomplete.exception.code, "execution_feedback_source_incomplete")

    def test_changed_correlation_and_cross_run_invocation_reuse_are_conflicts(self) -> None:
        observation = _observation(1, "call_1")
        self.collector.record(
            observation,
            run_id="run_1",
            executor_invocation_id="execinv_1",
            source_span_id="span_1",
            tool_effect=ToolEffect.READ,
        )
        with self.assertRaises(ExecutionFeedbackCollectionError) as changed:
            self.collector.record(
                _completed("run_1", observation),
                run_id="run_1",
                executor_invocation_id="execinv_1",
                source_span_id="different_span",
            )
        self.assertEqual(changed.exception.code, "execution_feedback_source_conflict")

        with self.assertRaises(ExecutionFeedbackCollectionError) as reused:
            self.collector.record(
                _observation(1, "call_2"),
                run_id="run_2",
                executor_invocation_id="execinv_1",
                source_span_id="span_2",
                tool_effect=ToolEffect.READ,
            )
        self.assertEqual(reused.exception.code, "execution_feedback_source_conflict")

    def test_terminal_result_must_match_collected_observations(self) -> None:
        observation = _observation(1, "call_1")
        self.collector.record(
            observation,
            run_id="run_1",
            executor_invocation_id="execinv_1",
            source_span_id="span_1",
            tool_effect=ToolEffect.READ,
        )

        with self.assertRaises(ExecutionFeedbackCollectionError) as caught:
            self.collector.record(
                _completed("run_1"),
                run_id="run_1",
                executor_invocation_id="execinv_1",
                source_span_id="span_1",
            )
        self.assertEqual(caught.exception.code, "execution_feedback_source_incomplete")

    def _record_complete(
        self,
        run_id: str,
        invocation_id: str,
        span_id: str,
        plan_step: PlanStepExecutionInput | None,
        call_id: str,
    ) -> None:
        observation = _observation(1, call_id)
        self.collector.record(
            observation,
            run_id=run_id,
            executor_invocation_id=invocation_id,
            source_span_id=span_id,
            tool_effect=ToolEffect.READ,
            plan_step=plan_step,
        )
        self.collector.record(
            _completed(run_id, observation),
            run_id=run_id,
            executor_invocation_id=invocation_id,
            source_span_id=span_id,
            plan_step=plan_step,
        )


def _observation(step_index: int, call_id: str) -> ToolObservation:
    return ToolObservation(
        step_index,
        call_id,
        "research.search_knowledge",
        ToolCallStatus.SUCCEEDED,
    )


def _completed(run_id: str, *observations: ToolObservation) -> ExecutorResult:
    return ExecutorResult(
        run_id,
        ExecutorStatus.COMPLETED,
        ExecutorStopReason.FINAL_ANSWER,
        "done",
        len(observations) + 1,
        observations,
    )


def _plan_step(step_id: str) -> PlanStepExecutionInput:
    return PlanStepExecutionInput(
        "plan_1",
        1,
        step_id,
        "goal",
        f"objective {step_id}",
        f"outcome {step_id}",
    )


if __name__ == "__main__":
    unittest.main()
