from __future__ import annotations

import unittest
from pathlib import Path

from app.skills.errors import SkillNotFoundError, SkillRegistryError
from app.skills.models import SkillDefinition
from app.skills.registry import SkillRegistry


def _definition(skill_id: str) -> SkillDefinition:
    return SkillDefinition(skill_id, f"{skill_id} description", Path("app/skills") / skill_id)


class SkillRegistryTest(unittest.TestCase):
    def test_registry_lists_definitions_in_stable_order(self) -> None:
        registry = SkillRegistry([_definition("travel"), _definition("research")])

        self.assertEqual(
            tuple(item.skill_id for item in registry.list_definitions()),
            ("research", "travel"),
        )
        self.assertEqual(registry.get("travel").skill_id, "travel")
        self.assertTrue(registry.contains("research"))

    def test_registry_rejects_duplicate_skill_ids(self) -> None:
        with self.assertRaises(SkillRegistryError) as caught:
            SkillRegistry([_definition("research"), _definition("research")])

        self.assertEqual(caught.exception.code, "skill_registry_duplicate_id")
        self.assertEqual(caught.exception.details, {"skill_id": "research"})

    def test_registry_reports_unknown_skill_id(self) -> None:
        with self.assertRaises(SkillNotFoundError) as caught:
            SkillRegistry().get("missing")

        self.assertEqual(caught.exception.code, "skill_not_found")
        self.assertEqual(caught.exception.details, {"skill_id": "missing"})


if __name__ == "__main__":
    unittest.main()
