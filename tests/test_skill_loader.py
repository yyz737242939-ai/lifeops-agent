from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.skills.errors import SkillDiscoveryError, SkillMetadataError
from app.skills.loader import discover_skills


class SkillDiscoveryTest(unittest.TestCase):
    def _write_skill(self, root: Path, directory: str, content: str) -> None:
        skill_dir = root / directory
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

    def test_discovers_only_metadata_from_direct_skill_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_skill(
                root,
                "research",
                "---\nname: research\ndescription: Research trusted sources.\n---\nSECRET BODY",
            )
            (root / "not-a-skill").mkdir()

            definitions = discover_skills(root)

        self.assertEqual(len(definitions), 1)
        self.assertEqual(definitions[0].skill_id, "research")
        self.assertEqual(definitions[0].description, "Research trusted sources.")
        self.assertFalse(hasattr(definitions[0], "body"))

    def test_project_skill_skeletons_are_discoverable(self) -> None:
        definitions = discover_skills(Path("app/skills"))

        self.assertEqual(
            tuple(definition.skill_id for definition in definitions),
            ("memory", "research", "travel"),
        )
        descriptions = {definition.skill_id: definition.description for definition in definitions}
        self.assertIn("Hugging Face", descriptions["research"])
        self.assertIn("itinerary", descriptions["travel"])

    def test_supports_folded_description_in_compatible_subset(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_skill(
                root,
                "travel",
                "---\nname: travel\ndescription: >-\n  Compare travel options and\n  prepare itineraries.\n---\n# Travel",
            )

            definition = discover_skills(root)[0]

        self.assertEqual(
            definition.description,
            "Compare travel options and prepare itineraries.",
        )

    def test_rejects_missing_required_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_skill(root, "research", "---\nname: research\n---\nBody")

            with self.assertRaises(SkillMetadataError) as caught:
                discover_skills(root)

        self.assertEqual(caught.exception.code, "skill_metadata_missing_fields")
        self.assertEqual(caught.exception.details["missing_fields"], ["description"])

    def test_rejects_unknown_optional_field_in_lifeops_subset(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_skill(
                root,
                "research",
                "---\nname: research\ndescription: Research sources.\nlicense: MIT\n---\nBody",
            )

            with self.assertRaises(SkillMetadataError) as caught:
                discover_skills(root)

        self.assertEqual(caught.exception.code, "skill_frontmatter_unknown_field")
        self.assertEqual(caught.exception.details["field"], "license")

    def test_rejects_directory_name_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_skill(
                root,
                "research",
                "---\nname: travel\ndescription: Travel planning.\n---\nBody",
            )

            with self.assertRaises(SkillMetadataError) as caught:
                discover_skills(root)

        self.assertEqual(caught.exception.code, "skill_metadata_name_mismatch")

    def test_rejects_invalid_agent_skills_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_skill(
                root,
                "Bad_Name",
                "---\nname: Bad_Name\ndescription: Invalid name.\n---\nBody",
            )

            with self.assertRaises(SkillMetadataError) as caught:
                discover_skills(root)

        self.assertEqual(caught.exception.code, "skill_metadata_invalid_value")

    def test_reports_missing_skill_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "missing"

            with self.assertRaises(SkillDiscoveryError) as caught:
                discover_skills(missing)

        self.assertEqual(caught.exception.code, "skill_root_not_found")


if __name__ == "__main__":
    unittest.main()
