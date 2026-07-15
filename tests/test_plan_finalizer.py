from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from app.executor.models import ExecutorResult, ExecutorStatus, ExecutorStopReason
from app.planning.controller import PlanController
from app.planning.errors import PlanContractError, PlanningError
from app.planning.finalizer import (
    FakePlanFinalizerClient,
    OpenAIPlanFinalizerClient,
    deterministic_finalizer_fallback,
    parse_finalizer_output,
)
from app.planning.models import (
    PlanCommand,
    PlanCommandAction,
    PlanDraft,
    PlanFinalizerInput,
    PlanFinalizerOutput,
    PlanFinalizerStepResult,
    PlanRunStatus,
    PlanStepDraft,
    PlanStepStatus,
    PlanningLimits,
)
from app.planning.repository import SqlitePlanRepository
from app.runtime.models import RuntimeRequest
from app.tools.models import AllowedToolSet
from app.tools.registry import ToolRegistry
from app.tools.runtime import ToolRuntime
from tests.helpers import create_test_connection


class PlanFinalizerAdapterTest(unittest.TestCase):
    def test_production_adapter_uses_only_safe_read_only_payload_and_logs(self) -> None:
        response = PlanFinalizerOutput("资料已保存。", True, ("ev_1",))
        client = _Client(
            SimpleNamespace(
                output_text=json.dumps(
                    {
                        "message": response.message,
                        "claims_write_success": response.claims_write_success,
                        "evidence_refs": list(response.evidence_refs),
                    }
                )
            )
        )
        sink = _Sink()
        actual = OpenAIPlanFinalizerClient(
            client=client, model="test-model"
        ).finalize(_input(evidence=("ev_1",)), llm_log=sink)

        self.assertEqual(actual, response)
        request = client.requests[0]
        payload = json.loads(request["input"])
        self.assertEqual(payload["goal"], "完成研究")
        self.assertNotIn("tools", request)
        serialized = json.dumps(payload)
        for forbidden in ("tool_output", "arguments", "prompt", "transcript", "observation"):
            self.assertNotIn(forbidden, serialized)
        self.assertIn(
            "Completed read-only or temporary-result steps do not require evidence_refs",
            request["instructions"],
        )
        self.assertEqual(sink.records[0]["status"], "ok")

    def test_output_rejects_unsupported_write_claim_and_unknown_evidence(self) -> None:
        without_evidence = json.dumps(
            {
                "message": "已写入。",
                "claims_write_success": True,
                "evidence_refs": [],
            }
        )
        unknown_evidence = json.dumps(
            {
                "message": "已写入。",
                "claims_write_success": True,
                "evidence_refs": ["invented"],
            }
        )
        with self.assertRaises(PlanContractError):
            parse_finalizer_output(without_evidence, _input())
        with self.assertRaises(PlanContractError):
            parse_finalizer_output(unknown_evidence, _input(evidence=("ev_1",)))

    def test_provider_failure_is_logged_with_safe_error(self) -> None:
        sink = _Sink()
        adapter = OpenAIPlanFinalizerClient(
            client=_Client(error=RuntimeError("secret")), model="test-model"
        )
        with self.assertRaises(PlanningError) as caught:
            adapter.finalize(_input(), llm_log=sink)
        self.assertEqual(caught.exception.code, "plan_finalization_failed")
        self.assertNotIn("secret", caught.exception.message)
        self.assertEqual(sink.records[0]["error_code"], "plan_finalization_failed")

    def test_deterministic_fallback_uses_safe_summaries_only(self) -> None:
        output = deterministic_finalizer_fallback(_input())
        self.assertIn("安全摘要", output.message)
        self.assertFalse(output.claims_write_success)
        self.assertEqual(output.evidence_refs, ())


class PlanFinalizerControllerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = create_test_connection()
        self.repo = SqlitePlanRepository(self.conn)
        self.limits = PlanningLimits(max_plan_steps=2)

    def tearDown(self) -> None:
        self.conn.close()

    def test_completed_plan_returns_finalizer_message(self) -> None:
        finalizer = FakePlanFinalizerClient(PlanFinalizerOutput("最终答复"))
        result = self._execute(finalizer)

        self.assertEqual(result.run.status, PlanRunStatus.COMPLETED)
        self.assertEqual(result.final_message, "最终答复")
        self.assertFalse(result.used_finalizer_fallback)
        self.assertEqual(
            finalizer.inputs[0].step_results[0].safe_result_summary,
            "Completed: 完成",
        )

    def test_finalizer_failure_keeps_completed_run_and_returns_fallback(self) -> None:
        result = self._execute(
            FakePlanFinalizerClient(
                PlanningError("failed", code="plan_finalization_failed")
            )
        )

        self.assertEqual(result.run.status, PlanRunStatus.COMPLETED)
        self.assertTrue(result.used_finalizer_fallback)
        self.assertIn("Completed: 完成", result.final_message or "")

    def _execute(self, finalizer) -> object:
        run, _ = self.repo.create_initial_plan(
            session_id="session_1",
            goal="完成研究",
            draft=PlanDraft((PlanStepDraft("one", 1, "研究", "完成"),)),
            limits=self.limits,
            plan_id="plan_1",
        )
        controller = PlanController(
            self.repo,
            _Executor(),
            limits=self.limits,
            finalizer=finalizer,
        )
        return controller.confirm_and_execute(
            PlanCommand(
                "confirm_1",
                run.plan_id,
                "session_1",
                1,
                PlanCommandAction.CONFIRM,
            ),
            RuntimeRequest("完成研究", "session_1", run_id="run_1"),
            (),
            AllowedToolSet(),
            ToolRuntime.from_registry(ToolRegistry()),
        )


class _Executor:
    def execute_step(self, request, step_input, prompts, tools, scope, trace=None, llm_log=None):
        return ExecutorResult(
            "run_1",
            ExecutorStatus.COMPLETED,
            ExecutorStopReason.FINAL_ANSWER,
            "done",
            1,
        )


class _Responses:
    def __init__(self, owner) -> None:
        self.owner = owner

    def create(self, **kwargs):
        self.owner.requests.append(kwargs)
        if self.owner.error is not None:
            raise self.owner.error
        return self.owner.responses_queue.pop(0)


class _Client:
    def __init__(self, *responses, error=None) -> None:
        self.responses_queue = list(responses)
        self.error = error
        self.requests = []
        self.responses = _Responses(self)


class _Sink:
    def __init__(self) -> None:
        self.records = []

    def record(self, **kwargs) -> None:
        self.records.append(kwargs)


def _input(*, evidence: tuple[str, ...] = ()) -> PlanFinalizerInput:
    return PlanFinalizerInput(
        goal="完成研究",
        revision=1,
        step_results=(
            PlanFinalizerStepResult(
                step_id="one",
                position=1,
                status=PlanStepStatus.COMPLETED,
                safe_result_summary="安全摘要",
                evidence_refs=evidence,
            ),
        ),
    )


if __name__ == "__main__":
    unittest.main()
