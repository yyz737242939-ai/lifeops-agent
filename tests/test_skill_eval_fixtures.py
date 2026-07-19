from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from app.runtime.models import RuntimeRequest
from app.skills.errors import SkillSelectionError
from app.skills.models import SkillDefinition
from app.skills.selector import select_skills


FIXTURE_ROOT = Path("tests/fixtures/skills")


class SkillEvalFixturesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.metadata = (
            SkillDefinition("research", "Research sources.", Path("research")),
            SkillDefinition("travel", "Plan travel.", Path("travel")),
        )

    def test_selection_fixture_shape_is_stable_and_executable(self) -> None:
        fixture = self._read("selection_cases.json")

        self.assertEqual(fixture["schema_version"], 1)
        case_ids = [case["case_id"] for case in fixture["cases"]]
        self.assertEqual(len(case_ids), len(set(case_ids)))
        for case in fixture["cases"]:
            with self.subTest(case_id=case["case_id"]):
                result = select_skills(
                    RuntimeRequest(
                        user_input=case["user_input"],
                        session_id="eval_session",
                    ),
                    self.metadata,
                    FixtureSelectionClient(case["expected_skill_ids"]),
                )
                self.assertEqual(
                    list(result.selected_skill_ids),
                    case["expected_skill_ids"],
                )

    def test_invalid_output_fixtures_keep_expected_error_contract(self) -> None:
        fixture = self._read("invalid_selection_cases.json")

        self.assertEqual(fixture["schema_version"], 1)
        for case in fixture["cases"]:
            with self.subTest(case_id=case["case_id"]):
                with self.assertRaises(SkillSelectionError) as caught:
                    select_skills(
                        RuntimeRequest(
                            user_input="fixture request",
                            session_id="eval_session",
                        ),
                        self.metadata,
                        StaticOutputClient(case["output"]),
                    )
                self.assertEqual(caught.exception.code, case["expected_error_code"])

    @staticmethod
    def _read(name: str) -> dict[str, Any]:
        return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


class FixtureSelectionClient:
    def __init__(self, selected_ids: list[str]) -> None:
        self._selected_ids = selected_ids

    def select(
        self,
        request: RuntimeRequest,
        skill_metadata: tuple[SkillDefinition, ...],
    ) -> dict[str, Any]:
        return {"selected_skill_ids": self._selected_ids, "reason": "Fixture expectation."}


class StaticOutputClient:
    def __init__(self, output: dict[str, Any]) -> None:
        self._output = output

    def select(
        self,
        request: RuntimeRequest,
        skill_metadata: tuple[SkillDefinition, ...],
    ) -> dict[str, Any]:
        return self._output


if __name__ == "__main__":
    unittest.main()
