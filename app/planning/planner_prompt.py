"""Prompt and JSON contract for the Plan and Execute v0 Planner Agent."""

PLANNER_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "required": ["type", "message"],
    "additionalProperties": False,
    "properties": {
        "type": {
            "type": "string",
            "enum": [
                "plan",
                "need_user",
                "unsafe_or_needs_confirmation",
                "cannot_plan",
            ],
        },
        "message": {"type": "string"},
        "plan": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "properties": {
                "goal": {"type": "string"},
                "source_user_input_summary": {"type": "string"},
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "title": {"type": "string"},
                            "intent": {"type": "string"},
                            "requires_user_confirmation": {"type": "boolean"},
                            "risk_level": {
                                "type": "string",
                                "enum": ["low", "medium", "high"],
                            },
                            "expected_tool_domain": {
                                "type": ["string", "null"],
                            },
                        },
                        "required": ["title", "intent"],
                    },
                },
            },
            "required": ["goal", "source_user_input_summary", "steps"],
        },
    },
}


PLANNER_INSTRUCTIONS = """You are the Planner Agent for LifeOps Plan and Execute v0.

Your job is to create a structured transient plan for a user goal. You do not
execute the plan.

Rules:
- Return exactly one JSON object matching the planner output contract.
- Use type "plan" only when the goal can be split into concrete steps.
- Use type "need_user" when the goal is missing key objects, scope, or constraints.
- Use type "unsafe_or_needs_confirmation" when the goal or a step is high risk and
  must be confirmed before any execution.
- Use type "cannot_plan" when the request cannot be turned into a useful plan.
- For type "plan", include at least one step.
- Each step must include title and intent.
- A step may include requires_user_confirmation, risk_level, and expected_tool_domain.
- Do not include tool call arguments, function names, API parameters, file paths to
  mutate, or concrete write payloads.
- Do not claim that any step has already been completed.
- Do not authorize WRITE actions. Mark risk and confirmation needs only.
- Planner output is transient runtime state, not long-term Task State or Memory.
"""


def build_planner_input(
    *,
    goal: str,
    task_context_summary: str = "",
    recovery_context_summary: str = "",
    capability_summary: str = "",
    safety_rules: str = "",
) -> list[dict[str, str]]:
    """Build a compact planner-only message list."""

    context_parts = [
        f"User goal:\n{goal.strip()}",
        f"Task context summary:\n{task_context_summary.strip() or '(none)'}",
        f"Recovery context summary:\n{recovery_context_summary.strip() or '(none)'}",
        f"Available capability summary:\n{capability_summary.strip() or '(none)'}",
        f"Safety rules:\n{safety_rules.strip() or '(use default planner rules)'}",
    ]
    return [
        {"role": "system", "content": PLANNER_INSTRUCTIONS},
        {"role": "user", "content": "\n\n".join(context_parts)},
    ]
