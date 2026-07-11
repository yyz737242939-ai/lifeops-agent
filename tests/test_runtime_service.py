from __future__ import annotations

import tempfile
import unittest

from app.observability.file_logs import SessionLogWriter
from app.intent.models import IntentDecision, IntentType
from app.policy.models import PolicyAction, PolicyDecision
from app.runtime.models import RuntimeRequest, RuntimeStatus
from app.runtime.service import RuntimeService
from tests.helpers import create_test_connection, create_test_skill_service


class RuntimeServiceTest(unittest.TestCase):
    def test_handle_writes_run_record_and_event_log(self) -> None:
        conn = create_test_connection()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                request = RuntimeRequest(
                    user_input="把明天跑步加入任务",
                    session_id="session_test",
                    run_id="run_runtime_success",
                )
                session_log = SessionLogWriter.create(
                    tmpdir,
                    session_id=request.session_id,
                )

                result = RuntimeService(
                    create_test_skill_service(),
                    conn=conn,
                    event_log=session_log.event_log,
                ).handle(request)

                self.assertEqual(result.status, RuntimeStatus.OK)
                self.assertEqual(result.intent["intent_type"], "write_request")
                self.assertEqual(result.policy["action"], "allow")

                row = conn.execute(
                    "SELECT id, status, error_code FROM run_records WHERE id = ?",
                    (request.run_id,),
                ).fetchone()
                self.assertEqual(row["id"], request.run_id)
                self.assertEqual(row["status"], "ok")
                self.assertIsNone(row["error_code"])

                events = session_log.event_log.read_all()
                self.assertEqual(
                    [event["event_type"] for event in events],
                    [
                        "runtime.run.started",
                        "runtime.request.created",
                        "intent.classified",
                        "policy.decided",
                        "orchestration.route.selected",
                        "skill.selected",
                        "runtime.run.completed",
                    ],
                )
                self.assertEqual(events[2]["payload"]["intent_type"], "write_request")
                self.assertEqual(events[3]["payload"]["action"], "allow")
                self.assertEqual(events[4]["payload"]["route"], "allow")
                self.assertEqual(
                    events[6]["payload"]["graph_path"],
                    [
                        "classify_intent",
                        "decide_policy",
                        "prepare_skills",
                        "stub_execute",
                        "finalize",
                    ],
                )
                self.assertEqual(events[0]["run_id"], request.run_id)
                self.assertEqual(events[0]["session_id"], request.session_id)
        finally:
            conn.close()

    def test_handle_can_write_event_log_without_sqlite_connection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            request = _request("把明天跑步加入任务")
            session_log = SessionLogWriter.create(tmpdir, session_id=request.session_id)

            result = RuntimeService(
                create_test_skill_service(),
                event_log=session_log.event_log,
            ).handle(request)

            self.assertEqual(result.status, RuntimeStatus.OK)
            events = session_log.event_log.read_all()
            self.assertEqual(events[0]["event_type"], "runtime.run.started")
            self.assertEqual(events[-1]["event_type"], "runtime.run.completed")

    def test_requires_confirmation_result_does_not_claim_write(self) -> None:
        result = RuntimeService(create_test_skill_service()).handle(_request("计划一下"))

        self.assertEqual(result.status, RuntimeStatus.REQUIRES_CONFIRMATION)
        self.assertEqual(result.policy["action"], "requires_confirmation")
        self.assertNotIn("已写入", result.message)
        self.assertNotIn("saved", result.message.lower())

    def test_policy_allow_is_still_stubbed_execution(self) -> None:
        result = RuntimeService(create_test_skill_service()).handle(
            _request("把明天跑步加入任务")
        )

        self.assertEqual(result.status, RuntimeStatus.OK)
        self.assertEqual(result.policy["action"], "allow")
        self.assertEqual(result.trace_summary, ["runtime.orchestration.stubbed"])
        self.assertIn("execution is not implemented yet", result.message)

    def test_intent_failure_returns_error_and_skips_policy(self) -> None:
        policy = RecordingPolicyService()
        result = RuntimeService(
            create_test_skill_service(),
            intent_service=FailingIntentService(),
            policy_service=policy,
        ).handle(_request("hello"))

        self.assertEqual(result.status, RuntimeStatus.ERROR)
        self.assertEqual(result.error_code, "runtime.intent_failed")
        self.assertFalse(policy.called)
        self.assertIsNone(result.policy)

    def test_policy_failure_returns_error(self) -> None:
        result = RuntimeService(
            create_test_skill_service(),
            intent_service=FixedIntentService(),
            policy_service=FailingPolicyService(),
        ).handle(_request("hello"))

        self.assertEqual(result.status, RuntimeStatus.ERROR)
        self.assertEqual(result.error_code, "runtime.policy_failed")
        self.assertEqual(result.intent["intent_type"], "chat")
        self.assertIsNone(result.policy)


class FailingIntentService:
    def classify(self, request: RuntimeRequest) -> IntentDecision:
        raise RuntimeError("boom")


class FixedIntentService:
    def classify(self, request: RuntimeRequest) -> IntentDecision:
        return IntentDecision(intent_type=IntentType.CHAT, confidence=0.8)


class RecordingPolicyService:
    called = False

    def evaluate(self, request: RuntimeRequest, intent: IntentDecision) -> PolicyDecision:
        self.called = True
        return PolicyDecision(action=PolicyAction.ALLOW)


class FailingPolicyService:
    def evaluate(self, request: RuntimeRequest, intent: IntentDecision) -> PolicyDecision:
        raise RuntimeError("boom")


def _request(user_input: str) -> RuntimeRequest:
    return RuntimeRequest(user_input=user_input, session_id="session_test")


if __name__ == "__main__":
    unittest.main()
