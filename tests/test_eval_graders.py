from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

from app.evals import (
    EVAL_MANIFEST_SCHEMA_VERSION,
    EvalCase,
    EvalExecutionMode,
    EvalExpectations,
    EvalStateSnapshot,
    EvaluationSubject,
    GradeStatus,
    build_state_delta,
    default_grader_registry,
)
from app.observability.trace_reader import FileTraceStore, TraceReader
from app.runtime_reporting import EvidenceReport, FactProjection, RuntimeReportBuilder
from app.runtime_reporting.providers import EmptyRuntimeFactProvider


class EvalDeterministicGradersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.graph = TraceReader(
            FileTraceStore(Path("tests/fixtures/traces/serial_diamond"))
        ).get_trace("trace_diamond")
        base = RuntimeReportBuilder().build(
            cls.graph,
            EmptyRuntimeFactProvider().load(cls.graph),
        )
        cls.report = replace(
            base,
            plan_report=(
                FactProjection("plan_run", "plan-1", "running", {"current_revision": 1}),
                FactProjection(
                    "plan_step",
                    "plan-1:1:step-1",
                    "completed",
                    {"step_id": "step-1", "revision": 1},
                ),
            ),
            tool_attempts=(
                FactProjection(
                    "trace_span:TOOL",
                    "tool-span-1",
                    "ok",
                    {
                        "lifeops.tool.name": "research.search",
                        "lifeops.tool.effect": "read",
                        "lifeops.tool.handler_reached": True,
                        "lifeops.tool.outcome": "succeeded",
                    },
                ),
            ),
            evidence=(EvidenceReport("artifact_reference", "evidence-1", "fixture/evidence-1"),),
            execution_feedback=FactProjection(
                "execution_feedback",
                "feedback-1",
                "completed",
                {"path": "planning", "action_count": 1, "evidence_count": 1},
            ),
            final_answer_validation=FactProjection(
                "final_answer_validation",
                "feedback-1:validation",
                "supported",
                {"accepted_claim_count": 1, "reason_count": 0},
            ),
            stop_point=FactProjection(
                "execution_stop_point", "feedback-1:stop", "completed"
            ),
        )
        cls.delta = build_state_delta(
            (EvalStateSnapshot("task-state", {"count": 0}),),
            (EvalStateSnapshot("task-state", {"count": 1}),),
        )
        cls.subject = EvaluationSubject(cls.report, cls.graph, cls.delta)
        cls.registry = default_grader_registry()

    def test_registry_contains_exactly_the_ten_ready_graders(self) -> None:
        self.assertEqual(
            self.registry.grader_ids,
            (
                "execution-path",
                "plan-lifecycle",
                "workflow-dependency",
                "tool-call",
                "state-change",
                "evidence",
                "execution-feedback",
                "final-answer-grounding",
                "trace-contract",
                "privacy",
            ),
        )

    def test_all_ten_graders_pass_current_typed_inputs(self) -> None:
        cases = {
            "execution-path": _case(execution_path={"equals": "planning"}),
            "plan-lifecycle": _case(
                plan_lifecycle={"status_by_id": {"plan-1": "running", "step-1": "completed"}}
            ),
            "workflow-dependency": _case(
                workflow_dependencies={
                    "status_by_id": {"A": "succeeded", "C": "failed", "D": "blocked"},
                    "linked_to": {"D": ["B", "C"]},
                }
            ),
            "tool-call": _case(
                tool_calls={
                    "contains_all": ["research.search"],
                    "contains_none": ["memory.save"],
                    "count": 1,
                    "status_by_id": {"research.search": "succeeded"},
                    "effect_by_id": {"research.search": "read"},
                    "handler_reached_by_id": {"research.search": True},
                }
            ),
            "state-change": _case(
                state_changes={
                    "count": 1,
                    "fact_delta": {"task-state.count": {"before": 0, "after": 1}},
                }
            ),
            "evidence": _case(
                evidence={"count": 1, "contains_all": ["artifact_reference"]}
            ),
            "execution-feedback": _case(
                execution_feedback={
                    "equals": "completed",
                    "attributes": {"path": "planning", "evidence_count": 1},
                    "stop_status": "completed",
                }
            ),
            "final-answer-grounding": _case(
                final_answer={
                    "equals": "supported",
                    "min_accepted_claim_count": 1,
                    "max_reason_count": 0,
                }
            ),
            "trace-contract": _case(
                trace_contract={
                    "status": "ok",
                    "required_spans": ["RUNTIME", "EXECUTOR"],
                    "forbidden_spans": ["EVALUATOR"],
                    "required_links": ["depends_on"],
                }
            ),
            "privacy": _case(privacy={"forbidden_fields": ["api_key", "raw_prompt"]}),
        }
        for grader_id, case in cases.items():
            with self.subTest(grader_id=grader_id):
                result = self.registry.get(grader_id).grade(case, self.subject)
                self.assertEqual(result.status, GradeStatus.PASSED, result)
                self.assertEqual(result.target_trace_id, "trace_diamond")

    def test_mismatch_missing_fields_and_invalid_expectations_are_distinct(self) -> None:
        failed = self.registry.get("tool-call").grade(
            _case(tool_calls={"contains_none": ["research.search"]}),
            self.subject,
        )
        self.assertEqual(failed.status, GradeStatus.FAILED)
        self.assertEqual(failed.reason_code, "tool-call_mismatch")

        unavailable = self.registry.get("state-change").grade(
            _case(state_changes={"count": 0}),
            EvaluationSubject(self.report, self.graph),
        )
        self.assertEqual(unavailable.status, GradeStatus.UNAVAILABLE)

        invalid = self.registry.get("execution-path").grade(
            _case(execution_path={"fuzzy": "planning"}),
            self.subject,
        )
        self.assertEqual(invalid.status, GradeStatus.ERROR)

        missing = self.registry.get("plan-lifecycle").grade(_case(), self.subject)
        self.assertEqual(missing.status, GradeStatus.SKIPPED)

        final_only = replace(self.report, plan_report=(), workflow_report=None, tool_attempts=())
        result = self.registry.get("execution-path").grade(
            _case(execution_path={"equals": "final_only"}),
            EvaluationSubject(final_only, self.graph),
        )
        self.assertEqual(result.status, GradeStatus.PASSED)

    def test_trace_and_privacy_require_canonical_graph(self) -> None:
        subject = EvaluationSubject(self.report)
        trace = self.registry.get("trace-contract").grade(
            _case(trace_contract={}), subject
        )
        privacy = self.registry.get("privacy").grade(_case(privacy={}), subject)
        self.assertEqual(trace.status, GradeStatus.ERROR)
        self.assertEqual(privacy.status, GradeStatus.ERROR)


def _case(**expectations) -> EvalCase:
    return EvalCase(
        schema_version=EVAL_MANIFEST_SCHEMA_VERSION,
        case_id="grader-case",
        title="Grader case",
        description="Pure typed grader fixture.",
        execution_mode=EvalExecutionMode.RUNTIME_REQUEST,
        input={"message": "fixture"},
        expectations=EvalExpectations(**expectations),
        grader_ids=("trace-contract",),
    )


if __name__ == "__main__":
    unittest.main()
