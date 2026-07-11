from __future__ import annotations

import unittest
from pathlib import Path

from app.skills.models import (
    LoadedSkill,
    PromptContribution,
    SkillPreparation,
    SkillDefinition,
    SkillReferenceDefinition,
    SkillSelection,
)


class SkillModelsTest(unittest.TestCase):
    def test_skill_definition_keeps_startup_metadata_only(self) -> None:
        reference = SkillReferenceDefinition("ranking", "references/ranking.md")
        definition = SkillDefinition(
            skill_id="research",
            description="Research and compare sources.",
            root_path=Path("app/skills/research"),
            capability_hints=("research.sources.read",),
            references=(reference,),
        )

        self.assertEqual(definition.skill_id, "research")
        self.assertEqual(definition.references, (reference,))
        self.assertFalse(hasattr(definition, "body"))

    def test_loaded_skill_requires_non_empty_body(self) -> None:
        definition = SkillDefinition("research", "Research sources.", Path("research"))

        with self.assertRaises(ValueError):
            LoadedSkill(definition=definition, body=" ")

    def test_selection_supports_zero_or_multiple_skills(self) -> None:
        self.assertEqual(SkillSelection().selected_skill_ids, ())
        selection = SkillSelection(("research", "travel"), reason="Cross-domain request.")
        self.assertEqual(selection.selected_skill_ids, ("research", "travel"))

    def test_selection_rejects_duplicate_ids(self) -> None:
        with self.assertRaises(ValueError):
            SkillSelection(("research", "research"))

    def test_prompt_contribution_validates_capability_hints(self) -> None:
        with self.assertRaises(ValueError):
            PromptContribution("research", "Use trusted sources.", ("source.read", "source.read"))

    def test_skill_preparation_requires_contributions_to_match_loaded_ids(self) -> None:
        with self.assertRaises(ValueError):
            SkillPreparation(
                selection=SkillSelection(("research",), reason="Research request."),
                loaded_skill_ids=("research",),
                prompt_contributions=(
                    PromptContribution("travel", "Travel instructions."),
                ),
            )


if __name__ == "__main__":
    unittest.main()
