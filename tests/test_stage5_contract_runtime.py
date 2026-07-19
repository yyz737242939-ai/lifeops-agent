from __future__ import annotations

import tempfile
import unittest
import logging
import inspect
from dataclasses import fields
from pathlib import Path

from app.intent.models import IntentDecision, IntentType
from app.intent.service import IntentService
from app.policy.models import PolicyAction
from app.policy.service import PolicyService
from app.observability.file_logs import SessionLogWriter
from app.observability.logger import configure_application_logging
from app.orchestration.state import GraphState
from app.runtime.models import RuntimeRequest, RuntimeResult
from app.runtime.service import RuntimeService
from app.skills.models import SkillDefinition
from app.skills.registry import SkillRegistry
from app.skills.service import SkillService
from tests.helpers import create_test_connection, create_test_skill_service


class Stage5RuntimeContractTest(unittest.TestCase):
    def test_runtime_owns_one_explicit_execution_scope_per_run(self) -> None:
        parameters = inspect.signature(RuntimeService.__init__).parameters

        self.assertIn("execution_scope_factory", parameters)
        self.assertNotIn("tool_runtime_factory", parameters)

    def test_runtime_models_expose_only_frozen_public_fields(self) -> None:
        self.assertNotIn("metadata", {item.name for item in fields(RuntimeRequest)})
        self.assertEqual(
            tuple(item.name for item in fields(RuntimeResult)),
            ("run_id", "session_id", "status", "message", "tool_result", "error_code"),
        )
        self.assertNotIn("trace_summary", GraphState.__annotations__)

    def test_current_domains_reach_expected_intent_and_policy_effects(self) -> None:
        cases = (
            ("查询研究笔记", IntentType.READ, ("read", "external_read")),
            ("保存这篇研究笔记", IntentType.WRITE_REQUEST, ("write",)),
            ("查询东京旅行地点", IntentType.READ, ("read", "external_read")),
            ("创建东京旅行行程", IntentType.WRITE_REQUEST, ("write",)),
        )
        for user_input, expected_intent, expected_effects in cases:
            with self.subTest(user_input=user_input):
                request = RuntimeRequest(user_input=user_input, session_id="session_test")
                intent = IntentService().classify(request)
                policy = PolicyService().evaluate(request, intent)
                self.assertEqual(intent.intent_type, expected_intent)
                self.assertEqual(policy.action, PolicyAction.ALLOW)
                self.assertEqual(tuple(policy.allowed_effects), expected_effects)

    def test_llm_and_external_work_run_outside_a_sqlite_transaction(self) -> None:
        conn = create_test_connection()
        selection_client = _TransactionRecordingSkillSelectionClient(conn)
        skill_service = SkillService(
            SkillRegistry(
                [
                    SkillDefinition(
                        skill_id="research",
                        description="Research requests.",
                        root_path=Path("app/skills/research"),
                    )
                ]
            ),
            selection_client,
        )
        try:
            RuntimeService(skill_service, conn=conn).handle(
                RuntimeRequest(user_input="查询研究笔记", session_id="session_test")
            )
            self.assertFalse(selection_client.connection_was_in_transaction)
        finally:
            conn.close()

    def test_unexpected_orchestration_failure_leaves_a_finished_run_record(self) -> None:
        conn = create_test_connection()
        service = RuntimeService(create_test_skill_service(), conn=conn)
        service._orchestrator = _ExplodingOrchestrator()
        request = RuntimeRequest(
            user_input="查询研究笔记",
            session_id="session_test",
            run_id="run_unexpected_failure",
        )
        try:
            with self.assertRaises(RuntimeError):
                service.handle(request)
            row = conn.execute(
                "SELECT status, error_code FROM run_records WHERE id = ?",
                (request.run_id,),
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["status"], "error")
            self.assertEqual(row["error_code"], "runtime.orchestration_failed")
        finally:
            conn.close()

    def test_runtime_result_never_contains_internal_exception_text(self) -> None:
        secret = "provider-secret-path-C:/private/config"
        result = RuntimeService(
            create_test_skill_service(), intent_service=_FailingIntentService(secret)
        ).handle(RuntimeRequest(user_input="hello", session_id="session_test"))

        self.assertNotIn(secret, repr(result))

    def test_log_root_creates_one_isolated_directory_per_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                service = RuntimeService(create_test_skill_service(), log_root=tmpdir)
                service.handle(RuntimeRequest(user_input="hello", session_id="session_a"))
                service.handle(RuntimeRequest(user_input="hello", session_id="session_b"))

                session_dirs = sorted(Path(tmpdir).glob("session_*"))
                self.assertEqual(len(session_dirs), 2)
                metadata = [
                    (path / "metadata.json").read_text(encoding="utf-8")
                    for path in session_dirs
                ]
                self.assertTrue(any("session_a" in item for item in metadata))
                self.assertTrue(any("session_b" in item for item in metadata))
            finally:
                root = Path(tmpdir).resolve()
                logger = logging.getLogger("lifeops")
                for handler in list(logger.handlers):
                    if isinstance(handler, logging.FileHandler) and Path(
                        handler.baseFilename
                    ).is_relative_to(root):
                        logger.removeHandler(handler)
                        handler.close()

    def test_event_contract_has_no_duplicate_request_or_graph_path_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            writer = SessionLogWriter.create(tmpdir, session_id="session_test")
            RuntimeService(
                create_test_skill_service(), event_log=writer.event_log
            ).handle(RuntimeRequest(user_input="hello", session_id="session_test"))

            events = writer.event_log.read_all()
            self.assertNotIn(
                "runtime.request.created",
                [event["event_type"] for event in events],
            )
            for event in events:
                self.assertNotIn("graph_path", event["payload"])
                self.assertFalse(
                    {
                        "user_input",
                        "arguments",
                        "output",
                        "raw_html",
                        "trace_summary",
                        "classifier_results",
                        "denied_reason",
                    }
                    & set(event["payload"])
                )
            payload_fields = {
                event["event_type"]: set(event["payload"])
                for event in events
            }
            self.assertEqual(payload_fields["runtime.run.started"], set())
            self.assertEqual(
                payload_fields["intent.classified"],
                {"intent_type", "needs_clarification", "write_candidate"},
            )
            self.assertEqual(
                payload_fields["policy.decided"],
                {"action", "allowed_effects", "requires_confirmation"},
            )
            self.assertEqual(
                payload_fields["runtime.run.completed"], {"status"}
            )

    def test_application_logs_do_not_mirror_into_another_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first = root / "session_a"
            second = root / "session_b"
            first_log = configure_application_logging(first)
            second_log = configure_application_logging(second)
            logger = logging.getLogger("lifeops")
            try:
                logger.info("session-b-only-message")
                self.assertNotIn(
                    "session-b-only-message", first_log.read_text(encoding="utf-8")
                )
                self.assertIn(
                    "session-b-only-message", second_log.read_text(encoding="utf-8")
                )
            finally:
                for handler in list(logger.handlers):
                    if isinstance(handler, logging.FileHandler) and Path(
                        handler.baseFilename
                    ).is_relative_to(root.resolve()):
                        logger.removeHandler(handler)
                        handler.close()


class _TransactionRecordingSkillSelectionClient:
    def __init__(self, conn) -> None:
        self._conn = conn
        self.connection_was_in_transaction = False

    def select(self, request, skill_metadata):
        self.connection_was_in_transaction = self._conn.in_transaction
        return {"selected_skill_ids": [], "reason": "No Skill needed."}


class _ExplodingOrchestrator:
    def invoke(self, request, trace=None):
        raise RuntimeError("unexpected orchestration failure")


class _FailingIntentService:
    def __init__(self, message: str) -> None:
        self._message = message

    def classify(self, request: RuntimeRequest) -> IntentDecision:
        raise RuntimeError(self._message)


if __name__ == "__main__":
    unittest.main()
