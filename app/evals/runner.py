"""Serial isolated Eval suite/case lifecycle with separate evaluator traces."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from app.common.ids import new_id
from app.common.time import utc_now_iso
from app.evals.aggregation import aggregate_case_result, aggregate_eval_report
from app.evals.errors import EvalEnvironmentUnavailableError
from app.evals.contracts import (
    CaseResult,
    CaseStatus,
    EvalGraderRegistry,
    EvalReport,
    EvalRun,
    EvalRunStatus,
    EvaluationSubject,
    GradeResult,
    GradeStatus,
)
from app.evals.models import EvalCase, EvalSuite, require_stable_eval_id
from app.evals.state import EvalStateProbeRegistry, build_state_delta
from app.evals.targets import (
    EvalFactProviderFactory,
    EvalTargetExecutor,
    EvalTargetExecutorFactory,
)
from app.evals.workspace import EvalWorkspace, EvalWorkspaceFactory, EvalWorkspacePaths
from app.observability.file_logs import SessionLogWriter
from app.observability.logger import OptionalLogAppender
from app.observability.telemetry import (
    EndSpanInput,
    RequestTelemetry,
    SpanLinkInput,
    StartSpanInput,
)
from app.observability.trace_models import AnnotationRecord
from app.observability.trace_reader import FileTraceStore, TraceReader
from app.observability.trace_vocabulary import (
    AnnotationKind,
    AnnotationProducer,
    AnnotationStatus,
    LifeOpsSpanKind,
    SpanLinkType,
    TraceSource,
    TraceStatus,
)
from app.runtime_reporting import RuntimeFactBundle, RuntimeReportBuilder
from app.runtime_reporting.annotations import persist_annotations


@dataclass(frozen=True)
class EvalRunOptions:
    keep_failed_workspaces: bool = False
    keep_all_workspaces: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.keep_failed_workspaces, bool) or not isinstance(
            self.keep_all_workspaces, bool
        ):
            raise ValueError("workspace retention options must be bool values.")


class EvalReportSink(Protocol):
    def write(self, report: EvalReport) -> None: ...


class EvalTraceReaderFactory(Protocol):
    def create(self, workspace: EvalWorkspacePaths) -> TraceReader: ...


class EvalEvaluatorLogs(Protocol):
    trace_exporter: object
    annotation_sink: object


class EvalEvaluatorLogFactory(Protocol):
    def create(
        self, workspace: EvalWorkspacePaths, *, session_id: str
    ) -> EvalEvaluatorLogs: ...


class FileEvalTraceReaderFactory:
    def create(self, workspace: EvalWorkspacePaths) -> TraceReader:
        return TraceReader(FileTraceStore(workspace.log_root))


class FileEvalEvaluatorLogFactory:
    def create(
        self, workspace: EvalWorkspacePaths, *, session_id: str
    ) -> SessionLogWriter:
        return SessionLogWriter.create(workspace.log_root, session_id=session_id)


class EvalRunner:
    def __init__(
        self,
        *,
        workspace_factory: EvalWorkspaceFactory,
        target_factory: EvalTargetExecutorFactory,
        fact_provider_factory: EvalFactProviderFactory,
        grader_registry: EvalGraderRegistry,
        state_probe_registry: EvalStateProbeRegistry,
        state_probe_ids: Mapping[str, tuple[str, ...]] | None = None,
        trace_reader_factory: EvalTraceReaderFactory | None = None,
        report_builder: RuntimeReportBuilder | None = None,
        evaluator_log_factory: EvalEvaluatorLogFactory | None = None,
        report_sink: EvalReportSink | None = None,
        environment_fingerprint: str = "offline-local-v1",
        now: Callable[[], str] = utc_now_iso,
        monotonic: Callable[[], float] = time.monotonic,
        id_factory: Callable[[str], str] = new_id,
    ) -> None:
        if not isinstance(workspace_factory, EvalWorkspaceFactory):
            raise ValueError("workspace_factory must be EvalWorkspaceFactory.")
        if not isinstance(target_factory, EvalTargetExecutorFactory):
            raise ValueError("target_factory must be EvalTargetExecutorFactory.")
        if not isinstance(fact_provider_factory, EvalFactProviderFactory):
            raise ValueError("fact_provider_factory must be EvalFactProviderFactory.")
        if not isinstance(grader_registry, EvalGraderRegistry):
            raise ValueError("grader_registry must be EvalGraderRegistry.")
        if not isinstance(state_probe_registry, EvalStateProbeRegistry):
            raise ValueError("state_probe_registry must be EvalStateProbeRegistry.")
        if not isinstance(environment_fingerprint, str) or not environment_fingerprint.strip():
            raise ValueError("environment_fingerprint must be non-empty.")
        self._workspace_factory = workspace_factory
        self._target_factory = target_factory
        self._fact_provider_factory = fact_provider_factory
        self._graders = grader_registry
        self._state_probes = state_probe_registry
        self._probe_ids = _validated_probe_selections(state_probe_ids or {})
        self._trace_readers = trace_reader_factory or FileEvalTraceReaderFactory()
        self._report_builder = report_builder or RuntimeReportBuilder()
        self._evaluator_logs = evaluator_log_factory or FileEvalEvaluatorLogFactory()
        self._report_sink = report_sink
        self._environment_fingerprint = environment_fingerprint
        self._now = now
        self._monotonic = monotonic
        self._id_factory = id_factory
        self.retained_workspaces: dict[str, Path] = {}

    def run(
        self,
        suite: EvalSuite,
        options: EvalRunOptions = EvalRunOptions(),
    ) -> EvalReport:
        if not isinstance(suite, EvalSuite):
            raise ValueError("suite must be EvalSuite.")
        if not isinstance(options, EvalRunOptions):
            raise ValueError("options must be EvalRunOptions.")
        self.retained_workspaces = {}
        run = EvalRun(
            eval_run_id=self._id_factory("eval"),
            suite_id=suite.suite_id,
            suite_version=suite.version,
            environment_fingerprint=self._environment_fingerprint,
            started_at=self._now(),
        )
        results = tuple(
            self._run_case(run, suite, case, options) for case in suite.cases
        )
        report = aggregate_eval_report(
            run,
            results,
            ended_at=self._now(),
        )
        if self._report_sink is not None:
            try:
                self._report_sink.write(report)
            except Exception:
                report = replace(
                    report,
                    run=replace(report.run, status=EvalRunStatus.ERROR),
                    warnings=tuple(
                        dict.fromkeys((*report.warnings, "eval_report_not_persisted"))
                    ),
                )
        return report

    def _run_case(
        self,
        run: EvalRun,
        suite: EvalSuite,
        case: EvalCase,
        options: EvalRunOptions,
    ) -> CaseResult:
        started = self._monotonic()
        workspace: EvalWorkspace | None = None
        target_executor: EvalTargetExecutor | None = None
        warnings: list[str] = []
        result: CaseResult
        try:
            workspace = self._workspace_factory.create(case.case_id)
            probe_ids = self._probe_ids.get(_composition_key(case), ())
            before = self._state_probes.capture(probe_ids, workspace.paths)
            self._deadline(started, case)
            target_executor = self._target_factory.create(case, workspace)
            try:
                target = target_executor.execute()
            except EvalEnvironmentUnavailableError as exc:
                result = self._error_case(
                    run, suite, case, started,
                    GradeStatus.UNAVAILABLE,
                    exc.code,
                    warnings,
                )
                return self._finish_case(
                    case, result, workspace, target_executor, options, warnings
                )
            except Exception:
                result = self._error_case(
                    run, suite, case, started,
                    GradeStatus.ERROR,
                    "eval_target_execution_failed",
                    warnings,
                )
                return self._finish_case(
                    case, result, workspace, target_executor, options, warnings
                )
            self._deadline(started, case)
            reader = self._trace_readers.create(workspace.paths)
            graph = reader.find_by_run(target.run_id)
            fact_provider = self._fact_provider_factory.create(case, workspace, target)
            try:
                facts = fact_provider.load(graph)
            except Exception:
                facts = RuntimeFactBundle(
                    fact_source_warnings=("eval_fact_provider_failed",)
                )
            report = self._report_builder.build(graph, facts)
            after = self._state_probes.capture(probe_ids, workspace.paths)
            state_delta = build_state_delta(before, after) if probe_ids else None
            self._deadline(started, case)
            subject = EvaluationSubject(report, graph, state_delta)
            grades, evaluator_trace_id, annotation_failed = self._evaluate(
                run, suite, case, subject, workspace
            )
            if annotation_failed:
                warnings.append("annotation_not_persisted")
            self._deadline(started, case)
            result = aggregate_case_result(
                case,
                eval_run_id=run.eval_run_id,
                suite_id=suite.suite_id,
                grade_results=grades,
                duration_ms=_duration_ms(started, self._monotonic()),
                target_trace_id=report.identity.trace_id,
                evaluator_trace_id=evaluator_trace_id,
                warnings=tuple(warnings),
            )
        except EvalEnvironmentUnavailableError as exc:
            result = self._error_case(
                run, suite, case, started,
                GradeStatus.UNAVAILABLE,
                exc.code,
                warnings,
            )
        except _EvalDeadlineExceeded:
            result = self._error_case(
                run, suite, case, started, GradeStatus.ERROR, "eval_case_timeout", warnings
            )
        except Exception:
            result = self._error_case(
                run, suite, case, started, GradeStatus.ERROR, "eval_case_lifecycle_failed", warnings
            )
        if workspace is None:
            return result
        return self._finish_case(
            case, result, workspace, target_executor, options, warnings
        )

    def _evaluate(
        self,
        run: EvalRun,
        suite: EvalSuite,
        case: EvalCase,
        subject: EvaluationSubject,
        workspace: EvalWorkspace,
    ) -> tuple[tuple[GradeResult, ...], str, tuple[str, ...]]:
        logs = self._evaluator_logs.create(
            workspace.paths,
            session_id=subject.runtime_report.identity.session_id,
        )
        evaluator_run_id = self._id_factory("eval_case")
        telemetry = RequestTelemetry(
            run_id=evaluator_run_id,
            session_id=subject.runtime_report.identity.session_id,
            turn_id=self._id_factory("eval_turn"),
            legacy_sink=OptionalLogAppender(None),
            exporter=logs.trace_exporter,
            source=TraceSource.EVAL,
        )
        evaluator_trace_id = telemetry.trace_context.trace_id
        case_span = telemetry.start_span(
            StartSpanInput(
                "evaluation.case",
                LifeOpsSpanKind.EVALUATOR,
                {
                    "eval_run_id": run.eval_run_id,
                    "eval_suite_id": suite.suite_id,
                    "eval_case_id": case.case_id,
                },
            )
        )
        telemetry.add_link(
            SpanLinkInput(
                target_trace_id=subject.runtime_report.identity.trace_id,
                target_span_id=subject.trace_graph.root_span.span_id,
                link_type=SpanLinkType.EVALUATION_OF,
            )
        )
        grader_ids = tuple(
            dict.fromkeys((*suite.default_grader_ids, *case.grader_ids))
        )
        grades: list[GradeResult] = []
        for grader_id in grader_ids:
            span = telemetry.start_span(
                StartSpanInput(
                    f"grader.{grader_id}",
                    LifeOpsSpanKind.EVALUATOR,
                    {"eval_grader_id": grader_id},
                )
            )
            try:
                grade = self._graders.get(grader_id).grade(case, subject)
            except Exception:
                grade = _runner_grade(
                    run, suite, case,
                    GradeStatus.ERROR,
                    "eval_grader_failed",
                    grader_id=grader_id,
                    trace_id=subject.runtime_report.identity.trace_id,
                )
            grades.append(grade)
            telemetry.end_span(
                EndSpanInput(
                    span,
                    TraceStatus.OK,
                    attributes={"evaluation.grade.status": grade.status.value},
                )
            )
        annotations = tuple(
            _annotation(
                run,
                suite,
                case,
                grade,
                subject.runtime_report.identity.trace_id,
                self._environment_fingerprint,
                self._now(),
            )
            for grade in grades
        )
        failed_annotations = persist_annotations(logs.annotation_sink, annotations)
        telemetry.end_span(EndSpanInput(case_span, TraceStatus.OK))
        telemetry.finish(status=TraceStatus.OK)
        return tuple(grades), evaluator_trace_id, failed_annotations

    def _error_case(
        self,
        run: EvalRun,
        suite: EvalSuite,
        case: EvalCase,
        started: float,
        status: GradeStatus,
        reason: str,
        warnings: list[str],
    ) -> CaseResult:
        grade = _runner_grade(run, suite, case, status, reason)
        return aggregate_case_result(
            case,
            eval_run_id=run.eval_run_id,
            suite_id=suite.suite_id,
            grade_results=(grade,),
            duration_ms=_duration_ms(started, self._monotonic()),
            warnings=tuple(warnings),
        )

    def _finish_case(
        self,
        case: EvalCase,
        result: CaseResult,
        workspace: EvalWorkspace,
        target_executor: EvalTargetExecutor | None,
        options: EvalRunOptions,
        warnings: list[str],
    ) -> CaseResult:
        if target_executor is not None:
            try:
                target_executor.close()
            except Exception:
                warnings.append("target_close_failed")
        keep = options.keep_all_workspaces or (
            options.keep_failed_workspaces and result.status is not CaseStatus.PASSED
        )
        try:
            workspace.close(keep=keep)
        except Exception:
            warnings.append("workspace_cleanup_failed")
        if keep:
            self.retained_workspaces[case.case_id] = workspace.paths.root
        merged = tuple(dict.fromkeys((*result.warnings, *warnings)))
        return replace(result, warnings=merged) if merged != result.warnings else result

    def _deadline(self, started: float, case: EvalCase) -> None:
        if self._monotonic() - started > case.timeout_seconds:
            raise _EvalDeadlineExceeded


class _EvalDeadlineExceeded(RuntimeError):
    pass


def _runner_grade(
    run: EvalRun,
    suite: EvalSuite,
    case: EvalCase,
    status: GradeStatus,
    reason: str,
    *,
    grader_id: str = "eval-runner",
    trace_id: str | None = None,
) -> GradeResult:
    return GradeResult(
        grade_id=f"{case.case_id}.{grader_id}",
        grader_id=grader_id,
        grader_version="1.0.0",
        status=status,
        reason_code=reason,
        safe_explanation="Eval lifecycle completed with a safe classified failure.",
        target_trace_id=trace_id,
    )


def _annotation(
    run: EvalRun,
    suite: EvalSuite,
    case: EvalCase,
    grade: GradeResult,
    target_trace_id: str,
    fingerprint: str,
    created_at: str,
) -> AnnotationRecord:
    digest = hashlib.sha256(
        "|".join((run.eval_run_id, suite.suite_id, case.case_id, grade.grade_id)).encode(
            "utf-8"
        )
    ).hexdigest()
    status = {
        GradeStatus.PASSED: AnnotationStatus.PASSED,
        GradeStatus.FAILED: AnnotationStatus.FAILED,
        GradeStatus.WARNING: AnnotationStatus.WARNING,
        GradeStatus.SKIPPED: AnnotationStatus.SKIPPED,
        GradeStatus.UNAVAILABLE: AnnotationStatus.SKIPPED,
        GradeStatus.ERROR: AnnotationStatus.ERROR,
    }[grade.status]
    return AnnotationRecord(
        annotation_id=f"annotation_{digest}",
        target_trace_id=grade.target_trace_id or target_trace_id,
        target_span_id=grade.target_span_id,
        annotation_kind=AnnotationKind.EVALUATION,
        producer=AnnotationProducer.DETERMINISTIC_RULE,
        status=status,
        evaluator_id=grade.grader_id,
        producer_version=grade.grader_version,
        source_fingerprint=fingerprint,
        eval_run_id=run.eval_run_id,
        eval_suite_id=suite.suite_id,
        eval_case_id=case.case_id,
        score=grade.score,
        label=("unavailable" if grade.status is GradeStatus.UNAVAILABLE else grade.label),
        reason_code=grade.reason_code,
        safe_explanation=grade.safe_explanation,
        created_at=created_at,
    )


def _validated_probe_selections(
    selections: Mapping[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    if not isinstance(selections, Mapping):
        raise ValueError("state_probe_ids must be a mapping.")
    result = dict(selections)
    for key, probe_ids in result.items():
        require_stable_eval_id(key, "composition key")
        if not isinstance(probe_ids, tuple) or len(set(probe_ids)) != len(probe_ids):
            raise ValueError("probe selections must be unique tuples.")
        for probe_id in probe_ids:
            require_stable_eval_id(probe_id, "probe_id")
    return result


def _composition_key(case: EvalCase) -> str:
    return case.fixture_ref or case.execution_mode.value


def _duration_ms(started: float, ended: float) -> int:
    return max(0, round((ended - started) * 1000))
