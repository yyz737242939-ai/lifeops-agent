from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from app.context.errors import (
    ContextContractError,
    ContextErrorCode,
    ContextProviderError,
)
from app.context.models import (
    ContextBudget,
    ContextSummaryOutput,
    ConversationRole,
    ConversationSummary,
    ConversationTurn,
    ConversationTurnKind,
)
from app.context.summarizer import (
    CONTEXT_SUMMARY_SCHEMA,
    FakeContextSummarizer,
    OpenAIContextSummarizer,
    parse_context_summary,
)


class ContextSummarizerAdapterTest(unittest.TestCase):
    def test_fake_returns_and_records_exact_typed_values(self) -> None:
        output = ContextSummaryOutput("新的摘要。", "fake", "deterministic")
        fake = FakeContextSummarizer((output,))
        previous = _previous_summary()
        turns = (_turn(2, "turn_2", ConversationRole.USER),)
        budget = _budget()
        sink = _Sink()

        self.assertIs(
            fake.summarize(previous, turns, budget, llm_log=sink),
            output,
        )
        self.assertEqual(fake.calls, [(previous, turns, budget, sink)])
        with self.assertRaises(ContextProviderError) as caught:
            fake.summarize(previous, turns, budget)
        self.assertEqual(
            caught.exception.code,
            ContextErrorCode.SUMMARY_PROVIDER_FAILED.value,
        )

    def test_production_adapter_builds_bounded_structured_request_and_logs_it(self) -> None:
        client = _Client(
            SimpleNamespace(
                output_text=json.dumps({"summary": "用户继续实现 Context。"}, ensure_ascii=False)
            )
        )
        sink = _Sink()
        adapter = OpenAIContextSummarizer(client=client, model="test-model")

        output = adapter.summarize(
            _previous_summary(),
            (_turn(2, "turn_2", ConversationRole.USER),),
            _budget(),
            llm_log=sink,
        )

        self.assertEqual(
            output,
            ContextSummaryOutput(
                "用户继续实现 Context。",
                "openai-compatible",
                "test-model",
            ),
        )
        request = client.requests[0]
        self.assertEqual(request["max_output_tokens"], 20)
        self.assertEqual(request["text"]["format"]["schema"], CONTEXT_SUMMARY_SCHEMA)
        payload = json.loads(request["input"])
        self.assertEqual(payload["previous_summary"]["covered_end_sequence"], 1)
        self.assertEqual(payload["contiguous_turns"][0]["sequence"], 2)
        self.assertNotIn("run_id", request["input"])
        self.assertEqual(sink.records[0]["request"], request)
        self.assertEqual(sink.records[0]["status"], "ok")

    def test_provider_failure_is_safe_logged_and_fail_closed(self) -> None:
        client = _Client(error=RuntimeError("secret provider detail"))
        sink = _Sink()
        adapter = OpenAIContextSummarizer(client=client, model="test-model")

        with self.assertRaises(ContextProviderError) as caught:
            adapter.summarize(None, (_turn(1, "turn_1", ConversationRole.USER),), _budget(), llm_log=sink)

        self.assertEqual(
            caught.exception.code,
            ContextErrorCode.SUMMARY_PROVIDER_FAILED.value,
        )
        self.assertNotIn("secret", caught.exception.message)
        self.assertEqual(
            sink.records[0]["error_code"],
            ContextErrorCode.SUMMARY_PROVIDER_FAILED.value,
        )
        self.assertIsNone(sink.records[0]["response"])

    def test_invalid_or_oversized_provider_output_is_rejected_and_logged(self) -> None:
        invalid_outputs = (
            "",
            "not-json",
            json.dumps({"summary": "ok", "extra": True}),
            json.dumps({"summary": "   "}),
            json.dumps({"summary": "x" * 100}),
        )
        expected_codes = (
            ContextErrorCode.SUMMARY_INVALID,
            ContextErrorCode.SUMMARY_INVALID,
            ContextErrorCode.SUMMARY_INVALID,
            ContextErrorCode.SUMMARY_INVALID,
            ContextErrorCode.SUMMARY_TOO_LARGE,
        )
        for output_text, expected_code in zip(invalid_outputs, expected_codes, strict=True):
            sink = _Sink()
            adapter = OpenAIContextSummarizer(
                client=_Client(SimpleNamespace(output_text=output_text)),
                model="test-model",
            )
            with self.subTest(output_text=output_text), self.assertRaises(
                ContextContractError
            ) as caught:
                adapter.summarize(
                    None,
                    (_turn(1, "turn_1", ConversationRole.USER),),
                    _budget(),
                    llm_log=sink,
                )
            self.assertEqual(caught.exception.code, expected_code.value)
            self.assertEqual(sink.records[0]["error_code"], expected_code.value)

    def test_non_contiguous_or_cross_session_input_stops_before_provider(self) -> None:
        invalid_turn_groups = (
            (),
            (_turn(2, "turn_2", ConversationRole.USER),),
            (
                _turn(1, "turn_1", ConversationRole.USER),
                _turn(3, "turn_3", ConversationRole.USER),
            ),
            (
                _turn(1, "turn_1", ConversationRole.USER),
                _turn(2, "turn_2", ConversationRole.USER, session_id="other"),
            ),
        )
        for turns in invalid_turn_groups:
            client = _Client(SimpleNamespace(output_text='{"summary":"ok"}'))
            with self.subTest(turns=turns), self.assertRaises(ContextContractError):
                OpenAIContextSummarizer(client=client, model="test-model").summarize(
                    None,
                    turns,
                    _budget(),
                )
            self.assertEqual(client.requests, [])

    def test_parser_contract_is_exact(self) -> None:
        parsed = parse_context_summary(
            '{"summary":"bounded"}',
            model="test-model",
            budget=_budget(),
        )
        self.assertEqual(parsed.content, "bounded")


class _Responses:
    def __init__(self, owner: "_Client") -> None:
        self.owner = owner

    def create(self, **kwargs):
        self.owner.requests.append(kwargs)
        if self.owner.error is not None:
            raise self.owner.error
        return self.owner.queue.pop(0)


class _Client:
    def __init__(self, *responses, error: Exception | None = None) -> None:
        self.queue = list(responses)
        self.error = error
        self.requests: list[dict] = []
        self.responses = _Responses(self)


class _Sink:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def record(self, **kwargs) -> None:
        self.records.append(kwargs)


def _budget() -> ContextBudget:
    return ContextBudget(
        max_total_tokens=100,
        max_recent_turns=4,
        max_summary_tokens=20,
        max_profile_tokens=0,
        max_memory_items=0,
        max_memory_tokens=0,
        max_current_input_tokens=40,
    )


def _turn(
    sequence: int,
    turn_id: str,
    role: ConversationRole,
    *,
    session_id: str = "session_1",
) -> ConversationTurn:
    return ConversationTurn(
        schema_version=1,
        session_id=session_id,
        turn_id=turn_id,
        sequence=sequence,
        role=role,
        kind=(
            ConversationTurnKind.NATURAL_INPUT
            if role == ConversationRole.USER
            else ConversationTurnKind.FINAL_ANSWER
        ),
        content=f"visible turn {sequence}",
        run_id=f"run_{sequence}",
        created_at=f"2026-07-16T00:00:0{sequence}Z",
    )


def _previous_summary() -> ConversationSummary:
    return ConversationSummary(
        schema_version=1,
        session_id="session_1",
        summary_id="summary_1",
        version=1,
        covered_start_sequence=1,
        covered_end_sequence=1,
        content="previous",
        estimated_tokens=2,
        previous_summary_id=None,
        source_turn_ids=("turn_1",),
        provider="openai-compatible",
        model="old-model",
        created_at="2026-07-16T00:00:01Z",
    )


if __name__ == "__main__":
    unittest.main()
