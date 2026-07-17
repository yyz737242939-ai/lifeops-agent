"""OpenAI-compatible and deterministic fake adapters for Context summarization."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from app.context.budget import estimate_tokens
from app.context.errors import (
    ContextContractError,
    ContextErrorCode,
    ContextProviderError,
)
from app.context.models import (
    ContextBudget,
    ContextSummaryOutput,
    ConversationSummary,
    ConversationTurn,
)
from app.observability.logger import LlmInteractionSink


CONTEXT_SUMMARY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"summary": {"type": "string", "minLength": 1}},
    "required": ["summary"],
}

CONTEXT_SUMMARY_SYSTEM_PROMPT = """You summarize visible LifeOps conversation history.
Use only the supplied previous summary and contiguous visible turns.
Preserve user decisions, constraints, unresolved questions, and relevant references.
Do not invent facts, private reasoning, Tool observations, permissions, or long-term Memory.
Return only the strict structured summary response requested by the schema."""


class FakeContextSummarizer:
    """Deterministic queue-backed fake that records exact typed calls."""

    def __init__(self, outputs: Iterable[ContextSummaryOutput]) -> None:
        self._outputs = list(outputs)
        if any(not isinstance(item, ContextSummaryOutput) for item in self._outputs):
            raise ValueError("outputs must contain ContextSummaryOutput values.")
        self.calls: list[
            tuple[
                ConversationSummary | None,
                tuple[ConversationTurn, ...],
                ContextBudget,
                LlmInteractionSink | None,
            ]
        ] = []

    def summarize(
        self,
        previous_summary: ConversationSummary | None,
        contiguous_turns: tuple[ConversationTurn, ...],
        budget: ContextBudget,
        *,
        llm_log: LlmInteractionSink | None = None,
    ) -> ContextSummaryOutput:
        _validate_summary_input(previous_summary, contiguous_turns, budget)
        self.calls.append((previous_summary, contiguous_turns, budget, llm_log))
        if not self._outputs:
            raise ContextProviderError(
                "The fake Context summarizer has no remaining output.",
                code=ContextErrorCode.SUMMARY_PROVIDER_FAILED,
            )
        output = self._outputs.pop(0)
        _validate_summary_size(output, budget)
        return output


class OpenAIContextSummarizer:
    """Production OpenAI-compatible adapter for one incremental summary call."""

    def __init__(self, *, client: Any | None = None, model: str | None = None) -> None:
        if client is None:
            load_dotenv()
            api_key = os.getenv("OPENROUTER_API_KEY")
            base_url = os.getenv("OPENROUTER_BASE_URL")
            model = model or os.getenv("MODEL", "deepseek/deepseek-v4-flash")
            if not api_key or not base_url or not model:
                raise ContextProviderError(
                    "Context summarizer model configuration is incomplete.",
                    code=ContextErrorCode.SUMMARY_PROVIDER_FAILED,
                )
            client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=30,
                max_retries=0,
            )
        if not model:
            raise ContextProviderError(
                "Context summarizer model is missing.",
                code=ContextErrorCode.SUMMARY_PROVIDER_FAILED,
            )
        self._client = client
        self._model = model

    def summarize(
        self,
        previous_summary: ConversationSummary | None,
        contiguous_turns: tuple[ConversationTurn, ...],
        budget: ContextBudget,
        *,
        llm_log: LlmInteractionSink | None = None,
    ) -> ContextSummaryOutput:
        _validate_summary_input(previous_summary, contiguous_turns, budget)
        request = {
            "model": self._model,
            "instructions": CONTEXT_SUMMARY_SYSTEM_PROMPT,
            "input": json.dumps(
                _summary_payload(previous_summary, contiguous_turns),
                ensure_ascii=False,
                sort_keys=True,
            ),
            "max_output_tokens": budget.max_summary_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "context_summary",
                    "strict": True,
                    "schema": CONTEXT_SUMMARY_SCHEMA,
                }
            },
        }
        try:
            response = self._client.responses.create(**request)
        except Exception as exc:
            _record_llm(
                llm_log,
                self._model,
                request,
                None,
                status="failed",
                error_code=ContextErrorCode.SUMMARY_PROVIDER_FAILED.value,
            )
            raise ContextProviderError(
                "Context summary provider request failed.",
                code=ContextErrorCode.SUMMARY_PROVIDER_FAILED,
            ) from exc
        response_payload = {"output_text": getattr(response, "output_text", "")}
        try:
            output = parse_context_summary(
                response_payload["output_text"],
                model=self._model,
                budget=budget,
            )
        except ContextContractError as exc:
            _record_llm(
                llm_log,
                self._model,
                request,
                response_payload,
                status="failed",
                error_code=exc.code,
            )
            raise
        _record_llm(llm_log, self._model, request, response_payload)
        return output


def parse_context_summary(
    output_text: object,
    *,
    model: str,
    budget: ContextBudget,
) -> ContextSummaryOutput:
    if not isinstance(model, str) or not model.strip():
        raise ValueError("model must be a non-empty string.")
    if not isinstance(budget, ContextBudget):
        raise ValueError("budget must be a ContextBudget.")
    if not isinstance(output_text, str) or not output_text.strip():
        raise _invalid_summary()
    try:
        payload = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise _invalid_summary() from exc
    if not isinstance(payload, dict) or set(payload) != {"summary"}:
        raise _invalid_summary()
    content = payload["summary"]
    try:
        output = ContextSummaryOutput(
            content=content,
            provider="openai-compatible",
            model=model,
        )
    except ValueError as exc:
        raise _invalid_summary() from exc
    _validate_summary_size(output, budget)
    return output


def _validate_summary_input(
    previous_summary: ConversationSummary | None,
    contiguous_turns: tuple[ConversationTurn, ...],
    budget: ContextBudget,
) -> None:
    if previous_summary is not None and not isinstance(
        previous_summary, ConversationSummary
    ):
        raise _invalid_summary()
    if not isinstance(contiguous_turns, tuple) or not contiguous_turns or any(
        not isinstance(item, ConversationTurn) for item in contiguous_turns
    ):
        raise _invalid_summary()
    if not isinstance(budget, ContextBudget) or budget.max_summary_tokens < 1:
        raise _invalid_summary()
    first = contiguous_turns[0]
    expected_start = (
        previous_summary.covered_end_sequence + 1
        if previous_summary is not None
        else 1
    )
    if first.sequence != expected_start:
        raise _invalid_summary()
    expected_sequences = tuple(
        range(first.sequence, first.sequence + len(contiguous_turns))
    )
    if tuple(item.sequence for item in contiguous_turns) != expected_sequences:
        raise _invalid_summary()
    if any(item.session_id != first.session_id for item in contiguous_turns):
        raise _invalid_summary()
    if previous_summary is not None and previous_summary.session_id != first.session_id:
        raise _invalid_summary()
    if len({item.turn_id for item in contiguous_turns}) != len(contiguous_turns):
        raise _invalid_summary()


def _validate_summary_size(
    output: ContextSummaryOutput, budget: ContextBudget
) -> None:
    if estimate_tokens(output.content) > budget.max_summary_tokens:
        raise ContextContractError(
            "Context summary exceeds its deterministic budget.",
            code=ContextErrorCode.SUMMARY_TOO_LARGE,
        )


def _summary_payload(
    previous_summary: ConversationSummary | None,
    contiguous_turns: tuple[ConversationTurn, ...],
) -> dict[str, Any]:
    return {
        "previous_summary": (
            None
            if previous_summary is None
            else {
                "version": previous_summary.version,
                "covered_start_sequence": previous_summary.covered_start_sequence,
                "covered_end_sequence": previous_summary.covered_end_sequence,
                "content": previous_summary.content,
            }
        ),
        "contiguous_turns": [
            {
                "sequence": turn.sequence,
                "role": turn.role.value,
                "kind": turn.kind.value,
                "content": turn.content,
            }
            for turn in contiguous_turns
        ],
    }


def _invalid_summary() -> ContextContractError:
    return ContextContractError(
        "Context summary input or output is invalid.",
        code=ContextErrorCode.SUMMARY_INVALID,
    )


def _record_llm(
    sink: LlmInteractionSink | None,
    model: str,
    request: dict[str, Any],
    response: dict[str, Any] | None,
    *,
    status: str = "ok",
    error_code: str | None = None,
) -> None:
    if sink is None:
        return
    try:
        sink.record(
            provider="openai-compatible",
            model=model,
            request=request,
            response=response,
            status=status,
            error_code=error_code,
        )
    except Exception:
        logging.getLogger("lifeops.llm").exception(
            "Context summary LLM interaction log failed"
        )
