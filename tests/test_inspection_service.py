from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

from app.inspection import (
    InspectionQuery,
    InspectionTarget,
    InspectionView,
    InspectorError,
    InspectorErrorCode,
    InspectorService,
)
from app.runtime_reporting import ReportIdentity, RuntimeFactBundle, RuntimeReport
from app.observability.trace_reader import FileTraceStore, TraceReader


class InspectorServiceTest(unittest.TestCase):
    def test_dispatches_only_through_shared_reader_and_report_ports(self) -> None:
        for target, expected in (
            (InspectionTarget(trace_id="trace_1"), ("trace", "trace_1")),
            (InspectionTarget(run_id="run_1"), ("run", "run_1")),
            (InspectionTarget(plan_id="plan_1"), ("plan", "plan_1")),
        ):
            with self.subTest(target=target):
                reader = _Reader()
                facts = _Facts()
                builder = _Builder()
                service = InspectorService(
                    trace_reader=reader,
                    fact_provider=facts,
                    report_builder=builder,
                )

                result = service.inspect(
                    InspectionQuery(target, views=(InspectionView.SUMMARY,))
                )

                self.assertEqual(reader.calls, [expected])
                expected_graphs = 2 if target.plan_id is not None else 1
                self.assertEqual(len(facts.graphs), expected_graphs)
                self.assertEqual(builder.inputs, list(zip(facts.graphs, facts.bundles)))
                self.assertEqual(len(result.runtime_reports), expected_graphs)

    def test_service_output_is_deterministic_for_same_shared_inputs(self) -> None:
        service = InspectorService(
            trace_reader=_Reader(),
            fact_provider=_Facts(),
            report_builder=_Builder(),
        )
        query = InspectionQuery(InspectionTarget(run_id="run_1"))

        self.assertEqual(service.inspect(query), service.inspect(query))

    def test_safe_failures_are_stable_and_do_not_fall_through(self) -> None:
        cases = (
            (_FailingReader(), _Facts(), _Builder(), InspectorErrorCode.TARGET_NOT_FOUND),
            (_Reader(), _Facts(), _FailingBuilder(), InspectorErrorCode.REPORT_BUILDER_FAILED),
        )
        for reader, facts, builder, code in cases:
            with self.subTest(code=code):
                service = InspectorService(
                    trace_reader=reader,
                    fact_provider=facts,
                    report_builder=builder,
                )
                with self.assertRaises(InspectorError) as raised:
                    service.inspect(InspectionQuery(InspectionTarget(run_id="run_1")))
                self.assertEqual(raised.exception.code, code.value)
                self.assertNotIn("secret", raised.exception.message)

    def test_fact_provider_failure_preserves_trace_with_unavailable_warning(self) -> None:
        service = InspectorService(
            trace_reader=_Reader(),
            fact_provider=_FailingFacts(),
            report_builder=_Builder(),
        )

        result = service.inspect(InspectionQuery(InspectionTarget(run_id="run_1")))

        self.assertEqual(len(result.trace_graphs), 1)
        self.assertIn(
            "fact_provider_unavailable",
            result.runtime_reports[0].integrity_warnings,
        )


class _Reader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def get_trace(self, trace_id: str):
        self.calls.append(("trace", trace_id))
        return _graph(trace_id, "run_1")

    def find_by_run(self, run_id: str):
        self.calls.append(("run", run_id))
        return _graph("trace_1", run_id)

    def find_by_plan(self, plan_id: str):
        self.calls.append(("plan", plan_id))
        return (_graph("trace_preview", "run_preview"), _graph("trace_confirm", "run_confirm"))


class _FailingReader(_Reader):
    def find_by_run(self, run_id: str):
        raise RuntimeError("secret raw trace failure")


class _Facts:
    def __init__(self) -> None:
        self.graphs = []
        self.bundles = []

    def load(self, graph):
        bundle = RuntimeFactBundle()
        self.graphs.append(graph)
        self.bundles.append(bundle)
        return bundle


class _FailingFacts(_Facts):
    def load(self, graph):
        raise RuntimeError("secret database failure")


class _Builder:
    def __init__(self) -> None:
        self.inputs = []

    def build(self, graph, facts):
        self.inputs.append((graph, facts))
        return replace(
            _report(graph.trace.trace_id, graph.trace.run_id),
            integrity_warnings=facts.fact_source_warnings,
        )


class _FailingBuilder(_Builder):
    def build(self, graph, facts):
        raise RuntimeError("secret report failure")


def _report(trace_id: str, run_id: str) -> RuntimeReport:
    return RuntimeReport(
        identity=ReportIdentity(trace_id, run_id, "session_1", "turn_1"),
        route=None,
        intent_decision=None,
        policy_decision=None,
        selected_skills=(),
        context_report=None,
        plan_report=(),
        workflow_report=None,
        executor_invocations=(),
        tool_attempts=(),
        execution_feedback=None,
        recovery_report=None,
        evidence=(),
        final_answer_validation=None,
        stop_point=None,
        diagnostic_annotations=(),
        evaluation_annotations=(),
        integrity_warnings=(),
    )


def _graph(trace_id: str, run_id: str):
    graph = TraceReader(
        FileTraceStore(Path("tests/fixtures/traces/serial_diamond"))
    ).get_trace("trace_diamond")
    return replace(
        graph,
        trace=replace(graph.trace, trace_id=trace_id, run_id=run_id),
    )


if __name__ == "__main__":
    unittest.main()
