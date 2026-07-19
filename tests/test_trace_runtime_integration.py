from __future__ import annotations

import tempfile
import unittest

from app.executor.models import FinalAnswerDecision, PlanStepExecutionInput
from app.executor.service import ReactExecutor
from app.observability.file_logs import RequestLlmLog, SessionLogWriter
from app.observability.logger import OptionalLogAppender
from app.observability.telemetry import RequestTelemetry
from app.observability.trace_vocabulary import TraceStatus
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


class TraceRuntimeIntegrationTest(unittest.TestCase):
    def test_plan_step_executor_has_invocation_and_plan_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logs = SessionLogWriter.create(tmpdir, session_id="session_1")
            request = RuntimeRequest("read fixture", "session_1", "turn_1", "run_1")
            telemetry = _telemetry(logs, request)
            executor = ReactExecutor(_FinalClient())

            result = executor.execute_step(
                request,
                PlanStepExecutionInput(
                    plan_id="plan_1", revision=2, step_id="step_1",
                    plan_goal="read fixture", current_objective="inspect fixture",
                    expected_outcome="fixture inspected",
                ),
                (),
                AllowedToolSet(()),
                ToolRuntime.from_registry(ToolRegistry()),
                trace=telemetry,
                llm_log=RequestLlmLog(logs.llm_log, request, telemetry),
            )
            telemetry.finish(status=TraceStatus.OK)

            self.assertEqual(result.final_message, "done")
            executor_span = next(
                row for row in logs.trace_exporter.read_all()
                if row["record_type"] == "span"
                and row["lifeops_span_kind"] == "EXECUTOR"
            )
            self.assertEqual(executor_span["attributes"]["lifeops.plan.id"], "plan_1")
            self.assertEqual(executor_span["attributes"]["lifeops.plan.revision"], 2)
            self.assertEqual(executor_span["attributes"]["lifeops.plan.step.id"], "step_1")
            self.assertTrue(executor_span["attributes"]["lifeops.executor.invocation_id"])

    def test_tool_guardrails_and_evidence_reference_are_nested_and_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logs = SessionLogWriter.create(tmpdir, session_id="session_1")
            request = RuntimeRequest("read fixture", "session_1", "turn_1", "run_1")
            telemetry = _telemetry(logs, request)
            definition = ToolDefinition(
                name="fixture.read", description="Read fixture.",
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                output_schema={
                    "type": "object", "properties": {"status": {"type": "string"}},
                    "required": ["status"], "additionalProperties": False,
                },
                effect=ToolEffect.READ, risk=ToolRisk.LOW, skill_ids=("fixture",),
            )

            def handler(call: ToolCall) -> ToolResult:
                return ToolResult(
                    call.call_id, call.tool_name, ToolCallStatus.SUCCEEDED,
                    output={"status": "ok"},
                    evidence=(ExecutionEvidence("fixture", "Fixture inspected.", "fixture/ref_1"),),
                )

            runtime = ToolRuntime.from_registry(ToolRegistry(((definition, handler),)))
            result = runtime.gateway.execute(
                ToolCall("call_1", "fixture.read", {}),
                AllowedToolSet(("fixture.read",)),
                trace=telemetry,
            )
            telemetry.finish(status=TraceStatus.OK)

            self.assertEqual(result.status, ToolCallStatus.SUCCEEDED)
            rows = logs.trace_exporter.read_all()
            spans = {row["span_id"]: row for row in rows if row["record_type"] == "span"}
            tool = next(row for row in spans.values() if row["lifeops_span_kind"] == "TOOL")
            guardrails = [row for row in spans.values() if row["lifeops_span_kind"] == "GUARDRAIL"]
            self.assertEqual(len(guardrails), 2)
            self.assertTrue(all(row["parent_span_id"] == tool["span_id"] for row in guardrails))
            artifact = next(row for row in rows if row["record_type"] == "artifact_reference")
            self.assertEqual(artifact["span_id"], tool["span_id"])
            self.assertEqual(artifact["safe_reference"], "fixture/ref_1")
            serialized = logs.trace_exporter.path.read_text(encoding="utf-8")
            self.assertNotIn("Fixture inspected.", serialized)
            self.assertNotIn('"output"', serialized)


class _FinalClient:
    def decide(self, model_input, *, llm_log=None):
        if llm_log is not None:
            llm_log.record(
                provider="fixture", model="fixture-model",
                request={"operation": "executor_decision"},
                response={"decision_type": "final_answer"},
            )
        return FinalAnswerDecision("done")


def _telemetry(logs: SessionLogWriter, request: RuntimeRequest) -> RequestTelemetry:
    return RequestTelemetry(
        run_id=request.run_id, session_id=request.session_id, turn_id=request.turn_id,
        legacy_sink=OptionalLogAppender(None), exporter=logs.trace_exporter,
        annotation_sink=logs.annotation_sink,
    )


if __name__ == "__main__":
    unittest.main()
