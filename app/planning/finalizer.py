"""Read-only PlanFinalizer adapter and deterministic fallback."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from app.observability.logger import LlmInteractionSink, project_llm_token_usage
from app.planning.errors import PlanContractError, PlanningError
from app.planning.models import (
    PlanFinalizerInput,
    PlanFinalizerOutput,
    PlanStepStatus,
)


FINALIZER_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "message": {"type": "string"},
        "claims_write_success": {"type": "boolean"},
        "evidence_refs": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["message", "claims_write_success", "evidence_refs"],
    "additionalProperties": False,
}

FINALIZER_SYSTEM_PROMPT = """
Summarize the supplied completed plan for the user. The input is the complete
read-only source of truth: do not infer from tools, prompts, transcripts, or
hidden context. Mention a write as successfully completed only when the output
sets claims_write_success=true and cites one or more supplied evidence_refs.
Completed read-only or temporary-result steps do not require evidence_refs;
their completed status and safe_result_summary are sufficient to report the
read-only result as completed. An empty evidence_refs list means no durable
write was evidenced, not that the read-only plan failed. Do not describe a
temporary brief as saved or written unless WRITE evidence is supplied.
Never invent evidence, tool activity, or private reasoning.
""".strip()


class FakePlanFinalizerClient:
    def __init__(self, *results: PlanFinalizerOutput | Exception) -> None:
        self._results = list(results)
        self.inputs: list[PlanFinalizerInput] = []

    def finalize(
        self,
        finalizer_input: PlanFinalizerInput,
        *,
        llm_log: LlmInteractionSink | None = None,
    ) -> PlanFinalizerOutput:
        if not isinstance(finalizer_input, PlanFinalizerInput):
            raise PlanContractError(
                "Finalizer input is invalid.", code="plan_contract_invalid"
            )
        self.inputs.append(finalizer_input)
        if not self._results:
            raise PlanningError(
                "Finalizer fake is exhausted.", code="plan_finalization_failed"
            )
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return _validate_output(result, finalizer_input)


class OpenAIPlanFinalizerClient:
    def __init__(self, *, client: Any | None = None, model: str | None = None) -> None:
        if client is None:
            load_dotenv()
            api_key = os.getenv("OPENROUTER_API_KEY")
            base_url = os.getenv("OPENROUTER_BASE_URL")
            model = model or os.getenv("MODEL", "deepseek/deepseek-v4-flash")
            if not api_key or not base_url or not model:
                raise PlanningError(
                    "Finalizer model configuration is incomplete.",
                    code="plan_finalization_failed",
                )
            client = OpenAI(
                api_key=api_key, base_url=base_url, timeout=30, max_retries=0
            )
        if not model:
            raise PlanningError(
                "Finalizer model is missing.", code="plan_finalization_failed"
            )
        self._client = client
        self._model = model

    def finalize(
        self,
        finalizer_input: PlanFinalizerInput,
        *,
        llm_log: LlmInteractionSink | None = None,
    ) -> PlanFinalizerOutput:
        if not isinstance(finalizer_input, PlanFinalizerInput):
            raise PlanContractError(
                "Finalizer input is invalid.", code="plan_contract_invalid"
            )
        request = {
            "model": self._model,
            "instructions": FINALIZER_SYSTEM_PROMPT,
            "input": json.dumps(
                _finalizer_payload(finalizer_input), ensure_ascii=False, sort_keys=True
            ),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "plan_finalization",
                    "strict": True,
                    "schema": FINALIZER_OUTPUT_SCHEMA,
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
                error_code="plan_finalization_failed",
            )
            raise PlanningError(
                "Finalizer provider request failed.",
                code="plan_finalization_failed",
            ) from exc
        response_payload = {
            "output_text": getattr(response, "output_text", ""),
            "usage": project_llm_token_usage(response),
        }
        try:
            output = parse_finalizer_output(response_payload["output_text"], finalizer_input)
        except PlanContractError as exc:
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


def parse_finalizer_output(
    output_text: object, finalizer_input: PlanFinalizerInput
) -> PlanFinalizerOutput:
    if not isinstance(output_text, str) or not output_text.strip():
        raise _invalid_output()
    try:
        payload = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise _invalid_output() from exc
    if not isinstance(payload, dict) or set(payload) != {
        "message",
        "claims_write_success",
        "evidence_refs",
    }:
        raise _invalid_output()
    if not isinstance(payload["evidence_refs"], list):
        raise _invalid_output()
    try:
        output = PlanFinalizerOutput(
            message=payload["message"],
            claims_write_success=payload["claims_write_success"],
            evidence_refs=tuple(payload["evidence_refs"]),
        )
    except (TypeError, ValueError) as exc:
        raise _invalid_output() from exc
    return _validate_output(output, finalizer_input)


def deterministic_finalizer_fallback(
    finalizer_input: PlanFinalizerInput,
) -> PlanFinalizerOutput:
    lines = ["计划执行已结束。"]
    for item in finalizer_input.step_results:
        if item.status == PlanStepStatus.COMPLETED:
            detail = item.safe_result_summary or "该步骤已完成。"
        else:
            detail = item.error_code or item.stop_reason or "该步骤未完成。"
        lines.append(f"{item.position}. {detail}")
    return PlanFinalizerOutput(message="\n".join(lines))


def _finalizer_payload(finalizer_input: PlanFinalizerInput) -> dict[str, Any]:
    return {
        "goal": finalizer_input.goal,
        "revision": finalizer_input.revision,
        "step_results": [
            {
                "step_id": item.step_id,
                "position": item.position,
                "status": item.status.value,
                "safe_result_summary": item.safe_result_summary,
                "stop_reason": item.stop_reason,
                "error_code": item.error_code,
                "evidence_refs": list(item.evidence_refs),
            }
            for item in finalizer_input.step_results
        ],
    }


def _validate_output(
    output: PlanFinalizerOutput, finalizer_input: PlanFinalizerInput
) -> PlanFinalizerOutput:
    if not isinstance(output, PlanFinalizerOutput):
        raise _invalid_output()
    supplied_evidence = {
        ref for item in finalizer_input.step_results for ref in item.evidence_refs
    }
    if not set(output.evidence_refs) <= supplied_evidence:
        raise _invalid_output()
    if output.claims_write_success and not output.evidence_refs:
        raise _invalid_output()
    return output


def _invalid_output() -> PlanContractError:
    return PlanContractError(
        "Finalizer response is invalid.", code="plan_finalization_failed"
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
            "plan finalizer LLM interaction log failed"
        )
