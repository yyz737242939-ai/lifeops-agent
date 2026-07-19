from __future__ import annotations

import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from app.evals import (
    EVAL_MANIFEST_SCHEMA_VERSION,
    CaseStatus,
    EvalCase,
    EvalExecutionMode,
    EvalExpectations,
    EvalFactProviderFactory,
    EvalRunOptions,
    EvalRunner,
    EvalStateProbeRegistry,
    EvalSuite,
    EvalTargetExecutorFactory,
    EvalTargetResult,
    EvalWorkspaceFactory,
    RuntimeRequestTargetExecutor,
    default_grader_registry,
)
from app.executor.models import FinalAnswerDecision
from app.executor.service import ReactExecutor
from app.inspection import (
    InspectionQuery,
    InspectionTarget,
    InspectionView,
    build_inspector_service,
)
from app.observability.file_logs import SessionLogWriter
from app.observability.trace_reader import FileTraceStore, TraceReader
from app.observability.trace_vocabulary import SpanLinkType, TraceSource
from app.runtime.models import RuntimeRequest
from app.runtime.service import RuntimeService
from app.runtime_reporting import EmptyRuntimeFactProvider, RuntimeReportBuilder
from tests.helpers import create_test_skill_service


class EvalRunnerLifecycleTest(unittest.TestCase):
    def test_suite_builds_one_report_and_separate_evaluator_trace_annotations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            report_builder = _CountingReportBuilder()
            runner = _runner(base, report_builder=report_builder)

            report = runner.run(_suite(), EvalRunOptions(keep_all_workspaces=True))

            self.assertEqual(report.case_results[0].status, CaseStatus.PASSED)
            self.assertEqual(report_builder.calls, 1)
            self.assertEqual(report.run.status.value, "passed")
            root = runner.retained_workspaces["runtime-final"]
            reader = TraceReader(FileTraceStore(root / "logs" / "sessions"))
            target = reader.find_by_run("run-runtime-final")
            evaluator = reader.get_trace(report.case_results[0].evaluator_trace_id)

            self.assertNotEqual(target.trace.trace_id, evaluator.trace.trace_id)
            self.assertEqual(evaluator.trace.source, TraceSource.EVAL)
            self.assertTrue(
                any(
                    link.link_type is SpanLinkType.EVALUATION_OF
                    and link.target_trace_id == target.trace.trace_id
                    for link in evaluator.links
                )
            )
            self.assertFalse(
                any(
                    str(key).startswith("eval_")
                    for span in target.spans_by_id.values()
                    for key in span.attributes
                )
            )
            refreshed = reader.get_trace(target.trace.trace_id)
            self.assertEqual(len(refreshed.annotations), 3)
            self.assertTrue(all(item.eval_case_id == "runtime-final" for item in refreshed.annotations))
            inspection = build_inspector_service(root / "logs" / "sessions").inspect(
                InspectionQuery(
                    InspectionTarget(run_id="run-runtime-final"),
                    views=(InspectionView.ANNOTATIONS,),
                )
            )
            self.assertEqual(
                len(inspection.runtime_reports[0].evaluation_annotations), 3
            )
            shutil.rmtree(root)

    def test_annotation_sink_failure_warns_without_changing_immediate_grade(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _runner(
                Path(tmpdir), evaluator_log_factory=_FailingAnnotationLogFactory()
            )

            report = runner.run(_suite(), EvalRunOptions(keep_all_workspaces=True))

            case = report.case_results[0]
            self.assertEqual(case.status, CaseStatus.PASSED)
            self.assertEqual(case.warnings, ("annotation_not_persisted",))
            shutil.rmtree(runner.retained_workspaces["runtime-final"])

    def test_phase_deadline_closes_target_and_cleans_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            target_builder = _DeadlineTargetBuilder()
            runner = EvalRunner(
                workspace_factory=EvalWorkspaceFactory(base),
                target_factory=EvalTargetExecutorFactory(
                    {"runtime_request": target_builder}
                ),
                fact_provider_factory=EvalFactProviderFactory(
                    {"runtime_request": _EmptyFactBuilder()}
                ),
                grader_registry=default_grader_registry(),
                state_probe_registry=EvalStateProbeRegistry(()),
                monotonic=_SequenceClock((0.0, 0.0, 2.0, 2.0)),
                now=lambda: "2026-07-19T01:00:00+00:00",
                id_factory=_ids,
            )
            case = _case(timeout_seconds=1.0)

            report = runner.run(
                EvalSuite(1, "runtime-core", "1.0.0", "suite", (case,))
            )

            self.assertEqual(report.case_results[0].status, CaseStatus.ERROR)
            self.assertEqual(
                report.case_results[0].grade_results[0].reason_code,
                "eval_case_timeout",
            )
            self.assertTrue(target_builder.executor.closed)
            self.assertEqual(list(base.iterdir()), [])

    def test_report_sink_failure_returns_in_memory_harness_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _runner(Path(tmpdir), report_sink=_FailingReportSink())
            report = runner.run(_suite())
            self.assertEqual(report.run.status.value, "error")
            self.assertEqual(report.warnings, ("eval_report_not_persisted",))

    def test_target_exception_is_harness_error_and_still_closes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            builder = _FailingTargetBuilder()
            runner = _runner(
                base,
                target_factory=EvalTargetExecutorFactory(
                    {"runtime_request": builder}
                ),
            )

            report = runner.run(_suite())

            case = report.case_results[0]
            self.assertEqual(case.status, CaseStatus.ERROR)
            self.assertEqual(
                case.grade_results[0].reason_code,
                "eval_target_execution_failed",
            )
            self.assertTrue(builder.executor.closed)
            self.assertEqual(list(base.iterdir()), [])

    def test_reader_failure_is_classified_and_still_cleans_the_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            report = _runner(
                base,
                trace_reader_factory=_FailingTraceReaderFactory(),
            ).run(_suite())

            self.assertEqual(report.case_results[0].status, CaseStatus.ERROR)
            self.assertEqual(
                report.case_results[0].grade_results[0].reason_code,
                "eval_case_lifecycle_failed",
            )
            self.assertEqual(list(base.iterdir()), [])

    def test_fact_provider_failure_keeps_trace_grading_and_degrades_fact_grade(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base_case = _case()
            case = replace(
                base_case,
                expectations=EvalExpectations(
                    execution_feedback={"equals": "completed"},
                    trace_contract={"status": "ok"},
                ),
                grader_ids=("execution-feedback",),
            )
            suite = EvalSuite(
                EVAL_MANIFEST_SCHEMA_VERSION,
                "runtime-core",
                "1.0.0",
                "Fact degradation suite.",
                (case,),
                default_grader_ids=("trace-contract",),
            )
            runner = _runner(
                Path(tmpdir),
                fact_provider_factory=EvalFactProviderFactory(
                    {"runtime_request": _FailingFactBuilder()}
                ),
            )

            report = runner.run(suite)

            grades = {item.grader_id: item for item in report.case_results[0].grade_results}
            self.assertEqual(grades["trace-contract"].status.value, "passed")
            self.assertEqual(grades["execution-feedback"].status.value, "unavailable")
            self.assertEqual(report.case_results[0].status, CaseStatus.ERROR)


def _runner(base: Path, **overrides) -> EvalRunner:
    arguments = {
        "workspace_factory": EvalWorkspaceFactory(base),
        "target_factory": EvalTargetExecutorFactory(
            {"runtime_request": _RuntimeTargetBuilder()}
        ),
        "fact_provider_factory": EvalFactProviderFactory(
            {"runtime_request": _EmptyFactBuilder()}
        ),
        "grader_registry": default_grader_registry(),
        "state_probe_registry": EvalStateProbeRegistry(()),
        "environment_fingerprint": "offline-runner-v1",
        "now": lambda: "2026-07-19T01:00:00+00:00",
        "id_factory": _ids,
    }
    arguments.update(overrides)
    return EvalRunner(**arguments)


class _RuntimeTargetBuilder:
    def build(self, case, workspace):
        service = RuntimeService(
            create_test_skill_service(),
            log_root=workspace.paths.log_root,
            executor=ReactExecutor(
                _FinalAnswerModel()
            ),
        )
        request = RuntimeRequest(
            "把明天跑步加入任务",
            "session-runtime-final",
            turn_id="turn-runtime-final",
            run_id="run-runtime-final",
        )
        return RuntimeRequestTargetExecutor(service, request)


class _EmptyFactBuilder:
    def build(self, case, workspace, target):
        return EmptyRuntimeFactProvider()


class _FailingFactBuilder:
    def build(self, case, workspace, target):
        return _FailingFactProvider()


class _FailingFactProvider:
    def load(self, graph):
        raise RuntimeError("private fact provider failure")


class _FailingTraceReaderFactory:
    def create(self, workspace):
        return _FailingTraceReader()


class _FailingTraceReader:
    def find_by_run(self, run_id):
        raise RuntimeError("private trace reader failure")


class _FinalAnswerModel:
    def decide(self, model_input, *, llm_log=None):
        return FinalAnswerDecision("fixture final")


class _CountingReportBuilder(RuntimeReportBuilder):
    def __init__(self) -> None:
        self.calls = 0

    def build(self, trace, facts):
        self.calls += 1
        return super().build(trace, facts)


class _FailingSink:
    def record(self, annotation):
        raise OSError("fixture sink failure")


class _LogWrapper:
    def __init__(self, logs):
        self.trace_exporter = logs.trace_exporter
        self.annotation_sink = _FailingSink()


class _FailingAnnotationLogFactory:
    def create(self, workspace, *, session_id):
        return _LogWrapper(
            SessionLogWriter.create(workspace.log_root, session_id=session_id)
        )


class _FailingReportSink:
    def write(self, report):
        raise OSError("fixture report failure")


class _DeadlineTargetBuilder:
    def __init__(self) -> None:
        self.executor = _DeadlineExecutor()

    def build(self, case, workspace):
        return self.executor


class _DeadlineExecutor:
    execution_mode = EvalExecutionMode.RUNTIME_REQUEST

    def __init__(self) -> None:
        self.closed = False

    def execute(self):
        return EvalTargetResult(
            self.execution_mode,
            "run-deadline",
            "session-deadline",
            "turn-deadline",
            ("run-deadline",),
        )

    def close(self):
        self.closed = True


class _FailingTargetBuilder:
    def __init__(self) -> None:
        self.executor = _FailingTargetExecutor()

    def build(self, case, workspace):
        return self.executor


class _FailingTargetExecutor:
    execution_mode = EvalExecutionMode.RUNTIME_REQUEST

    def __init__(self) -> None:
        self.closed = False

    def execute(self):
        raise RuntimeError("fixture target failure")

    def close(self):
        self.closed = True


class _SequenceClock:
    def __init__(self, values):
        self._values = iter(values)

    def __call__(self):
        return next(self._values)


def _suite() -> EvalSuite:
    case = _case()
    return EvalSuite(
        EVAL_MANIFEST_SCHEMA_VERSION,
        "runtime-core",
        "1.0.0",
        "Runner suite.",
        (case,),
        default_grader_ids=("trace-contract", "privacy"),
    )


def _case(*, timeout_seconds: float = 30.0) -> EvalCase:
    return EvalCase(
        EVAL_MANIFEST_SCHEMA_VERSION,
        "runtime-final",
        "Runtime final",
        "Normal public Runtime request.",
        EvalExecutionMode.RUNTIME_REQUEST,
        {"message": "fixture"},
        EvalExpectations(
            execution_path={"equals": "final_only"},
            trace_contract={"status": "ok", "forbidden_spans": ["EVALUATOR"]},
            privacy={"forbidden_fields": ["api_key", "raw_prompt"]},
        ),
        ("execution-path",),
        timeout_seconds=timeout_seconds,
    )


def _ids(prefix: str) -> str:
    return {
        "eval": "eval-1",
        "eval_case": "eval-case-1",
        "eval_turn": "eval-turn-1",
    }[prefix]


if __name__ == "__main__":
    unittest.main()
