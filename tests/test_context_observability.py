from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.context.errors import ContextErrorCode, ConversationRepositoryError
from app.context.models import (
    ContextBudget,
    ConversationRole,
    ConversationTurn,
    ConversationTurnKind,
)
from app.context.summarizer import OpenAIContextSummarizer
from app.observability.file_logs import RequestLlmLog, SessionLogWriter
from app.runtime.models import RuntimeRequest, RuntimeStatus
from tests.test_context_runtime_lifecycle import _Assembler, _Orchestrator, _Repository, _service


class ContextObservabilityTest(unittest.TestCase):
    def test_semantic_events_are_content_free(self) -> None:
        secret = "SECRET_CONTEXT_VALUE"
        with tempfile.TemporaryDirectory() as tmpdir:
            order: list[str] = []
            repository = _Repository(order)
            assembler = _Assembler(order)
            orchestrator = _Orchestrator(order)
            service = _service(repository, assembler, orchestrator)
            service._log_root = Path(tmpdir)

            result = service.handle(
                RuntimeRequest(secret, "session_1", turn_id="turn_1", run_id="run_1")
            )
            service.close()

            self.assertEqual(result.status, RuntimeStatus.OK)
            session_dir = next(item for item in Path(tmpdir).iterdir() if item.is_dir())
            event_text = (session_dir / "events.jsonl").read_text(encoding="utf-8")
            self.assertNotIn(secret, event_text)
            rows = _read_jsonl(session_dir / "events.jsonl")
            context_rows = [row for row in rows if row["event_type"].startswith("context.")]
            self.assertEqual(
                [row["event_type"] for row in context_rows],
                [
                    "context.turn.persisted",
                    "context.assembled",
                    "context.turn.persisted",
                ],
            )
            self.assertEqual(context_rows[1]["payload"]["assembly_id"], "assembly_1")
            self.assertEqual(context_rows[1]["payload"]["estimated_total_tokens"], 2)

    def test_llm_log_keeps_the_actual_bounded_context_request(self) -> None:
        secret = "SECRET_BOUNDED_TURN"
        with tempfile.TemporaryDirectory() as tmpdir:
            request = RuntimeRequest(secret, "session_1", turn_id="turn_1", run_id="run_1")
            logs = SessionLogWriter(Path(tmpdir) / "session")
            sink = RequestLlmLog(logs.llm_log, request)
            adapter = OpenAIContextSummarizer(
                client=_Client(SimpleNamespace(output_text='{"summary":"bounded"}')),
                model="test-model",
            )
            adapter.summarize(
                None,
                (
                    ConversationTurn(
                        1,
                        "session_1",
                        "turn_1",
                        1,
                        ConversationRole.USER,
                        ConversationTurnKind.NATURAL_INPUT,
                        secret,
                        "run_1",
                        "2026-07-16T00:00:00Z",
                    ),
                ),
                ContextBudget(100, 4, 20, 0, 0, 0, 40),
                llm_log=sink,
            )

            llm_text = logs.llm_log.path.read_text(encoding="utf-8")
            self.assertIn(secret, llm_text)
            self.assertEqual(_read_jsonl(logs.llm_log.path)[0]["status"], "ok")

    def test_assistant_persistence_failure_logs_only_safe_metadata(self) -> None:
        secret = "SECRET_REPOSITORY_DETAIL"
        with tempfile.TemporaryDirectory() as tmpdir:
            order: list[str] = []
            repository = _SecretFailingRepository(order, secret)
            service = _service(repository, _Assembler(order), _Orchestrator(order))
            service._log_root = Path(tmpdir)

            result = service.handle(
                RuntimeRequest("visible input", "session_1", turn_id="turn_1", run_id="run_1")
            )
            service.close()

            self.assertEqual(result.status, RuntimeStatus.OK)
            session_dir = next(item for item in Path(tmpdir).iterdir() if item.is_dir())
            application_text = (session_dir / "application.log").read_text(encoding="utf-8")
            event_text = (session_dir / "events.jsonl").read_text(encoding="utf-8")
            self.assertNotIn(secret, application_text)
            self.assertNotIn(secret, event_text)
            self.assertIn(ContextErrorCode.TURN_APPEND_FAILED.value, application_text)
            self.assertIn("context.conversation.persist_failed", event_text)


class _SecretFailingRepository(_Repository):
    def __init__(self, order: list[str], secret: str) -> None:
        super().__init__(order)
        self._secret = secret

    def append_turn(self, turn) -> None:
        if self.append_count == 1:
            self.order.append("append")
            self.append_count += 1
            raise ConversationRepositoryError(
                self._secret,
                code=ContextErrorCode.TURN_APPEND_FAILED,
            )
        super().append_turn(turn)


class _Responses:
    def __init__(self, response) -> None:
        self._response = response

    def create(self, **kwargs):
        return self._response


class _Client:
    def __init__(self, response) -> None:
        self.responses = _Responses(response)


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


if __name__ == "__main__":
    unittest.main()
