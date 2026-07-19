from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.evals import (
    EVAL_MANIFEST_SCHEMA_VERSION,
    EvalCase,
    EvalExecutionMode,
    EvalExpectations,
    EvalTargetExecutorFactory,
    PlanCommandInvocation,
    PlanCommandSequenceTargetExecutor,
    RecoveryTargetExecutor,
    RuntimeRequestTargetExecutor,
)
from app.evals.workspace import EvalWorkspaceFactory
from app.executor.models import FinalAnswerDecision
from app.executor.service import ReactExecutor
from app.observability.trace_reader import FileTraceStore, TraceReader
from app.observability.trace_vocabulary import TraceStatus
from app.planning.models import PlanCommand, PlanCommandAction
from app.recovery.models import (
    ExecutionPath,
    FeedbackOverallStatus,
    RecoveryContext,
    RecoveryOutputMode,
    RecoveryResult,
    RecoveryStopPoint,
)
from app.runtime.models import RuntimeRequest, RuntimeResult, RuntimeStatus
from app.runtime.service import RuntimeService
from tests.helpers import create_test_skill_service


class EvalTargetAdaptersTest(unittest.TestCase):
    def test_runtime_request_adapter_uses_normal_handle_and_closes_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = EvalWorkspaceFactory(Path(tmpdir)).create("runtime-case")
            request = RuntimeRequest(
                "把明天跑步加入任务",
                "session-eval",
                turn_id="turn-runtime",
                run_id="run-runtime",
            )
            service = RuntimeService(
                create_test_skill_service(),
                log_root=workspace.paths.log_root,
                executor=ReactExecutor(
                    _FinalAnswerModel()
                ),
            )
            executor = RuntimeRequestTargetExecutor(service, request)

            target = executor.execute()
            executor.close()
            executor.close()

            self.assertEqual(target.execution_mode, EvalExecutionMode.RUNTIME_REQUEST)
            self.assertEqual(target.run_ids, ("run-runtime",))
            self.assertEqual(target.turn_id, "turn-runtime")
            trace = TraceReader(
                FileTraceStore(workspace.paths.log_root)
            ).find_by_run("run-runtime")
            self.assertEqual(trace.trace.status, TraceStatus.OK)
            workspace.close()

    def test_plan_sequence_calls_preview_then_public_plan_commands(self) -> None:
        service = _RecordingRuntimeService()
        preview = RuntimeRequest("plan", "session-plan", "turn-0", "run-0")
        invocation = PlanCommandInvocation(
            PlanCommand(
                "command-1",
                "plan-1",
                "session-plan",
                1,
                PlanCommandAction.CONFIRM,
            ),
            RuntimeRequest("confirm", "session-plan", "turn-1", "run-1"),
        )
        executor = PlanCommandSequenceTargetExecutor(
            service, preview, (invocation,)
        )

        target = executor.execute()
        executor.close()

        self.assertEqual(service.calls, [("handle", "run-0"), ("confirm", "run-1")])
        self.assertEqual(target.run_ids, ("run-0", "run-1"))
        self.assertEqual(target.plan_id, "plan-1")
        self.assertTrue(service.closed)

    def test_recovery_adapter_calls_read_only_public_explain_and_resolves_identity(self) -> None:
        runtime = _RecordingRecoveryRuntime(_recovery_result())
        resolver = _RecoveryIdentityResolver()
        executor = RecoveryTargetExecutor(
            runtime,
            session_id="session-recovery",
            source_run_id="run-source",
            identity_resolver=resolver,
        )

        target = executor.execute()
        executor.close()

        self.assertEqual(runtime.calls, [("session-recovery", "run-source")])
        self.assertEqual(target.run_id, "recovery-run-1")
        self.assertEqual(target.turn_id, "recovery-turn-1")
        self.assertEqual(target.source_run_id, "run-source")
        self.assertTrue(runtime.closed)

    def test_factory_selects_only_registered_fixture_or_mode_builders(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = EvalWorkspaceFactory(Path(tmpdir)).create("factory-case")
            builder = _StaticTargetBuilder()
            factory = EvalTargetExecutorFactory({"runtime_request": builder})
            executor = factory.create(_case("factory-case"), workspace)
            self.assertIs(executor, builder.executor)

            with self.assertRaises(ValueError):
                factory.create(
                    _case("missing-case", fixture_ref="missing-fixture"), workspace
                )
            workspace.close()


class _RecordingRuntimeService:
    def __init__(self) -> None:
        self.calls = []
        self.closed = False

    def handle(self, request):
        self.calls.append(("handle", request.run_id))
        return RuntimeResult(
            request.run_id,
            request.session_id,
            RuntimeStatus.REQUIRES_CONFIRMATION,
            "preview",
            {"type": "plan_preview", "plan_id": "plan-1", "revision": 1},
        )

    def handle_plan_command(self, command, request):
        self.calls.append((command.action.value, request.run_id))
        return RuntimeResult(
            request.run_id, request.session_id, RuntimeStatus.OK, "command"
        )

    def close(self):
        self.closed = True


class _FinalAnswerModel:
    def decide(self, model_input, *, llm_log=None):
        return FinalAnswerDecision("fixture final")


class _RecordingRecoveryRuntime:
    def __init__(self, result) -> None:
        self.result = result
        self.calls = []
        self.closed = False

    def explain(self, session_id, run_id=None):
        self.calls.append((session_id, run_id))
        return self.result

    def close(self):
        self.closed = True


class _RecoveryIdentityResolver:
    def resolve(self, result):
        return "recovery-run-1", "recovery-turn-1"


class _StaticTargetBuilder:
    def __init__(self) -> None:
        self.executor = _StaticExecutor()

    def build(self, case, workspace):
        return self.executor


class _StaticExecutor:
    execution_mode = EvalExecutionMode.RUNTIME_REQUEST

    def execute(self):
        raise AssertionError("not called")

    def close(self):
        pass


def _case(case_id: str, *, fixture_ref: str | None = None) -> EvalCase:
    return EvalCase(
        schema_version=EVAL_MANIFEST_SCHEMA_VERSION,
        case_id=case_id,
        title="Target case",
        description="Target adapter fixture.",
        execution_mode=EvalExecutionMode.RUNTIME_REQUEST,
        input={},
        expectations=EvalExpectations(),
        grader_ids=("trace-contract",),
        fixture_ref=fixture_ref,
    )


def _recovery_result() -> RecoveryResult:
    return RecoveryResult(
        RecoveryContext(
            source_trace_id="trace-source",
            source_run_id="run-source",
            session_id="session-recovery",
            goal_summary="Recover fixture run.",
            path=ExecutionPath.DIRECT,
            stop_point=RecoveryStopPoint(FeedbackOverallStatus.COMPLETED),
            succeeded_actions=(),
            failed_actions=(),
            completed_steps=(),
            failed_steps=(),
            not_run_steps=(),
            durable_evidence=(),
            safe_next_steps=(),
            generated_at="2026-07-19T01:00:00+00:00",
        ),
        "Recovery explanation.",
        RecoveryOutputMode.DETERMINISTIC,
    )


if __name__ == "__main__":
    unittest.main()
