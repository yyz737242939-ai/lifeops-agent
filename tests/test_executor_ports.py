from __future__ import annotations

import inspect
import unittest
from dataclasses import fields

from app.executor.adapters import (
    EmptyExecutorContextProvider,
    EmptyExecutorMemoryProvider,
    NoOpActionConfirmationProvider,
    NoOpExecutorFeedbackSink,
    NoOpExecutorRecoveryHook,
)
from app.executor.models import (
    ExecutorContextContribution,
    ExecutorMemoryContribution,
    ExecutorModelInput,
    ExecutorResult,
    ExecutorStatus,
    ExecutorStopReason,
    FinalAnswerDecision,
    PlanStepExecutionInput,
)
from app.executor.ports import (
    ActionConfirmationProvider,
    ExecutorContextProvider,
    ExecutorFeedbackSink,
    ExecutorMemoryProvider,
    ExecutorModelClient,
    ExecutorRecoveryHook,
)
from app.runtime.models import RuntimeRequest
from app.tools.models import ToolCall, ToolDefinition, ToolEffect, ToolRisk
from tests.executor_fakes import (
    FakeActionConfirmationProvider,
    FakeExecutorContextProvider,
    FakeExecutorMemoryProvider,
    FakeExecutorModelClient,
    RecordingExecutorFeedbackSink,
    RecordingExecutorRecoveryHook,
)


_EMPTY_SCHEMA = {"type": "object", "properties": {}}


class ExecutorPortsTest(unittest.TestCase):
    def test_port_method_shapes_are_narrow_and_frozen(self) -> None:
        expected = {
            ExecutorModelClient.decide: ("self", "model_input", "llm_log"),
            ExecutorContextProvider.load: ("self", "request", "plan_step"),
            ExecutorMemoryProvider.load: ("self", "request", "plan_step"),
            ActionConfirmationProvider.confirm: (
                "self",
                "run_id",
                "call",
                "tool_definition",
            ),
            ExecutorRecoveryHook.on_stop: ("self", "result", "plan_step"),
            ExecutorFeedbackSink.record: ("self", "step_or_result", "plan_step"),
        }
        for method, parameters in expected.items():
            with self.subTest(method=method.__qualname__):
                self.assertEqual(
                    tuple(inspect.signature(method).parameters), parameters
                )

    def test_model_input_and_provider_contribution_fields_are_frozen(self) -> None:
        self.assertEqual(
            tuple(item.name for item in fields(ExecutorContextContribution)),
            ("content", "source"),
        )
        self.assertEqual(
            tuple(item.name for item in fields(ExecutorMemoryContribution)),
            ("content", "source"),
        )
        self.assertEqual(
            tuple(item.name for item in fields(ExecutorModelInput)),
            (
                "request",
                "prompt_contributions",
                "context_contributions",
                "memory_contributions",
                "tool_catalog",
                "observations",
                "step_index",
                "plan_step",
            ),
        )
        self.assertTrue(
            {item.name for item in fields(ExecutorModelInput)}.isdisjoint(
                {"policy", "allowed_tools", "execution_scope", "gateway", "trace"}
            )
        )

    def test_empty_and_no_op_adapters_have_no_authorizing_side_effect(self) -> None:
        request = RuntimeRequest(user_input="总结当前信息", session_id="session_1")
        result = _completed_result()
        call = ToolCall(call_id="call_1", tool_name="travel.get_trip")
        definition = ToolDefinition(
            name="travel.get_trip",
            description="Get one trip.",
            input_schema=_EMPTY_SCHEMA,
            output_schema=_EMPTY_SCHEMA,
            effect=ToolEffect.READ,
            risk=ToolRisk.LOW,
        )

        self.assertEqual(EmptyExecutorContextProvider().load(request), ())
        self.assertEqual(EmptyExecutorMemoryProvider().load(request), ())
        self.assertIsNone(
            NoOpActionConfirmationProvider().confirm(
                request.run_id, call, definition
            )
        )
        self.assertIsNone(NoOpExecutorRecoveryHook().on_stop(result))
        self.assertIsNone(NoOpExecutorFeedbackSink().record(result))

    def test_fake_model_and_read_providers_preserve_typed_inputs(self) -> None:
        request = RuntimeRequest(user_input="总结当前信息", session_id="session_1")
        context = (ExecutorContextContribution("Current context.", "context://1"),)
        memory = (ExecutorMemoryContribution("Saved memory.", "memory://1"),)
        model_input = ExecutorModelInput(
            request=request,
            context_contributions=context,
            memory_contributions=memory,
            step_index=1,
        )
        decision = FinalAnswerDecision("完成。")
        model = FakeExecutorModelClient([decision])
        context_provider = FakeExecutorContextProvider(context)
        memory_provider = FakeExecutorMemoryProvider(memory)

        self.assertIs(model.decide(model_input), decision)
        self.assertEqual(model.inputs, [model_input])
        self.assertEqual(context_provider.load(request), context)
        self.assertEqual(memory_provider.load(request), memory)
        self.assertEqual(context_provider.requests, [request])
        self.assertEqual(memory_provider.requests, [request])

    def test_confirmation_and_observer_fakes_only_record_exact_values(self) -> None:
        request = RuntimeRequest(user_input="保存信息", session_id="session_1")
        call = ToolCall(call_id="call_1", tool_name="research.create_note")
        definition = ToolDefinition(
            name="research.create_note",
            description="Create one note.",
            input_schema=_EMPTY_SCHEMA,
            output_schema=_EMPTY_SCHEMA,
            effect=ToolEffect.WRITE,
            risk=ToolRisk.MEDIUM,
        )
        result = _completed_result()
        confirmation = FakeActionConfirmationProvider(None)
        recovery = RecordingExecutorRecoveryHook()
        feedback = RecordingExecutorFeedbackSink()
        plan_step = PlanStepExecutionInput(
            "plan_1", 1, "step_1", "goal", "objective", "outcome"
        )

        self.assertIsNone(confirmation.confirm(request.run_id, call, definition))
        self.assertEqual(
            confirmation.requests, [(request.run_id, call, definition)]
        )
        self.assertIsNone(recovery.on_stop(result, plan_step=plan_step))
        self.assertIsNone(feedback.record(result, plan_step=plan_step))
        self.assertEqual(recovery.results, [result])
        self.assertEqual(feedback.items, [result])
        self.assertEqual(recovery.plan_steps, [plan_step])
        self.assertEqual(feedback.plan_steps, [plan_step])


def _completed_result() -> ExecutorResult:
    return ExecutorResult(
        run_id="run_1",
        status=ExecutorStatus.COMPLETED,
        stop_reason=ExecutorStopReason.FINAL_ANSWER,
        final_message="完成。",
        step_count=1,
    )


if __name__ == "__main__":
    unittest.main()
