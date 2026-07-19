from __future__ import annotations

import json
import tempfile
import unittest
from types import SimpleNamespace

from app.observability.file_logs import RequestLlmLog, SessionLogWriter
from app.planning.finalizer import OpenAIPlanFinalizerClient
from app.planning.models import (
    PlanFinalizerInput,
    PlanFinalizerStepResult,
    PlannerInput,
    PlanningLimits,
    PlanningRouteInput,
    PlanStep,
    PlanStepStatus,
    ReplanInput,
)
from app.planning.planner import OpenAIPlannerModelClient
from app.planning.router import OpenAIPlanningRouteClient
from app.runtime.models import RuntimeRequest


class PlanningLlmLogTest(unittest.TestCase):
    def test_route_plan_replan_and_finalize_share_ordered_request_log(self) -> None:
        route_client = _Client(
            _response({"route": "plan", "reason_code": "multi", "question": None})
        )
        plan_payload = {
            "result_type": "plan",
            "steps": [
                {
                    "step_id": "one",
                    "position": 1,
                    "objective": "研究",
                    "expected_outcome": "完成",
                    "dependency_step_ids": [],
                }
            ],
            "question": None,
        }
        planner_client = _Client(_response(plan_payload), _response(plan_payload))
        finalizer_client = _Client(
            _response(
                {
                    "message": "完成。",
                    "claims_write_success": False,
                    "evidence_refs": [],
                }
            )
        )
        request = RuntimeRequest("private-goal", "session_1", run_id="run_1")
        limits = PlanningLimits(max_plan_steps=2)
        planner_input = PlannerInput("goal", (), (), limits)
        failed = PlanStep(
            "plan_1",
            1,
            "failed",
            1,
            "研究",
            "完成",
            (),
            PlanStepStatus.GOAL_NOT_ACHIEVED,
            error_code="plan_step_goal_not_achieved",
        )
        finalizer_input = PlanFinalizerInput(
            "goal",
            1,
            (
                PlanFinalizerStepResult(
                    "one", 1, PlanStepStatus.COMPLETED, "安全摘要"
                ),
            ),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            session = SessionLogWriter.create(tmpdir, session_id=request.session_id)
            sink = RequestLlmLog(session.llm_log, request)
            OpenAIPlanningRouteClient(client=route_client, model="route").decide(
                PlanningRouteInput("goal", "plan_request", limits=limits),
                llm_log=sink,
            )
            planner = OpenAIPlannerModelClient(client=planner_client, model="planner")
            planner.create_plan(planner_input, llm_log=sink)
            planner.replan(
                ReplanInput(planner_input, (), failed), llm_log=sink
            )
            OpenAIPlanFinalizerClient(
                client=finalizer_client, model="finalizer"
            ).finalize(finalizer_input, llm_log=sink)

            rows = session.llm_log.read_all()

        self.assertEqual([row["seq"] for row in rows], [1, 2, 3, 4])
        self.assertEqual(
            [row["request"]["text"]["format"]["name"] for row in rows],
            ["planning_route", "plan_draft", "plan_draft", "plan_finalization"],
        )
        self.assertTrue(all(row["run_id"] == "run_1" for row in rows))
        self.assertTrue(all(row["status"] == "ok" for row in rows))


class _Responses:
    def __init__(self, owner) -> None:
        self.owner = owner

    def create(self, **kwargs):
        self.owner.requests.append(kwargs)
        return self.owner.queue.pop(0)


class _Client:
    def __init__(self, *responses) -> None:
        self.queue = list(responses)
        self.requests = []
        self.responses = _Responses(self)


def _response(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(output_text=json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
