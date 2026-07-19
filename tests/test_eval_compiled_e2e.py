from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from app.evals import (
    CaseStatus,
    EvalGraderRegistry,
    EvalRunOptions,
    EvalStateSnapshot,
    EvaluationSubject,
    FileEvalSuiteLoader,
    TraceContractGrader,
    build_state_delta,
    default_grader_registry,
)
from app.evals.compiled import FIXTURE_REFS, build_compiled_eval_runner
from app.observability.trace_index import TraceIndexBuilder
from app.observability.trace_reader import FileTraceStore, TraceReader
from app.recovery.reporting import ExecutionFeedbackFactSource
from app.recovery.repository import SqliteExecutionFeedbackRepository
from app.runtime_reporting import RuntimeReportBuilder
from app.storage.sqlite import connect_sqlite
from tests.test_eval_runner import (
    _FailingAnnotationLogFactory,
    _FailingReportSink,
    _FailingTraceReaderFactory,
    _runner,
    _suite,
)


class EvalCompiledE2ETest(unittest.TestCase):
    def test_01_direct_final_only(self) -> None:
        case = _run_case("direct-final-only")
        self.assertEqual(case.status, CaseStatus.PASSED)
        self.assertEqual(_grade(case, "execution-path").reason_code, "execution-path_passed")
        self.assertEqual(_grade(case, "tool-call").safe_actual["identities"], ())

    def test_02_direct_read_has_evidence_and_grounding(self) -> None:
        case = _run_case("direct-read-success")
        self.assertEqual(case.status, CaseStatus.PASSED)
        self.assertGreaterEqual(_grade(case, "evidence").safe_actual["count"], 1)
        self.assertEqual(
            _grade(case, "final-answer-grounding").safe_actual["equals"], "valid"
        )

    def test_03_direct_write_changes_once_after_exact_confirmation(self) -> None:
        case = _run_case("direct-write-confirmed")
        self.assertEqual(case.status, CaseStatus.PASSED)
        state = _grade(case, "state-change")
        self.assertEqual(state.safe_actual["count"], 1)
        self.assertEqual(
            state.safe_actual["changes"]["fixture-state.write_count"]["before"], 0
        )
        self.assertEqual(
            state.safe_actual["changes"]["fixture-state.write_count"]["after"], 1
        )

    def test_04_tool_failure_false_success_is_located(self) -> None:
        case = _run_case("direct-failure-false-success")
        self.assertEqual(case.status, CaseStatus.PASSED)
        self.assertEqual(_grade(case, "execution-feedback").safe_actual["equals"], "failed")
        self.assertEqual(
            _grade(case, "final-answer-grounding").safe_actual["equals"], "invalid"
        )

    def test_05_planning_preview_confirm_is_cross_trace(self) -> None:
        case = _run_case("planning-confirm")
        self.assertEqual(case.status, CaseStatus.PASSED)
        trace_grade = _grade(case, "trace-contract")
        self.assertIn("plan_continuation", trace_grade.safe_actual["required_links"])
        self.assertEqual(_grade(case, "plan-lifecycle").status.value, "passed")

    def test_06_planning_partial_distinguishes_all_step_outcomes(self) -> None:
        case = _run_case("planning-partial")
        self.assertEqual(case.status, CaseStatus.PASSED)
        statuses = _grade(case, "plan-lifecycle").safe_actual["status_by_id"]
        self.assertEqual(
            {key: statuses[key] for key in ("step-1", "step-2", "step-3")},
            {
                "step-1": "completed",
                "step-2": "goal_not_achieved",
                "step-3": "pending",
            },
        )

    def test_07_recovery_explain_has_zero_execution_authority_spans(self) -> None:
        case = _run_case("recovery-restart")
        self.assertEqual(case.status, CaseStatus.PASSED)
        trace = _grade(case, "trace-contract")
        self.assertEqual(trace.safe_actual["status"], "ok")
        self.assertNotIn("POLICY", trace.safe_actual["forbidden_spans"])
        self.assertNotIn("EXECUTOR", trace.safe_actual["forbidden_spans"])
        self.assertNotIn("TOOL", trace.safe_actual["forbidden_spans"])

    def test_08_serial_diamond_uses_links_and_outcomes(self) -> None:
        case = _run_case("serial-diamond")
        self.assertEqual(case.status, CaseStatus.PASSED)
        workflow = _grade(case, "workflow-dependency").safe_actual
        self.assertEqual(workflow["linked_to"]["D"], ("B", "C"))
        self.assertEqual(workflow["status_by_id"]["D"], "blocked")

    def test_09_regression_keeps_stable_reason(self) -> None:
        case = _run_case("regression-false-success", suite_ref="regression")
        self.assertEqual(case.status, CaseStatus.PASSED)
        self.assertEqual(
            _grade(case, "final-answer-grounding").reason_code,
            "final-answer-grounding_passed",
        )

    def test_10_restart_and_index_rebuild_keep_grades_stable(self) -> None:
        loader = _loader()
        suite = loader.load("runtime_core")
        case = next(item for item in suite.cases if item.case_id == "direct-read-success")
        suite = replace(suite, cases=(case,))
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = build_compiled_eval_runner(workspace_root=Path(tmpdir))
            first = runner.run(suite, EvalRunOptions(keep_all_workspaces=True))
            root = runner.retained_workspaces[case.case_id]
            log_root = root / "logs" / "sessions"
            index_path = root / "index" / "traces.sqlite3"
            TraceIndexBuilder(index_path).index_session(
                log_root / "session-direct-read-success"
            )
            graph = TraceReader(
                FileTraceStore(log_root, index_path=index_path)
            ).get_trace(first.case_results[0].target_trace_id)
            conn = connect_sqlite(root / "data" / "lifeops.sqlite3")
            try:
                facts = ExecutionFeedbackFactSource(
                    SqliteExecutionFeedbackRepository(conn)
                ).load(graph)
                runtime_report = RuntimeReportBuilder().build(graph, facts)
                snapshot = EvalStateSnapshot("fixture-state", {"write_count": 0})
                subject = EvaluationSubject(
                    runtime_report,
                    graph,
                    build_state_delta((snapshot,), (snapshot,)),
                )
                registry = default_grader_registry()
                rebuilt = tuple(
                    registry.get(grader_id).grade(case, subject)
                    for grader_id in case.grader_ids
                )
            finally:
                conn.close()

        self.assertEqual(
            tuple((item.grader_id, item.status, item.reason_code) for item in rebuilt),
            tuple(
                (item.grader_id, item.status, item.reason_code)
                for item in first.case_results[0].grade_results
            ),
        )

    def test_11_trace_annotation_report_and_grader_failures_are_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            annotation = _runner(
                Path(tmpdir) / "annotations",
                evaluator_log_factory=_FailingAnnotationLogFactory(),
            ).run(_suite())
            report_sink = _runner(
                Path(tmpdir) / "reports", report_sink=_FailingReportSink()
            ).run(_suite())
            reader = _runner(
                Path(tmpdir) / "reader",
                trace_reader_factory=_FailingTraceReaderFactory(),
            ).run(_suite())
            suite = _suite()
            exploding_case = replace(
                suite.cases[0], grader_ids=("exploding-grader",)
            )
            exploding_suite = replace(
                suite,
                cases=(exploding_case,),
                default_grader_ids=("trace-contract",),
            )
            grader = _runner(
                Path(tmpdir) / "grader",
                grader_registry=EvalGraderRegistry(
                    (TraceContractGrader(), _ExplodingGrader())
                ),
            ).run(exploding_suite)

        self.assertEqual(annotation.case_results[0].status, CaseStatus.PASSED)
        self.assertIn("annotation_not_persisted", annotation.case_results[0].warnings)
        self.assertEqual(report_sink.run.status.value, "error")
        self.assertEqual(reader.case_results[0].status, CaseStatus.ERROR)
        grader_results = {item.grader_id: item for item in grader.case_results[0].grade_results}
        self.assertEqual(grader_results["trace-contract"].status.value, "passed")
        self.assertEqual(grader_results["exploding-grader"].status.value, "error")

    def test_cross_case_workspaces_sessions_and_state_do_not_leak(self) -> None:
        loader = _loader()
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            runner = build_compiled_eval_runner(workspace_root=base)
            runtime_report = runner.run(
                loader.load("runtime_core"),
                EvalRunOptions(keep_all_workspaces=True),
            )
            roots = dict(runner.retained_workspaces)
            regression_report = runner.run(
                loader.load("regression"),
                EvalRunOptions(keep_all_workspaces=True),
            )
            roots.update(runner.retained_workspaces)

            self.assertEqual(len(roots), 11)
            self.assertEqual(len(set(roots.values())), 11)
            trace_ids = tuple(
                item.target_trace_id
                for item in (*runtime_report.case_results, *regression_report.case_results)
            )
            self.assertEqual(len(set(trace_ids)), 11)
            markers = {
                case_id: (
                    "session_diamond"
                    if case_id == "serial-diamond"
                    else f"session-{case_id}"
                )
                for case_id in roots
            }
            for case_id, root in roots.items():
                payload = b"".join(
                    path.read_bytes() for path in root.rglob("*") if path.is_file()
                )
                for other_id, marker in markers.items():
                    if other_id != case_id:
                        self.assertNotIn(marker.encode("utf-8"), payload)
                state_path = root / "data" / "fixture_state.json"
                count = (
                    json.loads(state_path.read_text(encoding="utf-8"))["write_count"]
                    if state_path.is_file()
                    else 0
                )
                self.assertEqual(count, 1 if case_id == "direct-write-confirmed" else 0)


class _ExplodingGrader:
    grader_id = "exploding-grader"
    version = "1.0.0"

    def grade(self, case, subject):
        raise RuntimeError("private grader failure")


def _run_case(case_id: str, *, suite_ref: str = "runtime_core"):
    suite = _loader().load(suite_ref)
    case = next(item for item in suite.cases if item.case_id == case_id)
    with tempfile.TemporaryDirectory() as tmpdir:
        report = build_compiled_eval_runner(
            workspace_root=Path(tmpdir)
        ).run(replace(suite, cases=(case,)))
    return report.case_results[0]


def _grade(case, grader_id: str):
    return next(item for item in case.grade_results if item.grader_id == grader_id)


def _loader() -> FileEvalSuiteLoader:
    return FileEvalSuiteLoader(
        Path("evals/manifests"),
        trusted_fixture_refs=FIXTURE_REFS,
        trusted_grader_ids=default_grader_registry().grader_ids,
    )


if __name__ == "__main__":
    unittest.main()
