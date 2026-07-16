"""Deterministic fake and OpenAI-compatible PlanningRouter adapters."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from app.observability.logger import LlmInteractionSink
from app.planning.errors import PlanContractError, PlanningRouteError
from app.planning.models import (
    DirectRoute,
    NeedUserRoute,
    PlanRoute,
    PlanningRouteDecision,
    PlanningRouteInput,
)


PLANNING_ROUTE_SCHEMA = {
    "type": "object",
    "oneOf": [
        {
            "properties": {
                "route": {"type": "string", "const": "direct"},
                "reason_code": {"type": "string"},
                "question": {"type": "null"},
            },
            "required": ["route", "reason_code", "question"],
            "additionalProperties": False,
        },
        {
            "properties": {
                "route": {"type": "string", "const": "plan"},
                "reason_code": {"type": "string"},
                "question": {"type": "null"},
            },
            "required": ["route", "reason_code", "question"],
            "additionalProperties": False,
        },
        {
            "properties": {
                "route": {"type": "string", "const": "need_user"},
                "reason_code": {"type": "null"},
                "question": {"type": "string"},
            },
            "required": ["route", "reason_code", "question"],
            "additionalProperties": False,
        },
    ],
}

PLANNING_ROUTE_SYSTEM_PROMPT = """
Decide only how LifeOps should execute the supplied user goal.

Return direct for one clear local goal that bounded ReAct can handle. Return
plan for multiple goals, explicit dependencies, or work that must use an
intermediate result in a later step. Return need_user only when a missing fact
prevents safe routing.

The three output shapes are mutually exclusive:
- direct: route="direct", reason_code is a short stable string, question=null.
- plan: route="plan", reason_code is a short stable string, question=null.
- need_user: route="need_user", reason_code=null, question is the clarification.
Never put an explanation or route name in question for direct or plan. Never
put a missing-details reason in reason_code for need_user.

Do not create plan steps, choose tools, construct tool arguments, authorize a
write, or expose private reasoning. Use only the supplied filtered capability
descriptions. A PLAN_REQUEST intent is a strong signal but a single keyword is
not sufficient by itself.
""".strip()


class FakePlanningRouteClient:
    """Deterministic test adapter returning decisions in supplied order."""

    def __init__(self, *decisions: PlanningRouteDecision) -> None:
        self._decisions = list(decisions)
        self.inputs: list[PlanningRouteInput] = []

    def decide(
        self,
        route_input: PlanningRouteInput,
        *,
        llm_log: LlmInteractionSink | None = None,
    ) -> PlanningRouteDecision:
        if not isinstance(route_input, PlanningRouteInput):
            raise PlanContractError("Planning route input is invalid.", code="plan_contract_invalid")
        self.inputs.append(route_input)
        if not self._decisions:
            raise PlanningRouteError("Planning route fake is exhausted.", code="planning_route_failed")
        return self._decisions.pop(0)


class OpenAIPlanningRouteClient:
    """OpenAI-compatible structured-output adapter for planning route only."""

    def __init__(self, *, client: Any | None = None, model: str | None = None) -> None:
        if client is None:
            load_dotenv()
            api_key = os.getenv("OPENROUTER_API_KEY")
            base_url = os.getenv("OPENROUTER_BASE_URL")
            model = model or os.getenv("MODEL", "deepseek/deepseek-v4-flash")
            if not api_key or not base_url or not model:
                raise PlanningRouteError(
                    "Planning route model configuration is incomplete.",
                    code="planning_route_failed",
                )
            client = OpenAI(api_key=api_key, base_url=base_url, timeout=30, max_retries=0)
        if not model:
            raise PlanningRouteError("Planning route model is missing.", code="planning_route_failed")
        self._client = client
        self._model = model

    def decide(
        self,
        route_input: PlanningRouteInput,
        *,
        llm_log: LlmInteractionSink | None = None,
    ) -> PlanningRouteDecision:
        if not isinstance(route_input, PlanningRouteInput):
            raise PlanContractError("Planning route input is invalid.", code="plan_contract_invalid")
        request = {
            "model": self._model,
            "instructions": _instructions(route_input),
            "input": json.dumps(_route_payload(route_input), ensure_ascii=False, sort_keys=True),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "planning_route",
                    "strict": True,
                    "schema": PLANNING_ROUTE_SCHEMA,
                }
            },
        }
        try:
            response = self._client.responses.create(**request)
        except Exception as exc:
            _record_llm(llm_log, self._model, request, None, status="failed", error_code="planning_route_failed")
            raise PlanningRouteError(
                "Planning route provider request failed.", code="planning_route_failed"
            ) from exc
        response_payload = {"output_text": getattr(response, "output_text", "")}
        try:
            decision = parse_planning_route(response_payload["output_text"])
        except PlanContractError as exc:
            _record_llm(llm_log, self._model, request, response_payload, status="failed", error_code=exc.code)
            raise
        _record_llm(llm_log, self._model, request, response_payload)
        return decision


def parse_planning_route(output_text: object) -> PlanningRouteDecision:
    """Parse the strict route envelope without accepting fenced or extra content."""
    if not isinstance(output_text, str) or not output_text.strip():
        raise _invalid_route()
    try:
        payload = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise _invalid_route() from exc
    if not isinstance(payload, dict) or set(payload) != {"route", "reason_code", "question"}:
        raise _invalid_route()
    route = payload["route"]
    reason = payload["reason_code"]
    question = payload["question"]
    try:
        if route == "direct" and isinstance(reason, str) and question is None:
            return DirectRoute(reason)
        if route == "plan" and isinstance(reason, str) and question is None:
            return PlanRoute(reason)
        if route == "need_user" and reason is None and isinstance(question, str):
            return NeedUserRoute(question)
    except ValueError as exc:
        raise _invalid_route() from exc
    raise _invalid_route()


def _instructions(route_input: PlanningRouteInput) -> str:
    if not route_input.prompt_contributions:
        return PLANNING_ROUTE_SYSTEM_PROMPT
    return PLANNING_ROUTE_SYSTEM_PROMPT + "\n\nSelected Skill instructions:\n" + "\n\n".join(
        item.instructions for item in route_input.prompt_contributions
    )


def _route_payload(route_input: PlanningRouteInput) -> dict[str, Any]:
    return {
        "goal": route_input.goal,
        "intent_summary": route_input.intent_summary,
        "capabilities": [
            {
                key: item[key]
                for key in ("name", "description", "effect")
                if key in item
            }
            for item in route_input.tool_catalog
        ],
        "limits": {
            "max_plan_steps": route_input.limits.max_plan_steps,
            "max_replans": route_input.limits.max_replans,
        },
    }


def _invalid_route() -> PlanContractError:
    return PlanContractError("Planning route response is invalid.", code="plan_contract_invalid")


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
        logging.getLogger("lifeops.llm").exception("planning route LLM interaction log failed")
