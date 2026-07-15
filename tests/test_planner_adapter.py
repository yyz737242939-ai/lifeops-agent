from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from app.planning.errors import PlanContractError, PlanningError
from app.planning.models import (
    PlanDraft,
    PlannerInput,
    PlannerNeedUser,
    PlanningLimits,
    PlanningScopeRef,
    PlanningSnapshotEnvelope,
    PlanStep,
    PlanStepDraft,
    PlanStepStatus,
    ReplanInput,
)
from app.planning.planner import (
    FakePlannerModelClient,
    FakePlanningSnapshotProvider,
    OpenAIPlannerModelClient,
    parse_plan_draft,
)


class PlannerAdapterTest(unittest.TestCase):
    def test_fake_consumers_preserve_typed_initial_replan_and_snapshot_inputs(self) -> None:
        draft = _draft()
        fake = FakePlannerModelClient(draft, PlannerNeedUser("请补充范围。"))
        planner_input = _input()
        failed = _step("failed", PlanStepStatus.GOAL_NOT_ACHIEVED)
        replan_input = ReplanInput(planner_input, (), failed, ("保留已确认范围",))
        envelope = planner_input.snapshots[0]
        snapshots = FakePlanningSnapshotProvider(envelope)
        refs = (PlanningScopeRef("research", "topic_1"),)

        self.assertIs(fake.create_plan(planner_input), draft)
        self.assertIsInstance(fake.replan(replan_input), PlannerNeedUser)
        self.assertEqual(snapshots.load(refs), (envelope,))
        self.assertEqual((fake.create_inputs, fake.replan_inputs, snapshots.requests), ([planner_input], [replan_input], [refs]))

    def test_parser_accepts_complete_plan_and_structured_clarification(self) -> None:
        self.assertEqual(parse_plan_draft(json.dumps(_payload()), _input()), _draft())
        clarification = parse_plan_draft(
            json.dumps({"result_type": "need_user", "steps": [], "question": "需要哪个主题？"}),
            _input(),
        )
        self.assertEqual(clarification, PlannerNeedUser("需要哪个主题？"))

    def test_parser_rejects_forbidden_fields_invalid_dependencies_and_limits(self) -> None:
        cases = []
        forbidden = _payload()
        forbidden["steps"][0]["tool_name"] = "research.search_knowledge"
        cases.append(forbidden)
        unknown = _payload()
        unknown["private_reasoning"] = "secret"
        cases.append(unknown)
        duplicate = _payload()
        duplicate["steps"].append(dict(duplicate["steps"][0]))
        cases.append(duplicate)
        cycle = _payload()
        cycle["steps"][0]["dependency_step_ids"] = ["step_2"]
        cases.append(cycle)
        wrong_type = _payload()
        wrong_type["steps"][0]["dependency_step_ids"] = "step_2"
        cases.append(wrong_type)
        oversized = _payload()
        oversized["steps"].append(
            {"step_id": "step_3", "position": 3, "objective": "C", "expected_outcome": "C done", "dependency_step_ids": ["step_2"]}
        )
        cases.append(oversized)
        limited = _input(limits=PlanningLimits(max_plan_steps=2))
        for index, payload in enumerate(cases):
            with self.subTest(index=index), self.assertRaises(PlanContractError):
                parse_plan_draft(json.dumps(payload), limited)

    def test_production_adapter_records_create_and_replan_interactions(self) -> None:
        client = _Client(
            SimpleNamespace(output_text=json.dumps(_payload())),
            SimpleNamespace(output_text=json.dumps(_payload())),
        )
        sink = _Sink()
        adapter = OpenAIPlannerModelClient(client=client, model="test-model")
        planner_input = _input()
        completed = _step("done", PlanStepStatus.COMPLETED, summary="safe")
        failed = _step("failed", PlanStepStatus.GOAL_NOT_ACHIEVED)

        self.assertEqual(adapter.create_plan(planner_input, llm_log=sink), _draft())
        self.assertEqual(
            adapter.replan(
                ReplanInput(planner_input, (completed,), failed, ("keep",)), llm_log=sink
            ),
            _draft(),
        )
        self.assertEqual([item["status"] for item in sink.records], ["ok", "ok"])
        payloads = [json.loads(item["input"]) for item in client.requests]
        self.assertEqual([item["operation"] for item in payloads], ["create_plan", "replan"])
        self.assertNotIn("tool_name", json.dumps(payloads))
        schema = client.requests[0]["text"]["format"]["schema"]
        self.assertEqual(
            [branch["properties"]["result_type"]["const"] for branch in schema["oneOf"]],
            ["plan", "need_user"],
        )
        self.assertEqual(schema["oneOf"][0]["properties"]["steps"]["minItems"], 1)
        self.assertEqual(schema["oneOf"][0]["properties"]["question"]["type"], "null")
        self.assertEqual(schema["oneOf"][1]["properties"]["steps"]["maxItems"], 0)

    def test_provider_failure_is_safe_and_fail_closed(self) -> None:
        sink = _Sink()
        adapter = OpenAIPlannerModelClient(
            client=_Client(error=RuntimeError("secret provider detail")), model="test-model"
        )
        with self.assertRaises(PlanningError) as caught:
            adapter.create_plan(_input(), llm_log=sink)
        self.assertEqual(caught.exception.code, "plan_generation_failed")
        self.assertNotIn("secret", caught.exception.message)
        self.assertEqual(sink.records[0]["error_code"], "plan_generation_failed")


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


def _input(*, limits: PlanningLimits | None = None) -> PlannerInput:
    return PlannerInput(
        goal="研究主题并形成摘要",
        prompt_contributions=(),
        tool_catalog=(
            {"name": "research.search_knowledge", "description": "Search", "effect": "read", "input_schema": {}},
        ),
        limits=limits or PlanningLimits(max_plan_steps=2),
        snapshots=(PlanningSnapshotEnvelope("research", "topic_1", {"title": "Agents"}),),
    )


def _draft() -> PlanDraft:
    return PlanDraft(
        (
            PlanStepDraft("step_1", 1, "读取主题", "获得材料"),
            PlanStepDraft("step_2", 2, "形成摘要", "获得摘要", ("step_1",)),
        )
    )


def _payload() -> dict:
    return {
        "result_type": "plan",
        "steps": [
            {"step_id": "step_1", "position": 1, "objective": "读取主题", "expected_outcome": "获得材料", "dependency_step_ids": []},
            {"step_id": "step_2", "position": 2, "objective": "形成摘要", "expected_outcome": "获得摘要", "dependency_step_ids": ["step_1"]},
        ],
        "question": None,
    }


def _step(step_id: str, status: PlanStepStatus, *, summary: str | None = None) -> PlanStep:
    return PlanStep("plan_1", 1, step_id, 1, step_id, f"{step_id} done", (), status, safe_result_summary=summary)


if __name__ == "__main__":
    unittest.main()
