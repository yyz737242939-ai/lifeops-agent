from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from app.runtime.models import RuntimeRequest
from app.skills.errors import SkillSelectionError
from app.skills.models import SkillDefinition
from app.skills.selector import select_skills


class SkillSelectorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.request = RuntimeRequest(user_input="Plan a research trip.", session_id="session_1")
        self.metadata = (
            SkillDefinition("research", "Research sources.", Path("research")),
            SkillDefinition("travel", "Plan travel.", Path("travel")),
        )

    def test_selects_zero_or_multiple_skills_using_all_metadata(self) -> None:
        client = FakeSelectionClient(
            {"selected_skill_ids": ["research", "travel"], "reason": "Needs both domains."}
        )
        trace = RecordingTraceSink()

        result = select_skills(self.request, self.metadata, client, trace=trace)

        self.assertEqual(result.selected_skill_ids, ("research", "travel"))
        self.assertEqual(tuple(item.skill_id for item in client.received_metadata), ("research", "travel"))
        self.assertEqual(
            trace.events,
            [
                (
                    "skill.selected",
                    {
                        "selected_skill_ids": ["research", "travel"],
                        "selection_count": 2,
                    },
                )
            ],
        )

    def test_allows_empty_selection_with_reason(self) -> None:
        result = select_skills(
            self.request,
            self.metadata,
            FakeSelectionClient({"selected_skill_ids": [], "reason": "No Skill applies."}),
        )

        self.assertEqual(result.selected_skill_ids, ())

    def test_rejects_unknown_and_duplicate_ids(self) -> None:
        for payload, expected_code in (
            (
                {"selected_skill_ids": ["missing"], "reason": "Bad ID."},
                "skill_selection_unknown_id",
            ),
            (
                {"selected_skill_ids": ["research", "research"], "reason": "Duplicate."},
                "skill_selection_duplicate_id",
            ),
        ):
            with self.subTest(expected_code=expected_code):
                with self.assertRaises(SkillSelectionError) as caught:
                    select_skills(self.request, self.metadata, FakeSelectionClient(payload))
                self.assertEqual(caught.exception.code, expected_code)

    def test_rejects_extra_output_fields_and_emits_one_safe_failure_event(self) -> None:
        trace = RecordingTraceSink()

        with self.assertRaises(SkillSelectionError):
            select_skills(
                self.request,
                self.metadata,
                FakeSelectionClient(
                    {
                        "selected_skill_ids": ["research"],
                        "reason": "Research request.",
                        "user_input": self.request.user_input,
                    }
                ),
                trace=trace,
            )

        self.assertEqual(len(trace.events), 1)
        event_type, payload = trace.events[0]
        self.assertEqual(event_type, "skill.selection.failed")
        self.assertNotIn("user_input", payload)
        self.assertNotIn(self.request.user_input, str(payload))

    def test_success_trace_does_not_include_model_reason(self) -> None:
        trace = RecordingTraceSink()
        sensitive_reason = f"Selected because the user said: {self.request.user_input}"

        result = select_skills(
            self.request,
            self.metadata,
            FakeSelectionClient(
                {"selected_skill_ids": ["research"], "reason": sensitive_reason}
            ),
            trace=trace,
        )

        self.assertEqual(result.reason, sensitive_reason)
        self.assertNotIn(sensitive_reason, str(trace.events))
        self.assertNotIn(self.request.user_input, str(trace.events))

    def test_wraps_model_failure(self) -> None:
        trace = RecordingTraceSink()

        with self.assertRaises(SkillSelectionError) as caught:
            select_skills(self.request, self.metadata, FailingSelectionClient(), trace=trace)

        self.assertEqual(caught.exception.code, "skill_selection_model_failed")
        self.assertEqual(trace.events[0][0], "skill.selection.failed")


class FakeSelectionClient:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.received_metadata: tuple[SkillDefinition, ...] = ()

    def select(
        self,
        request: RuntimeRequest,
        skill_metadata: tuple[SkillDefinition, ...],
    ) -> dict[str, Any]:
        self.received_metadata = skill_metadata
        return self.response


class FailingSelectionClient:
    def select(
        self,
        request: RuntimeRequest,
        skill_metadata: tuple[SkillDefinition, ...],
    ) -> dict[str, Any]:
        raise RuntimeError("provider unavailable with sensitive raw output")


class RecordingTraceSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any] | None]] = []

    def append(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        self.events.append((event_type, payload))


if __name__ == "__main__":
    unittest.main()
