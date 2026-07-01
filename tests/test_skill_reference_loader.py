import tempfile
import unittest
from pathlib import Path

from app.skills.reference_loader import SkillReferenceError, load_skill_reference


class SkillReferenceLoaderTests(unittest.TestCase):
    def test_loads_declared_news_reference(self) -> None:
        reference = load_skill_reference("news", "briefing_policy")

        self.assertEqual(reference.skill_name, "news")
        self.assertEqual(reference.ref_id, "briefing_policy")
        self.assertEqual(reference.relative_path, "references/briefing_policy.md")
        self.assertIn("Briefing Policy", reference.content)
        self.assertGreater(reference.chars, 0)

    def test_rejects_undeclared_reference(self) -> None:
        with self.assertRaisesRegex(SkillReferenceError, "not declared"):
            load_skill_reference("news", "missing")

    def test_rejects_path_traversal_in_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_dir = Path(temp_dir) / "bad"
            references_dir = skill_dir / "references"
            references_dir.mkdir(parents=True)
            (references_dir / "manifest.json").write_text(
                '{ "references": { "escape": { "path": "../outside.md" } } }',
                encoding="utf-8",
            )

            with self.assertRaises(SkillReferenceError) as context:
                load_skill_reference("bad", "escape", skills_dir=Path(temp_dir))

            self.assertEqual(context.exception.code, "skill_reference_forbidden")

    def test_rejects_non_markdown_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_dir = Path(temp_dir) / "bad"
            references_dir = skill_dir / "references"
            references_dir.mkdir(parents=True)
            (references_dir / "manifest.json").write_text(
                '{ "references": { "data": { "path": "references/data.json" } } }',
                encoding="utf-8",
            )
            (references_dir / "data.json").write_text("{}", encoding="utf-8")

            with self.assertRaises(SkillReferenceError) as context:
                load_skill_reference("bad", "data", skills_dir=Path(temp_dir))

            self.assertEqual(context.exception.code, "skill_reference_forbidden")


if __name__ == "__main__":
    unittest.main()
