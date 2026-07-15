from __future__ import annotations

import unittest

from app.executor.models import FinalAnswerDecision, ToolActionDecision
from app.executor.service import ReactExecutor
from app.runtime.models import RuntimeRequest
from app.tools.models import (
    AllowedToolSet,
    ExecutionEvidence,
    ToolCall,
    ToolCallStatus,
    ToolDefinition,
    ToolEffect,
    ToolResult,
    ToolRisk,
)
from app.tools.registry import ToolRegistry
from app.tools.runtime import ToolRuntime
from tests.executor_fakes import (
    FakeExecutorModelClient,
    RecordingExecutorFeedbackSink,
    RecordingExecutorRecoveryHook,
)


_EMPTY_SCHEMA = {"type": "object", "properties": {}}


class ExecutorObservabilityTest(unittest.TestCase):
    def test_executor_events_are_ordered_semantic_and_content_safe(self) -> None:
        secret = "private-tool-argument-and-output"
        call = ToolCall(
            call_id="call_1",
            tool_name="general.read",
            arguments={"secret": secret},
        )
        trace = RecordingTrace()
        feedback = RecordingExecutorFeedbackSink()
        recovery = RecordingExecutorRecoveryHook()

        result = ReactExecutor(
            FakeExecutorModelClient(
                [ToolActionDecision(call), FinalAnswerDecision("完成。")]
            ),
            feedback_sink=feedback,
            recovery_hook=recovery,
        ).execute(_request(), (), _allowed(), _runtime(secret), trace=trace)

        executor_events = [
            item for item in trace.events if item[0].startswith("executor.")
        ]
        self.assertEqual(
            [item[0] for item in executor_events],
            [
                "executor.action.selected",
                "executor.observation.recorded",
                "executor.action.selected",
                "executor.stopped",
            ],
        )
        self.assertEqual(
            set(executor_events[0][1]),
            {"step_index", "decision_type", "call_id", "tool_name"},
        )
        self.assertEqual(
            set(executor_events[1][1]),
            {
                "step_index",
                "call_id",
                "tool_name",
                "status",
                "error_code",
                "retryable",
                "evidence_count",
            },
        )
        self.assertNotIn(secret, repr(executor_events))
        self.assertEqual(
            [item[0] for item in trace.events].count("tool.call.requested"), 1
        )
        self.assertEqual(
            [item[0] for item in trace.events].count("tool.call.completed"), 1
        )
        self.assertEqual(feedback.items, [result.observations[0], result])
        self.assertEqual(recovery.results, [result])

    def test_hook_failures_preserve_result_and_emit_safe_diagnostics(self) -> None:
        trace = RecordingTrace()
        result = ReactExecutor(
            FakeExecutorModelClient([FinalAnswerDecision("完成。")]),
            feedback_sink=_ExplodingFeedbackSink(),
            recovery_hook=_ExplodingRecoveryHook(),
        ).execute(_request(), (), AllowedToolSet(), _runtime("unused"), trace=trace)

        self.assertEqual(result.final_message, "完成。")
        failures = [item for item in trace.events if item[0] == "executor.hook.failed"]
        self.assertEqual(
            [item[1]["hook"] for item in failures],
            ["feedback", "recovery"],
        )
        self.assertNotIn("private-hook-path", repr(failures))


class RecordingTrace:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def append(self, event_type: str, payload=None) -> None:
        self.events.append((event_type, payload or {}))


class _ExplodingFeedbackSink:
    def record(self, step_or_result, *, plan_step=None) -> None:
        raise RuntimeError("private-hook-path")


class _ExplodingRecoveryHook:
    def on_stop(self, result, *, plan_step=None) -> None:
        raise RuntimeError("private-hook-path")


def _runtime(secret: str) -> ToolRuntime:
    definition = ToolDefinition(
        name="general.read",
        description="Read one value.",
        input_schema={
            "type": "object",
            "properties": {"secret": {"type": "string"}},
            "required": ["secret"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        effect=ToolEffect.READ,
        risk=ToolRisk.LOW,
    )

    def handler(call: ToolCall) -> ToolResult:
        return ToolResult(
            call_id=call.call_id,
            tool_name=call.tool_name,
            status=ToolCallStatus.SUCCEEDED,
            output={"value": secret},
            evidence=(ExecutionEvidence("read", "One value was read."),),
        )

    return ToolRuntime.from_registry(ToolRegistry(((definition, handler),)))


def _allowed() -> AllowedToolSet:
    return AllowedToolSet(("general.read",))


def _request() -> RuntimeRequest:
    return RuntimeRequest(
        user_input="读取信息",
        session_id="session_test",
        run_id="run_test",
    )


if __name__ == "__main__":
    unittest.main()
