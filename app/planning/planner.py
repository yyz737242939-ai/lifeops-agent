"""Deterministic fakes and OpenAI-compatible Planner adapter."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from app.observability.logger import LlmInteractionSink, project_llm_token_usage
from app.planning.errors import PlanContractError, PlanningError
from app.planning.lifecycle import validate_plan_draft
from app.planning.models import (
    PlanDraft,
    PlanDraftResult,
    PlannerInput,
    PlannerNeedUser,
    PlanningScopeRef,
    PlanningSnapshotEnvelope,
    PlanStepDraft,
    ReplanInput,
)


_FORBIDDEN_OUTPUT_FIELDS = frozenset(
    {
        "tool_name",
        "candidate_tool_names",
        "arguments",
        "write_authorized",
        "confirmed",
        "provider",
        "mcp_schema",
        "reasoning",
        "private_reasoning",
        "chain_of_thought",
    }
)

PLANNER_OUTPUT_SCHEMA = {
    "type": "object",
    "oneOf": [
        {
            "properties": {
                "result_type": {"type": "string", "const": "plan"},
                "steps": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "step_id": {"type": "string"},
                            "position": {"type": "integer"},
                            "objective": {"type": "string"},
                            "expected_outcome": {"type": "string"},
                            "dependency_step_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": [
                            "step_id",
                            "position",
                            "objective",
                            "expected_outcome",
                            "dependency_step_ids",
                        ],
                        "additionalProperties": False,
                    },
                },
                "question": {"type": "null"},
            },
            "required": ["result_type", "steps", "question"],
            "additionalProperties": False,
        },
        {
            "properties": {
                "result_type": {"type": "string", "const": "need_user"},
                "steps": {"type": "array", "maxItems": 0},
                "question": {"type": "string"},
            },
            "required": ["result_type", "steps", "question"],
            "additionalProperties": False,
        },
    ],
}

PLANNER_SYSTEM_PROMPT = """
Create a complete, bounded execution plan for the supplied LifeOps goal, or
ask one clarification question when safe planning is impossible.

The two output shapes are mutually exclusive. For a feasible goal, return
result_type="plan", one or more complete steps, and question=null. Return
result_type="need_user", steps=[], and one concrete question only when a
specific missing fact makes a safe plan impossible. Do not ask the user to
choose between execution methods when the supplied goal is already clear.

For replan input, completed_steps are immutable achieved facts. Never include
any completed step_id in the replacement steps and never recreate work already
covered by a completed safe_result_summary. Replacement dependency_step_ids
must refer only to replacement steps, not completed step IDs; completed facts
are supplied separately by the runtime. Plan only the remaining work.

Each plan step is a small goal with a stable ID, one-based position, expected
outcome, and explicit dependencies. Do not choose tools, construct arguments,
authorize writes, include provider schemas, or expose private reasoning. Use
capability descriptions only to ensure the plan is feasible. Stable scope IDs
may come only from the supplied trusted snapshots; otherwise plan a step that
finds or creates the required scope.
""".strip()


class FakePlannerModelClient:
    def __init__(self, *results: PlanDraftResult) -> None:
        self._results = list(results)
        self.create_inputs: list[PlannerInput] = []
        self.replan_inputs: list[ReplanInput] = []

    def create_plan(
        self,
        planner_input: PlannerInput,
        *,
        llm_log: LlmInteractionSink | None = None,
    ) -> PlanDraftResult:
        if not isinstance(planner_input, PlannerInput):
            raise PlanContractError("Planner input is invalid.", code="plan_contract_invalid")
        self.create_inputs.append(planner_input)
        return self._next()

    def replan(
        self,
        replan_input: ReplanInput,
        *,
        llm_log: LlmInteractionSink | None = None,
    ) -> PlanDraftResult:
        if not isinstance(replan_input, ReplanInput):
            raise PlanContractError("Replan input is invalid.", code="plan_contract_invalid")
        self.replan_inputs.append(replan_input)
        return self._next()

    def _next(self) -> PlanDraftResult:
        if not self._results:
            raise PlanningError("Planner fake is exhausted.", code="plan_generation_failed")
        return self._results.pop(0)


class FakePlanningSnapshotProvider:
    def __init__(self, *envelopes: PlanningSnapshotEnvelope) -> None:
        self._envelopes = envelopes
        self.requests: list[tuple[PlanningScopeRef, ...]] = []

    def load(
        self, scope_refs: tuple[PlanningScopeRef, ...]
    ) -> tuple[PlanningSnapshotEnvelope, ...]:
        if not isinstance(scope_refs, tuple) or any(
            not isinstance(item, PlanningScopeRef) for item in scope_refs
        ):
            raise PlanContractError("Planning scope references are invalid.", code="plan_contract_invalid")
        self.requests.append(scope_refs)
        requested = {(item.domain, item.scope_id) for item in scope_refs}
        return tuple(
            item for item in self._envelopes if (item.domain, item.scope_id) in requested
        )


class OpenAIPlannerModelClient:
    def __init__(self, *, client: Any | None = None, model: str | None = None) -> None:
        if client is None:
            load_dotenv()
            api_key = os.getenv("OPENROUTER_API_KEY")
            base_url = os.getenv("OPENROUTER_BASE_URL")
            model = model or os.getenv("MODEL", "deepseek/deepseek-v4-flash")
            if not api_key or not base_url or not model:
                raise PlanningError(
                    "Planner model configuration is incomplete.", code="plan_generation_failed"
                )
            client = OpenAI(api_key=api_key, base_url=base_url, timeout=30, max_retries=0)
        if not model:
            raise PlanningError("Planner model is missing.", code="plan_generation_failed")
        self._client = client
        self._model = model

    def create_plan(
        self,
        planner_input: PlannerInput,
        *,
        llm_log: LlmInteractionSink | None = None,
    ) -> PlanDraftResult:
        if not isinstance(planner_input, PlannerInput):
            raise PlanContractError("Planner input is invalid.", code="plan_contract_invalid")
        return self._request("create_plan", planner_input, llm_log=llm_log)

    def replan(
        self,
        replan_input: ReplanInput,
        *,
        llm_log: LlmInteractionSink | None = None,
    ) -> PlanDraftResult:
        if not isinstance(replan_input, ReplanInput):
            raise PlanContractError("Replan input is invalid.", code="plan_contract_invalid")
        return self._request("replan", replan_input, llm_log=llm_log)

    def _request(
        self,
        operation: str,
        typed_input: PlannerInput | ReplanInput,
        *,
        llm_log: LlmInteractionSink | None,
    ) -> PlanDraftResult:
        planner_input = (
            typed_input.planner_input if isinstance(typed_input, ReplanInput) else typed_input
        )
        request = {
            "model": self._model,
            "instructions": _instructions(planner_input),
            "input": json.dumps(
                _planner_payload(operation, typed_input), ensure_ascii=False, sort_keys=True
            ),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "plan_draft",
                    "strict": True,
                    "schema": PLANNER_OUTPUT_SCHEMA,
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
                error_code="plan_generation_failed",
            )
            raise PlanningError(
                "Planner provider request failed.", code="plan_generation_failed"
            ) from exc
        response_payload = {
            "output_text": getattr(response, "output_text", ""),
            "usage": project_llm_token_usage(response),
        }
        try:
            result = parse_plan_draft(response_payload["output_text"], planner_input)
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
        return result


def parse_plan_draft(output_text: object, planner_input: PlannerInput) -> PlanDraftResult:
    if not isinstance(output_text, str) or not output_text.strip():
        raise _invalid_plan()
    try:
        payload = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise _invalid_plan() from exc
    if _contains_forbidden_field(payload):
        raise _invalid_plan()
    if not isinstance(payload, dict) or set(payload) != {"result_type", "steps", "question"}:
        raise _invalid_plan()
    if payload["result_type"] == "need_user":
        if payload["steps"] != [] or not isinstance(payload["question"], str):
            raise _invalid_plan()
        try:
            return PlannerNeedUser(payload["question"])
        except ValueError as exc:
            raise _invalid_plan() from exc
    if payload["result_type"] != "plan" or payload["question"] is not None:
        raise _invalid_plan()
    if not isinstance(payload["steps"], list):
        raise _invalid_plan()
    expected_fields = {
        "step_id",
        "position",
        "objective",
        "expected_outcome",
        "dependency_step_ids",
    }
    steps_list: list[PlanStepDraft] = []
    try:
        for item in payload["steps"]:
            if (
                not isinstance(item, dict)
                or set(item) != expected_fields
                or not isinstance(item["dependency_step_ids"], list)
            ):
                raise _invalid_plan()
            steps_list.append(
                PlanStepDraft(
                    step_id=item["step_id"],
                    position=item["position"],
                    objective=item["objective"],
                    expected_outcome=item["expected_outcome"],
                    dependency_step_ids=tuple(item["dependency_step_ids"]),
                )
            )
        steps = tuple(steps_list)
    except (KeyError, TypeError, ValueError) as exc:
        raise _invalid_plan() from exc
    try:
        draft = PlanDraft(steps)
        validate_plan_draft(draft, planner_input.limits)
    except (ValueError, PlanContractError) as exc:
        raise _invalid_plan() from exc
    return draft


def _planner_payload(
    operation: str, typed_input: PlannerInput | ReplanInput
) -> dict[str, Any]:
    planner_input = typed_input.planner_input if isinstance(typed_input, ReplanInput) else typed_input
    payload: dict[str, Any] = {
        "operation": operation,
        "goal": planner_input.goal,
        "context": [
            {
                "kind": item.kind.value,
                "source": item.source,
                "content": item.content,
            }
            for item in planner_input.context_contributions
        ],
        "capabilities": [
            {key: item[key] for key in ("name", "description", "effect") if key in item}
            for item in planner_input.tool_catalog
        ],
        "snapshots": [
            {"domain": item.domain, "scope_id": item.scope_id, "snapshot": item.snapshot}
            for item in planner_input.snapshots
        ],
        "confirmed_constraints": list(planner_input.confirmed_constraints),
        "limits": {"max_plan_steps": planner_input.limits.max_plan_steps},
    }
    if isinstance(typed_input, ReplanInput):
        payload["completed_steps"] = [
            {
                "step_id": item.step_id,
                "safe_result_summary": item.safe_result_summary,
                "evidence_refs": list(item.evidence_refs),
            }
            for item in typed_input.completed_steps
        ]
        payload["failed_step"] = {
            "step_id": typed_input.failed_step.step_id,
            "status": typed_input.failed_step.status.value,
            "stop_reason": typed_input.failed_step.stop_reason,
            "error_code": typed_input.failed_step.error_code,
        }
        payload["confirmed_constraints"] = list(typed_input.confirmed_constraints)
    return payload


def _instructions(planner_input: PlannerInput) -> str:
    if not planner_input.prompt_contributions:
        return PLANNER_SYSTEM_PROMPT
    return PLANNER_SYSTEM_PROMPT + "\n\nSelected Skill instructions:\n" + "\n\n".join(
        item.instructions for item in planner_input.prompt_contributions
    )


def _contains_forbidden_field(value: object) -> bool:
    if isinstance(value, dict):
        return bool(set(value) & _FORBIDDEN_OUTPUT_FIELDS) or any(
            _contains_forbidden_field(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_field(item) for item in value)
    return False


def _invalid_plan() -> PlanContractError:
    return PlanContractError("Planner response is invalid.", code="plan_contract_invalid")


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
        logging.getLogger("lifeops.llm").exception("planner LLM interaction log failed")
