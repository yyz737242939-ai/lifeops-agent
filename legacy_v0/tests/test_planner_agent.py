import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.config import LLM_MAX_OUTPUT_TOKENS, LLM_MODEL, LLM_TEMPERATURE
from app.planning.planner_agent import PlannerAgent, parse_planner_output


class PlannerAgentTests(unittest.TestCase):
    @patch("app.planning.planner_agent.client.responses.create")
    def test_default_llm_call_uses_repo_config(self, create_response) -> None:
        create_response.return_value = SimpleNamespace(
            output_text=json.dumps(
                {
                    "type": "need_user",
                    "message": "Please clarify the scope.",
                }
            )
        )
        agent = PlannerAgent()

        result = agent.plan(goal="Plan this.")

        self.assertEqual(result.output_type, "need_user")
        request_kwargs = create_response.call_args.kwargs
        self.assertEqual(request_kwargs["model"], LLM_MODEL)
        self.assertEqual(request_kwargs["temperature"], LLM_TEMPERATURE)
        self.assertEqual(request_kwargs["max_output_tokens"], LLM_MAX_OUTPUT_TOKENS)
        self.assertEqual(request_kwargs["tools"], [])

    def test_multi_step_goal_generates_valid_plan(self) -> None:
        agent = PlannerAgent(
            text_generator=lambda _messages: json.dumps(
                {
                    "type": "plan",
                    "message": "Review this plan before execution.",
                    "plan": {
                        "goal": "Implement the next Plan and Execute step.",
                        "source_user_input_summary": "Continue to Step 2.",
                        "steps": [
                            {
                                "title": "Read plan scope",
                                "intent": "Confirm the Planner Agent boundary.",
                                "expected_tool_domain": "files",
                            },
                            {
                                "title": "Add planner parser",
                                "intent": "Create safe structured plan parsing.",
                            },
                        ],
                    },
                }
            )
        )

        result = agent.plan(goal="Continue to Step 2.")

        self.assertEqual(result.output_type, "plan")
        self.assertIsNotNone(result.plan)
        assert result.plan is not None
        self.assertEqual(len(result.plan.steps), 2)
        self.assertEqual(result.plan.status, "pending_confirmation")
        self.assertEqual(result.plan.steps[0].expected_tool_domain, "files")

    def test_empty_steps_are_rejected(self) -> None:
        result = parse_planner_output(
            json.dumps(
                {
                    "type": "plan",
                    "message": "No steps.",
                    "plan": {
                        "goal": "Do something.",
                        "source_user_input_summary": "Do something.",
                        "steps": [],
                    },
                }
            ),
            fallback_goal="Do something.",
        )

        self.assertEqual(result.output_type, "cannot_plan")
        self.assertEqual(result.error, "empty_steps")
        self.assertIsNone(result.plan)

    def test_non_json_output_falls_back_to_cannot_plan(self) -> None:
        result = parse_planner_output("First I would think out loud.", fallback_goal="Goal")

        self.assertEqual(result.output_type, "cannot_plan")
        self.assertEqual(result.error, "invalid_json")
        self.assertIsNone(result.plan)

    def test_markdown_fenced_json_is_accepted(self) -> None:
        result = parse_planner_output(
            """```json
{
  "type": "plan",
  "message": "Review this plan.",
  "plan": {
    "goal": "Review todos.",
    "source_user_input_summary": "Review todos.",
    "steps": [
      {"title": "List todos", "intent": "Inspect the current todo list."}
    ]
  }
}
```""",
            fallback_goal="Review todos.",
        )

        self.assertEqual(result.output_type, "plan")
        self.assertIsNotNone(result.plan)
        assert result.plan is not None
        self.assertEqual(result.plan.steps[0].title, "List todos")

    def test_need_user_reason_is_used_as_message(self) -> None:
        result = parse_planner_output(
            json.dumps(
                {
                    "type": "need_user",
                    "reason": "Missing scope.",
                    "clarifying_questions": ["Which todo list?"],
                }
            ),
            fallback_goal="Review todos.",
        )

        self.assertEqual(result.output_type, "need_user")
        self.assertIn("Missing scope", result.message)
        self.assertIn("Which todo list", result.message)

    def test_planner_rejects_tool_call_arguments(self) -> None:
        result = parse_planner_output(
            json.dumps(
                {
                    "type": "plan",
                    "message": "Includes forbidden args.",
                    "plan": {
                        "goal": "Update a task.",
                        "source_user_input_summary": "Update a task.",
                        "steps": [
                            {
                                "title": "Call update_task_status",
                                "intent": "Update a task.",
                                "tool_name": "update_task_status",
                                "arguments": {"task_id": "task_1"},
                            }
                        ],
                    },
                }
            ),
            fallback_goal="Update a task.",
        )

        self.assertEqual(result.output_type, "cannot_plan")
        self.assertIn("forbidden_step_keys", result.error or "")
        self.assertIsNone(result.plan)

    def test_risky_step_can_mark_risk_but_not_authorize_write(self) -> None:
        safe_risk_result = parse_planner_output(
            json.dumps(
                {
                    "type": "plan",
                    "message": "Risk must be confirmed.",
                    "plan": {
                        "goal": "Delete obsolete tasks.",
                        "source_user_input_summary": "Delete tasks.",
                        "steps": [
                            {
                                "title": "Confirm deletion scope",
                                "intent": "Ask the user to confirm the exact deletion scope.",
                                "risk_level": "high",
                                "requires_user_confirmation": True,
                            }
                        ],
                    },
                }
            ),
            fallback_goal="Delete tasks.",
        )

        self.assertEqual(safe_risk_result.output_type, "plan")
        self.assertIsNotNone(safe_risk_result.plan)
        assert safe_risk_result.plan is not None
        self.assertEqual(safe_risk_result.plan.steps[0].risk_level, "high")
        self.assertTrue(safe_risk_result.plan.steps[0].requires_user_confirmation)

        authorized_write_result = parse_planner_output(
            json.dumps(
                {
                    "type": "plan",
                    "message": "Bad write authorization.",
                    "plan": {
                        "goal": "Delete obsolete tasks.",
                        "source_user_input_summary": "Delete tasks.",
                        "steps": [
                            {
                                "title": "Delete tasks",
                                "intent": "Delete tasks.",
                                "risk_level": "high",
                                "write_authorized": True,
                            }
                        ],
                    },
                }
            ),
            fallback_goal="Delete tasks.",
        )

        self.assertEqual(authorized_write_result.output_type, "cannot_plan")
        self.assertIn("write_authorized", authorized_write_result.error or "")


if __name__ == "__main__":
    unittest.main()
