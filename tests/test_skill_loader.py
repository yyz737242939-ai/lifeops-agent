import tempfile
import unittest
from pathlib import Path

from app.skills.skill_loader import discover_skills, load_skill


class SkillLoaderTests(unittest.TestCase):
    def test_discovers_metadata_and_loads_body_separately(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_dir = Path(temp_dir) / "example"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\nname: example\ndescription: Example skill.\n---\n\n# Body\n",
                encoding="utf-8",
            )

            skills = discover_skills(Path(temp_dir))

            self.assertEqual(list(skills), ["example"])
            self.assertEqual(skills["example"].description, "Example skill.")
            self.assertEqual(load_skill(skills["example"]).instructions, "# Body")

    def test_rejects_fields_outside_name_and_description(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_dir = Path(temp_dir) / "example"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\nname: example\ndescription: Example.\nkeywords: bad\n---\nBody\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "unsupported frontmatter"):
                discover_skills(Path(temp_dir))


if __name__ == "__main__":
    unittest.main()
