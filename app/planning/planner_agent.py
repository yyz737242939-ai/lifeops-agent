"""Planner Agent for Plan and Execute v0."""

from collections.abc import Callable
import json
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.config import LLM_MAX_OUTPUT_TOKENS, LLM_MODEL, LLM_TEMPERATURE
from app.planning.plan_types import PlanRun, PlanStep
from app.planning.planner_prompt import build_planner_input
from app.utils.llm import client


PlannerOutputType = Literal[
    "plan",
    "need_user",
    "unsafe_or_needs_confirmation",
    "cannot_plan",
]

FORBIDDEN_PLANNER_STEP_KEYS = {
    "args",
    "arguments",
    "authorized",
    "function",
    "function_name",
    "parameters",
    "tool",
    "tool_args",
    "tool_arguments",
    "tool_call",
    "tool_calls",
    "tool_name",
    "write_authorized",
    "write_payload",
}


class PlannerResult(BaseModel):
    """Parsed Planner Agent result."""

    output_type: PlannerOutputType
    message: str
    plan: PlanRun | None = None
    error: str | None = None

    @field_validator("message")
    @classmethod
    def message_must_not_be_empty(cls, value: str) -> str:
        clean_value = value.strip()
        if not clean_value:
            raise ValueError("Planner result message cannot be empty")
        return clean_value

    @field_validator("error")
    @classmethod
    def optional_error_must_be_stripped(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean_value = value.strip()
        return clean_value or None


PlannerTextGenerator = Callable[[list[dict[str, str]]], str]


class PlannerAgent:
    """Generate and parse transient execution plans without executing tools."""

    def __init__(
        self,
        *,
        model: str | None = None,
        temperature: float = LLM_TEMPERATURE,
        max_output_tokens: int = LLM_MAX_OUTPUT_TOKENS,
        text_generator: PlannerTextGenerator | None = None,
    ) -> None:
        self.model = model or LLM_MODEL
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self._text_generator = text_generator

    def plan(
        self,
        *,
        goal: str,
        task_context_summary: str = "",
        recovery_context_summary: str = "",
        capability_summary: str = "",
        safety_rules: str = "",
    ) -> PlannerResult:
        messages = build_planner_input(
            goal=goal,
            task_context_summary=task_context_summary,
            recovery_context_summary=recovery_context_summary,
            capability_summary=capability_summary,
            safety_rules=safety_rules,
        )
        raw_text = self._generate_text(messages)
        return parse_planner_output(raw_text, fallback_goal=goal)

    def _generate_text(self, messages: list[dict[str, str]]) -> str:
        if self._text_generator is not None:
            return self._text_generator(messages)
        response = client.responses.create(
            model=self.model,
            input=messages,
            tools=[],
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
        )
        return str(getattr(response, "output_text", "") or "")


def parse_planner_output(raw_text: str, *, fallback_goal: str) -> PlannerResult:
    """Parse Planner JSON into a safe PlannerResult."""

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return PlannerResult(
            output_type="cannot_plan",
            message="Planner did not return valid JSON.",
            error="invalid_json",
        )

    if not isinstance(payload, dict):
        return PlannerResult(
            output_type="cannot_plan",
            message="Planner output must be a JSON object.",
            error="invalid_shape",
        )

    output_type = payload.get("type")
    message = _clean_text(payload.get("message")) or "Planner could not produce a plan."
    if output_type not in (
        "plan",
        "need_user",
        "unsafe_or_needs_confirmation",
        "cannot_plan",
    ):
        return PlannerResult(
            output_type="cannot_plan",
            message="Planner output type is invalid.",
            error="invalid_type",
        )

    if output_type != "plan":
        return PlannerResult(output_type=output_type, message=message)

    plan_payload = payload.get("plan")
    if not isinstance(plan_payload, dict):
        return PlannerResult(
            output_type="cannot_plan",
            message="Planner plan payload is missing or invalid.",
            error="invalid_plan_payload",
        )

    steps_payload = plan_payload.get("steps")
    if not isinstance(steps_payload, list) or not steps_payload:
        return PlannerResult(
            output_type="cannot_plan",
            message="Planner plan must include at least one step.",
            error="empty_steps",
        )

    forbidden_keys = _find_forbidden_step_keys(steps_payload)
    if forbidden_keys:
        return PlannerResult(
            output_type="cannot_plan",
            message="Planner output included tool arguments or write authorization.",
            error=f"forbidden_step_keys:{','.join(sorted(forbidden_keys))}",
        )

    try:
        steps = [_parse_step(step_payload) for step_payload in steps_payload]
        plan = PlanRun(
            goal=_clean_text(plan_payload.get("goal")) or fallback_goal,
            steps=steps,
            source_user_input_summary=(
                _clean_text(plan_payload.get("source_user_input_summary"))
                or fallback_goal[:200]
            ),
        )
    except (TypeError, ValueError) as exc:
        return PlannerResult(
            output_type="cannot_plan",
            message="Planner plan payload failed validation.",
            error=str(exc),
        )

    return PlannerResult(output_type="plan", message=message, plan=plan)


def _parse_step(step_payload: Any) -> PlanStep:
    if not isinstance(step_payload, dict):
        raise ValueError("Plan step must be an object")
    return PlanStep(
        title=_clean_text(step_payload.get("title")) or "",
        intent=_clean_text(step_payload.get("intent")) or "",
        requires_user_confirmation=bool(
            step_payload.get("requires_user_confirmation", False)
        ),
        risk_level=step_payload.get("risk_level", "low"),
        expected_tool_domain=_clean_text(step_payload.get("expected_tool_domain")),
    )


def _find_forbidden_step_keys(steps_payload: list[Any]) -> set[str]:
    found: set[str] = set()
    for step_payload in steps_payload:
        if not isinstance(step_payload, dict):
            continue
        found.update(set(step_payload) & FORBIDDEN_PLANNER_STEP_KEYS)
    return found


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
