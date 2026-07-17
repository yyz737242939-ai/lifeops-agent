from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from app.executor.models import FinalAnswerDecision, ToolActionDecision
from app.executor.service import ReactExecutor
from app.intent.models import IntentDecision, IntentType
from app.policy.models import PolicyAction, PolicyDecision
from app.runtime.models import RuntimeRequest, RuntimeStatus
from app.runtime.service import RuntimeService
from app.skills.loader import discover_skills
from app.skills.models import SkillDefinition
from app.skills.registry import SkillRegistry
from app.skills.service import SkillService
from app.tools.models import (
    ToolCall,
    ToolCallStatus,
    ToolDefinition,
    ToolEffect,
    ToolResult,
    ToolRisk,
)
from app.tools.registry import ToolRegistry
from app.tools.runtime import ToolRuntime


class RuntimeObservabilityE2ETest(unittest.TestCase):
    def test_current_runtime_writes_readable_event_and_llm_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            request = RuntimeRequest(
                user_input="Inspect the fixture through the current Executor.",
                session_id="session_observability_e2e",
                run_id="run_observability_e2e",
                turn_id="turn_observability_e2e",
            )
            service = RuntimeService(
                SkillService(
                    SkillRegistry(discover_skills(Path("app/skills"))),
                    _LoggingSkillSelectionClient(),
                ),
                intent_service=_ReadIntentService(),
                policy_service=_ReadPolicyService(),
                log_root=tmpdir,
                execution_scope_factory=_tool_runtime,
                executor=ReactExecutor(_LoggingExecutorModelClient()),
            )

            result = service.handle(request)
            service.close()

            self.assertEqual(result.status, RuntimeStatus.OK)
            session_dirs = [item for item in Path(tmpdir).iterdir() if item.is_dir()]
            self.assertEqual(len(session_dirs), 1)
            session_dir = session_dirs[0]
            events = _read_jsonl(session_dir / "events.jsonl")
            llm_rows = _read_jsonl(session_dir / "llm.jsonl")
            trace_rows = _read_jsonl(session_dir / "traces.jsonl")

            event_types = [row["event_type"] for row in events]
            expected_flow = [
                "runtime.run.started",
                "intent.classified",
                "policy.decided",
                "orchestration.route.selected",
                "skill.selected",
                "skill.loaded",
                "tool.catalog.resolved",
                "executor.action.selected",
                "tool.call.requested",
                "tool.guardrail.decided",
                "tool.guardrail.decided",
                "tool.call.completed",
                "executor.observation.recorded",
                "executor.action.selected",
                "executor.stopped",
                "runtime.run.completed",
            ]
            positions: list[int] = []
            cursor = -1
            for name in expected_flow:
                cursor = event_types.index(name, cursor + 1)
                positions.append(cursor)
            self.assertEqual(positions, sorted(positions))
            self.assertEqual([row["seq"] for row in events], list(range(1, len(events) + 1)))
            self.assertTrue(
                all(row["run_id"] == request.run_id for row in events)
            )

            self.assertEqual([row["seq"] for row in llm_rows], [1, 2, 3])
            self.assertEqual(
                [row["request"]["operation"] for row in llm_rows],
                ["skill_selection", "executor_decision", "executor_decision"],
            )
            self.assertEqual(
                [row["response"]["decision_type"] for row in llm_rows[1:]],
                ["tool_action", "final_answer"],
            )
            self.assertTrue(
                all(row["run_id"] == request.run_id for row in llm_rows)
            )
            self.assertTrue((session_dir / "application.log").exists())
            self.assertTrue((session_dir / "annotations.jsonl").exists())

            spans = [row for row in trace_rows if row["record_type"] == "span"]
            artifacts = [
                row for row in trace_rows if row["record_type"] == "artifact_reference"
            ]
            trace_records = [
                row for row in trace_rows if row["record_type"] == "trace"
            ]
            self.assertEqual(len(trace_records), 1)
            self.assertEqual(trace_records[0]["run_id"], request.run_id)
            self.assertEqual(trace_records[0]["status"], "ok")
            self.assertEqual(
                {row["lifeops_span_kind"] for row in spans},
                {"RUNTIME", "INTENT", "POLICY", "SKILL", "EXECUTOR", "LLM", "TOOL", "GUARDRAIL"},
            )
            self.assertEqual(
                len([row for row in spans if row["lifeops_span_kind"] == "LLM"]),
                3,
            )
            llm_spans = {
                row["span_id"]: row
                for row in spans
                if row["lifeops_span_kind"] == "LLM"
            }
            llm_artifacts = [
                row for row in artifacts if row["artifact_type"] == "llm_interaction"
            ]
            self.assertEqual(len(llm_artifacts), 3)
            self.assertTrue(
                all(row["span_id"] in llm_spans for row in llm_artifacts)
            )
            self.assertTrue(
                all(row["sensitivity"] == "sensitive" for row in llm_artifacts)
            )
            self.assertEqual(
                len({row["safe_reference"] for row in llm_artifacts}),
                3,
            )
            self.assertTrue(
                all(
                    row["safe_reference"].startswith("llm.jsonl#id=logllm_")
                    for row in llm_artifacts
                )
            )
            self.assertEqual(
                [
                    span["attributes"]["llm.usage.total_tokens"]
                    for span in llm_spans.values()
                ],
                [12, 23, 23],
            )
            root = next(row for row in spans if row["lifeops_span_kind"] == "RUNTIME")
            self.assertIsNone(root["parent_span_id"])
            self.assertTrue(
                all(row["trace_id"] == trace_records[0]["trace_id"] for row in spans)
            )
            serialized_trace = (session_dir / "traces.jsonl").read_text(encoding="utf-8")
            for forbidden in (
                request.user_input,
                "messages",
                "private_reasoning",
                "confirmation",
            ):
                self.assertNotIn(forbidden, serialized_trace)


class _LoggingSkillSelectionClient:
    def select(
        self,
        request: RuntimeRequest,
        skill_metadata: tuple[SkillDefinition, ...],
        *,
        llm_log=None,
    ) -> dict[str, Any]:
        if llm_log is not None:
            llm_log.record(
                provider="fixture",
                model="skill-selector-fixture",
                request={"operation": "skill_selection", "skill_count": len(skill_metadata)},
                response={
                    "selected_skill_ids": ["research"],
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 2,
                        "total_tokens": 12,
                    },
                },
            )
        return {"selected_skill_ids": ["research"], "reason": "Research fixture."}


class _LoggingExecutorModelClient:
    def __init__(self) -> None:
        self._step = 0

    def decide(self, model_input, *, llm_log=None):
        self._step += 1
        if self._step == 1:
            decision = ToolActionDecision(
                ToolCall("call_observability", "research.inspect_fixture", {})
            )
            decision_type = "tool_action"
        else:
            decision = FinalAnswerDecision("Fixture inspection completed.")
            decision_type = "final_answer"
        if llm_log is not None:
            llm_log.record(
                provider="fixture",
                model="executor-fixture",
                request={
                    "operation": "executor_decision",
                    "step_index": model_input.step_index,
                    "observation_count": len(model_input.observations),
                },
                response={
                    "decision_type": decision_type,
                    "usage": {
                        "input_tokens": 20,
                        "output_tokens": 3,
                        "total_tokens": 23,
                    },
                },
            )
        return decision


class _ReadIntentService:
    def classify(self, request: RuntimeRequest) -> IntentDecision:
        return IntentDecision(IntentType.READ, 1.0)


class _ReadPolicyService:
    def evaluate(
        self,
        request: RuntimeRequest,
        intent: IntentDecision,
    ) -> PolicyDecision:
        return PolicyDecision(PolicyAction.ALLOW, allowed_effects=["read"])


def _tool_runtime() -> ToolRuntime:
    definition = ToolDefinition(
        name="research.inspect_fixture",
        description="Inspect one deterministic fixture.",
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"status": {"type": "string", "enum": ["ok"]}},
            "required": ["status"],
            "additionalProperties": False,
        },
        effect=ToolEffect.READ,
        risk=ToolRisk.LOW,
        skill_ids=("research",),
    )

    def handler(call: ToolCall) -> ToolResult:
        return ToolResult(
            call.call_id,
            call.tool_name,
            ToolCallStatus.SUCCEEDED,
            output={"status": "ok"},
        )

    return ToolRuntime.from_registry(ToolRegistry(((definition, handler),)))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    import json

    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


if __name__ == "__main__":
    unittest.main()
