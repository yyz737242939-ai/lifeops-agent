from __future__ import annotations

import unittest
from pathlib import Path

from app.skills.errors import SkillPromptError
from app.skills.models import LoadedSkill, SkillDefinition
from app.skills.prompt_assembler import build_prompt_contributions


class SkillPromptAssemblerTest(unittest.TestCase):
    def test_builds_contributions_in_selected_load_order(self) -> None:
        travel = self._loaded_skill(
            "travel",
            "Travel instructions.",
            ("travel.options.read",),
        )
        research = self._loaded_skill(
            "research",
            "Research instructions.",
            ("research.sources.read", "research.brief.build"),
        )

        contributions = build_prompt_contributions([travel, research])

        self.assertEqual(
            tuple(item.skill_id for item in contributions),
            ("travel", "research"),
        )
        self.assertEqual(contributions[0].instructions, "Travel instructions.")
        self.assertEqual(
            contributions[1].capability_hints,
            ("research.sources.read", "research.brief.build"),
        )

    def test_empty_loaded_skills_produces_no_contributions(self) -> None:
        self.assertEqual(build_prompt_contributions([]), [])

    def test_does_not_include_metadata_for_unloaded_skills(self) -> None:
        research = self._loaded_skill("research", "Research only.")

        contributions = build_prompt_contributions([research])

        self.assertEqual([item.skill_id for item in contributions], ["research"])
        self.assertNotIn("travel", str(contributions))

    def test_rejects_duplicate_loaded_skill_ids(self) -> None:
        first = self._loaded_skill("research", "First instructions.")
        second = self._loaded_skill("research", "Second instructions.")

        with self.assertRaises(SkillPromptError) as caught:
            build_prompt_contributions([first, second])

        self.assertEqual(caught.exception.code, "skill_prompt_duplicate_skill_id")

    def test_rejects_values_that_are_not_loaded_skills(self) -> None:
        with self.assertRaises(SkillPromptError) as caught:
            build_prompt_contributions(["research"])  # type: ignore[list-item]

        self.assertEqual(caught.exception.code, "skill_prompt_invalid_loaded_skills")

    @staticmethod
    def _loaded_skill(
        skill_id: str,
        body: str,
        capability_hints: tuple[str, ...] = (),
    ) -> LoadedSkill:
        definition = SkillDefinition(
            skill_id=skill_id,
            description=f"{skill_id} description",
            root_path=Path("app/skills") / skill_id,
            capability_hints=capability_hints,
        )
        return LoadedSkill(definition=definition, body=body)


if __name__ == "__main__":
    unittest.main()
