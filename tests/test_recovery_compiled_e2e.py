from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.executor.models import (
    FinalAnswerActionClaim,
    FinalAnswerDecision,
    GoalNotAchievedDecision,
    ToolActionDecision,
)
from app.executor.service import ReactExecutor
from app.intent.models import IntentDecision, IntentType
from app.observability.logger import OptionalLogAppender
from app.observability.telemetry import RequestTelemetry
from app.observability.trace_reader import FileTraceStore, TraceReader
from app.observability.trace_vocabulary import LifeOpsSpanKind
from app.planning.controller import PlanController
from app.planning.finalizer import FakePlanFinalizerClient
from app.planning.models import (
    PlanCommand,
    PlanCommandAction,
    PlanDraft,
    PlanFinalizerOutput,
    PlanRoute,
    PlanStepDraft,
    PlanningLimits,
)
from app.planning.planner import FakePlannerModelClient
from app.planning.repository import SqlitePlanRepository
from app.planning.router import FakePlanningRouteClient
from app.planning.service import PlanningService
from app.policy.models import PolicyAction, PolicyDecision
from app.recovery.collector import RequestExecutionFeedbackCollector
from app.recovery.errors import (
    ExecutionFeedbackCollectionError,
    ExecutionFeedbackRepositoryError,
)
from app.recovery.finalizer import RuntimeOutcomeFinalizer, SAFE_UNAVAILABLE_MESSAGE
from app.recovery.models import (
    AnswerOutputMode,
    ClaimStatus,
    ExecutionOutcome,
    FeedbackOverallStatus,
    PlanStepOutcome,
)
from app.recovery.reporting import (
    ExecutionFeedbackFactSource,
    RecoveryResultFactSource,
)
from app.recovery.repository import SqliteExecutionFeedbackRepository
from app.recovery.runtime import RecoveryRuntime
from app.runtime.models import RuntimeRequest
from app.runtime.service import RuntimeService
from app.runtime_reporting.builder import RuntimeReportBuilder
from app.storage.migrations import migrate
from app.storage.sqlite import connect_sqlite
from app.tools.models import (
    ExecutionEvidence,
    ToolCall,
    ToolCallStatus,
    ToolDefinition,
    ToolEffect,
    ToolError,
    ToolResult,
    ToolRisk,
)
from app.tools.registry import ToolRegistry
from app.tools.runtime import ToolRuntime
from tests.helpers import create_test_skill_service


class RecoveryCompiledE2ETest(unittest.TestCase):
    def test_01_direct_success_evidence_validates_and_recovers_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            decisions = (
                _action("call_1"),
                _answer("Source read.", "claim_1", "call_1", "fixture/ref_call_1"),
            )
            service, repository, counters = _direct_service(root, decisions)
            result = service.handle(_request("run_success"))
            feedback = repository.get_for_run("session_1", "run_success")
            service.close()

            recovery = _recovery(root)
            try:
                recovered = recovery.explain("session_1", "run_success")
            finally:
                recovery.close()

        self.assertEqual(result.message, "Source read.")
        self.assertEqual(feedback.overall_status, FeedbackOverallStatus.COMPLETED)
        self.assertEqual(feedback.validation.claim_status, ClaimStatus.VALID)
        self.assertEqual(len(feedback.actions[0].evidence), 1)
        self.assertIn("call_1", recovered.explanation)
        self.assertEqual(counters["tool"], 1)

    def test_02_direct_failure_false_success_uses_fallback_and_recovers_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            decisions = (
                _action("call_1"),
                _answer("False success.", "claim_1", "call_1"),
            )
            service, repository, _ = _direct_service(
                root, decisions, failed_calls={"call_1"}
            )
            result = service.handle(_request("run_failed"))
            feedback = repository.get_for_run("session_1", "run_failed")
            service.close()
            recovery = _recovery(root)
            try:
                recovered = recovery.explain("session_1", "run_failed")
            finally:
                recovery.close()

        self.assertNotEqual(result.message, "False success.")
        self.assertEqual(feedback.overall_status, FeedbackOverallStatus.FAILED)
        self.assertEqual(feedback.validation.claim_status, ClaimStatus.INVALID)
        self.assertEqual(
            feedback.validation.output_mode,
            AnswerOutputMode.DETERMINISTIC_FALLBACK,
        )
        self.assertIn("call_1, failed", recovered.explanation)

    def test_03_direct_first_success_later_failure_remains_partial(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            decisions = (
                _action("call_1"),
                _action("call_2"),
                _answer("Partial.", "claim_1", "call_1", "fixture/ref_call_1"),
            )
            service, repository, _ = _direct_service(
                root, decisions, failed_calls={"call_2"}
            )
            service.handle(_request("run_partial"))
            feedback = repository.get_for_run("session_1", "run_partial")
            service.close()

        self.assertEqual(feedback.overall_status, FeedbackOverallStatus.PARTIAL)
        self.assertEqual(
            tuple(item.outcome for item in feedback.actions),
            (ExecutionOutcome.SUCCEEDED, ExecutionOutcome.FAILED),
        )
        self.assertEqual(feedback.validation.claim_status, ClaimStatus.VALID)

    def test_04_planning_fully_completed_has_one_run_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            service, repository, _ = _planning_service(
                root,
                step_count=2,
                decisions=(FinalAnswerDecision("step 1"), FinalAnswerDecision("step 2")),
            )
            preview = service.handle(_request("run_preview"))
            result = service.handle_plan_command(
                _confirm(preview), _request("run_plan_completed")
            )
            feedback = repository.get_for_run("session_1", "run_plan_completed")
            count = service._conn.execute(
                "SELECT COUNT(*) AS count FROM execution_feedback WHERE run_id = ?",
                ("run_plan_completed",),
            ).fetchone()["count"]
            service.close()

        self.assertEqual(result.message, "plan complete")
        self.assertEqual(count, 1)
        self.assertEqual(feedback.overall_status, FeedbackOverallStatus.COMPLETED)
        self.assertTrue(
            all(step.outcome is PlanStepOutcome.COMPLETED for step in feedback.plan_steps)
        )

    def test_05_planning_partial_distinguishes_completed_failed_and_not_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            service, repository, _ = _planning_service(
                root,
                step_count=3,
                decisions=(
                    FinalAnswerDecision("step 1"),
                    GoalNotAchievedDecision("fixture_step_failed"),
                ),
            )
            preview = service.handle(_request("run_preview"))
            service.handle_plan_command(_confirm(preview), _request("run_plan_partial"))
            feedback = repository.get_for_run("session_1", "run_plan_partial")
            service.close()

        self.assertEqual(feedback.overall_status, FeedbackOverallStatus.PARTIAL)
        self.assertEqual(
            tuple(step.outcome for step in feedback.plan_steps),
            (
                PlanStepOutcome.COMPLETED,
                PlanStepOutcome.FAILED,
                PlanStepOutcome.NOT_RUN,
            ),
        )

    def test_06_restart_recovery_is_read_only_and_has_zero_execution_spans(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            service, repository, counters = _planning_service(
                root,
                step_count=3,
                decisions=(
                    FinalAnswerDecision("step 1"),
                    GoalNotAchievedDecision("fixture_step_failed"),
                ),
            )
            preview = service.handle(_request("run_preview"))
            service.handle_plan_command(_confirm(preview), _request("run_source"))
            before = repository.get_for_run("session_1", "run_source")
            service.close()
            source_counters = dict(counters)

            recovery = _recovery(root)
            try:
                recovered = recovery.explain("session_1", "run_source")
                after = SqliteExecutionFeedbackRepository(recovery._conn).get_for_run(
                    "session_1", "run_source"
                )
            finally:
                recovery.close()
            graph = _latest_recovery_graph(root)
            recovery_report = RuntimeReportBuilder().build(
                graph, RecoveryResultFactSource(recovered).load(graph)
            )

        self.assertEqual(before, after)
        self.assertEqual(counters, source_counters)
        self.assertEqual(before.overall_status, FeedbackOverallStatus.PARTIAL)
        kinds = {span.lifeops_span_kind for span in graph.spans_by_id.values()}
        self.assertEqual(kinds, {LifeOpsSpanKind.RUNTIME, LifeOpsSpanKind.RECOVERY})
        self.assertIsNotNone(recovery_report.recovery_report)
        self.assertEqual(recovery_report.integrity_warnings, ())

    def test_07_repository_failure_preserves_result_and_restart_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            service, _, _ = _direct_service(
                root,
                (FinalAnswerDecision("No execution success claimed."),),
                feedback_repository=_FailingRepository(),
            )
            result = service.handle(_request("run_no_feedback"))
            service.close()
            recovery = _recovery(root)
            try:
                with self.assertRaises(ExecutionFeedbackRepositoryError) as caught:
                    recovery.explain("session_1", "run_no_feedback")
            finally:
                recovery.close()

        self.assertEqual(result.message, "No execution success claimed.")
        self.assertEqual(caught.exception.code, "recovery_source_unavailable")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            service, _, _ = _direct_service(
                root,
                (FinalAnswerDecision("Unverified draft."),),
                feedback_collector=_FailingCollector(),
            )
            degraded = service.handle(_request("run_collector_failure"))
            service.close()
            recovery = _recovery(root)
            try:
                with self.assertRaises(ExecutionFeedbackRepositoryError):
                    recovery.explain("session_1", "run_collector_failure")
            finally:
                recovery.close()
        self.assertEqual(degraded.message, SAFE_UNAVAILABLE_MESSAGE)

    def test_08_cross_session_lookup_fails_closed_without_tool_or_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            service, _, counters = _direct_service(
                root, (_action("call_1"), FinalAnswerDecision("done"))
            )
            service.handle(_request("run_source"))
            service.close()
            before = dict(counters)
            recovery = _recovery(root)
            try:
                with self.assertRaises(ExecutionFeedbackRepositoryError) as caught:
                    recovery.explain("session_other", "run_source")
            finally:
                recovery.close()

        self.assertEqual(caught.exception.code, "recovery_source_unavailable")
        self.assertEqual(counters, before)
        self.assertNotIn("confirmation", RecoveryRuntime.explain.__annotations__)

    def test_09_trace_exporter_failure_does_not_change_feedback_or_safe_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            service, repository, _ = _direct_service(
                root,
                (
                    _action("call_1"),
                    _answer(
                        "safe result",
                        "claim_1",
                        "call_1",
                        "fixture/ref_call_1",
                    ),
                ),
                service_type=_ExporterFailingRuntime,
            )
            result = service.handle(_request("run_export_failure"))
            feedback = repository.get_for_run("session_1", "run_export_failure")
            service.close()

        self.assertEqual(result.message, "safe result")
        self.assertEqual(feedback.overall_status, FeedbackOverallStatus.COMPLETED)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            service, repository, _ = _direct_service(
                root, (FinalAnswerDecision("safe indexed result"),)
            )
            service.handle(_request("run_index_failure"))
            broken_index = root / "broken-index.sqlite3"
            broken_index.write_text("not sqlite", encoding="utf-8")
            graph = TraceReader(
                FileTraceStore(root / "logs", index_path=broken_index)
            ).find_by_run("run_index_failure")
            feedback = repository.get_for_run("session_1", "run_index_failure")
            service.close()
        self.assertEqual(graph.trace.run_id, feedback.run_id)
        self.assertEqual(feedback.overall_status, FeedbackOverallStatus.COMPLETED)

    def test_10_runtime_report_reads_feedback_through_typed_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            service, repository, _ = _direct_service(
                root, (_action("call_1"), FinalAnswerDecision("done"))
            )
            service.handle(_request("run_report"))
            graph = TraceReader(FileTraceStore(root / "logs")).find_by_run("run_report")
            facts = ExecutionFeedbackFactSource(repository).load(graph)
            report = RuntimeReportBuilder().build(graph, facts)
            service.close()

        self.assertIsNotNone(report.execution_feedback)
        self.assertEqual(report.execution_feedback.source_kind, "execution_feedback")
        self.assertEqual(report.execution_feedback.status, "completed")
        self.assertIsNotNone(report.final_answer_validation)
        self.assertIsNotNone(report.stop_point)
        self.assertEqual(len(report.evidence), 1)
        self.assertEqual(report.integrity_warnings, ())


def _direct_service(
    root: Path,
    decisions,
    *,
    failed_calls: set[str] | None = None,
    feedback_repository=None,
    feedback_collector=None,
    service_type=RuntimeService,
):
    conn = connect_sqlite(root / "lifeops.db")
    migrate(conn)
    collector = feedback_collector or RequestExecutionFeedbackCollector()
    repository = feedback_repository or SqliteExecutionFeedbackRepository(conn)
    counters = {"tool": 0, "policy": 0, "confirmation": 0, "controller": 0}
    executor = ReactExecutor(
        _ScriptedModel(decisions),
        feedback_sink=collector,
    )
    service = service_type(
        create_test_skill_service(),
        intent_service=_Intent(IntentType.READ),
        policy_service=_Policy(counters),
        conn=conn,
        log_root=root / "logs",
        execution_scope_factory=lambda: _tool_runtime(counters, failed_calls or set()),
        executor=executor,
        outcome_finalizer=RuntimeOutcomeFinalizer(collector, repository),
    )
    return service, repository, counters


def _planning_service(root: Path, *, step_count: int, decisions):
    conn = connect_sqlite(root / "lifeops.db")
    migrate(conn)
    plan_repository = SqlitePlanRepository(conn)
    feedback_repository = SqliteExecutionFeedbackRepository(conn)
    collector = RequestExecutionFeedbackCollector()
    counters = {"tool": 0, "policy": 0, "confirmation": 0, "controller": 0}
    limits = PlanningLimits(max_plan_steps=4)
    draft = PlanDraft(
        tuple(
            PlanStepDraft(
                f"step_{position}",
                position,
                f"objective {position}",
                f"outcome {position}",
                (() if position == 1 else (f"step_{position - 1}",)),
            )
            for position in range(1, step_count + 1)
        )
    )
    planner = FakePlannerModelClient(draft)
    executor = ReactExecutor(
        _ScriptedModel(decisions), feedback_sink=collector
    )
    service = RuntimeService(
        create_test_skill_service(),
        intent_service=_Intent(IntentType.PLAN_REQUEST),
        policy_service=_Policy(counters),
        conn=conn,
        log_root=root / "logs",
        execution_scope_factory=lambda: _tool_runtime(counters, set()),
        executor=executor,
        planning_route_client=FakePlanningRouteClient(PlanRoute("multi_step")),
        planning_service=PlanningService(planner, plan_repository, limits=limits),
        plan_controller=PlanController(
            plan_repository,
            executor,
            limits=limits,
            planner=planner,
            finalizer=FakePlanFinalizerClient(PlanFinalizerOutput("plan complete")),
        ),
        planning_limits=limits,
        outcome_finalizer=RuntimeOutcomeFinalizer(
            collector,
            feedback_repository,
            plan_repository=plan_repository,
        ),
    )
    return service, feedback_repository, counters


def _tool_runtime(counters: dict[str, int], failed_calls: set[str]) -> ToolRuntime:
    definition = ToolDefinition(
        "fixture.read",
        "Read deterministic fixture data.",
        {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False},
        ToolEffect.READ,
        ToolRisk.LOW,
    )

    def handler(call: ToolCall) -> ToolResult:
        counters["tool"] += 1
        if call.call_id in failed_calls:
            return ToolResult(
                call.call_id,
                call.tool_name,
                ToolCallStatus.FAILED,
                error=ToolError("fixture_failed", "safe fixture failure", True),
            )
        return ToolResult(
            call.call_id,
            call.tool_name,
            ToolCallStatus.SUCCEEDED,
            {"ok": True},
            (ExecutionEvidence("fixture_read", "Fixture was read.", f"fixture/ref_{call.call_id}"),),
        )

    return ToolRuntime.from_registry(ToolRegistry(((definition, handler),)))


class _Intent:
    def __init__(self, intent_type: IntentType) -> None:
        self.intent_type = intent_type

    def classify(self, _request):
        return IntentDecision(self.intent_type, 1.0)


class _ScriptedModel:
    def __init__(self, decisions) -> None:
        self._decisions = list(decisions)

    def decide(self, _model_input, *, llm_log=None):
        del llm_log
        if not self._decisions:
            raise AssertionError("No scripted Executor decision remains.")
        return self._decisions.pop(0)


class _Policy:
    def __init__(self, counters: dict[str, int]) -> None:
        self.counters = counters

    def evaluate(self, _request, _intent):
        self.counters["policy"] += 1
        return PolicyDecision(PolicyAction.ALLOW, allowed_effects=["read"])


class _FailingRepository:
    def save(self, _feedback) -> None:
        raise RuntimeError("private repository failure")

    def get_for_run(self, _session_id, _run_id):
        raise AssertionError("not used")

    def get_latest(self, _session_id):
        return None


class _FailingCollector(RequestExecutionFeedbackCollector):
    def snapshot(self, _run_id):
        raise ExecutionFeedbackCollectionError(
            "Execution feedback source is unavailable.",
            code="execution_feedback_source_incomplete",
        )


class _ExplodingExporter:
    def export(self, _records) -> None:
        raise RuntimeError("private exporter failure")


class _ExporterFailingRuntime(RuntimeService):
    def _build_request_telemetry(self, request: RuntimeRequest) -> RequestTelemetry:
        return RequestTelemetry(
            run_id=request.run_id,
            session_id=request.session_id,
            turn_id=request.turn_id,
            legacy_sink=OptionalLogAppender(None),
            exporter=_ExplodingExporter(),
        )


def _request(run_id: str) -> RuntimeRequest:
    return RuntimeRequest("safe fixture goal", "session_1", run_id=run_id, turn_id=f"turn_{run_id}")


def _action(call_id: str) -> ToolActionDecision:
    return ToolActionDecision(ToolCall(call_id, "fixture.read", {}))


def _answer(
    message: str,
    claim_id: str,
    call_id: str,
    *evidence_refs: str,
) -> FinalAnswerDecision:
    return FinalAnswerDecision(
        message,
        (FinalAnswerActionClaim(claim_id, call_id, tuple(evidence_refs)),),
    )


def _confirm(preview) -> PlanCommand:
    return PlanCommand(
        "command_confirm",
        preview.tool_result["plan_id"],
        "session_1",
        preview.tool_result["revision"],
        PlanCommandAction.CONFIRM,
    )


def _recovery(root: Path) -> RecoveryRuntime:
    conn = connect_sqlite(root / "lifeops.db")
    migrate(conn)
    return RecoveryRuntime(conn, root / "logs")


def _latest_recovery_graph(root: Path):
    store = FileTraceStore(root / "logs")
    trace_ids = []
    for path in (root / "logs").rglob("traces.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if (
                row.get("record_type") == "trace"
                and str(row.get("run_id", "")).startswith("recovery-run_")
            ):
                trace_ids.append(row["trace_id"])
    return TraceReader(store).get_trace(trace_ids[-1])


if __name__ == "__main__":
    unittest.main()
