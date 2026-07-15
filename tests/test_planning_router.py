from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.observability.file_logs import LlmLogWriter, RequestLlmLog
from app.planning.errors import PlanContractError, PlanningRouteError
from app.planning.models import (
    DirectRoute,
    NeedUserRoute,
    PlanRoute,
    PlanningRouteInput,
)
from app.planning.router import (
    FakePlanningRouteClient,
    OpenAIPlanningRouteClient,
    parse_planning_route,
)
from app.runtime.models import RuntimeRequest


class PlanningRouterTest(unittest.TestCase):
    def test_fake_returns_direct_plan_and_need_user_without_side_effects(self) -> None:
        fake = FakePlanningRouteClient(
            DirectRoute("single_goal"),
            PlanRoute("dependent_goals"),
            NeedUserRoute("请补充日期。"),
        )
        self.assertIsInstance(fake.decide(_input()), DirectRoute)
        self.assertIsInstance(fake.decide(_input()), PlanRoute)
        self.assertIsInstance(fake.decide(_input()), NeedUserRoute)
        self.assertEqual(len(fake.inputs), 3)

    def test_schema_parser_rejects_unknown_fenced_and_mismatched_fields(self) -> None:
        self.assertEqual(
            parse_planning_route('{"route":"direct","reason_code":"single","question":null}'),
            DirectRoute("single"),
        )
        invalid = (
            '```json\n{"route":"plan","reason_code":"multi","question":null}\n```',
            '{"route":"direct","reason_code":"single","question":null,"tool_name":"x"}',
            '{"route":"need_user","reason_code":"missing","question":"date?"}',
            '{"route":"unknown","reason_code":null,"question":null}',
        )
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(PlanContractError):
                parse_planning_route(payload)

    def test_production_adapter_logs_request_local_success(self) -> None:
        response = SimpleNamespace(
            output_text=json.dumps({"route": "plan", "reason_code": "dependent", "question": None})
        )
        client = _Client(response=response)
        with tempfile.TemporaryDirectory() as temp_dir:
            writer = LlmLogWriter(Path(temp_dir) / "llm.jsonl")
            request = RuntimeRequest("goal", "session_1", turn_id="turn_1", run_id="run_1")
            decision = OpenAIPlanningRouteClient(client=client, model="test-model").decide(
                _input(), llm_log=RequestLlmLog(writer, request)
            )
            rows = writer.read_all()
        self.assertEqual(decision, PlanRoute("dependent"))
        self.assertEqual((rows[0]["run_id"], rows[0]["seq"], rows[0]["status"]), ("run_1", 1, "ok"))
        schema = client.requests[0]["text"]["format"]["schema"]
        self.assertEqual(
            [branch["properties"]["route"]["const"] for branch in schema["oneOf"]],
            ["direct", "plan", "need_user"],
        )
        self.assertEqual(
            [branch["properties"]["question"]["type"] for branch in schema["oneOf"]],
            ["null", "null", "string"],
        )
        self.assertEqual(
            [branch["properties"]["reason_code"]["type"] for branch in schema["oneOf"]],
            ["string", "string", "null"],
        )
        self.assertTrue(all(branch["additionalProperties"] is False for branch in schema["oneOf"]))

    def test_provider_failure_is_safe_and_logged(self) -> None:
        client = _Client(error=RuntimeError("secret provider detail"))
        sink = _Sink()
        with self.assertRaises(PlanningRouteError) as caught:
            OpenAIPlanningRouteClient(client=client, model="test-model").decide(_input(), llm_log=sink)
        self.assertEqual(caught.exception.code, "planning_route_failed")
        self.assertNotIn("secret", caught.exception.message)
        self.assertEqual(sink.records[0]["error_code"], "planning_route_failed")


class _Responses:
    def __init__(self, owner) -> None:
        self.owner = owner

    def create(self, **kwargs):
        self.owner.requests.append(kwargs)
        if self.owner.error is not None:
            raise self.owner.error
        return self.owner.response


class _Client:
    def __init__(self, *, response=None, error=None) -> None:
        self.response = response
        self.error = error
        self.requests = []
        self.responses = _Responses(self)


class _Sink:
    def __init__(self) -> None:
        self.records = []

    def record(self, **kwargs) -> None:
        self.records.append(kwargs)


def _input() -> PlanningRouteInput:
    return PlanningRouteInput(
        goal="先研究，再整理旅行信息",
        intent_summary="plan_request",
        tool_catalog=(
            {"name": "research.search_knowledge", "description": "Search", "effect": "read", "input_schema": {}},
        ),
    )


if __name__ == "__main__":
    unittest.main()
