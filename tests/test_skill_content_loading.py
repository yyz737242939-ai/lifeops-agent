from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from app.skills.errors import SkillLoadError, SkillReferenceError
from app.skills.loader import discover_skills, load_skill
from app.skills.references import read_skill_reference


class SkillContentLoadingTest(unittest.TestCase):
    def test_loads_selected_body_and_emits_only_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            definition = self._create_skill(Path(tmpdir), body="# Private instructions")
            trace = RecordingTraceSink()

            loaded = load_skill(definition, trace=trace)

        self.assertEqual(loaded.body, "# Private instructions")
        self.assertEqual(trace.events, [("skill.loaded", {"skill_id": "example"})])
        self.assertNotIn("Private instructions", str(trace.events))

    def test_rejects_empty_or_oversized_body_with_one_failure_event(self) -> None:
        for body, limit, expected_code in (
            ("", 100, "skill_body_empty"),
            ("too large", 3, "skill_body_too_large"),
        ):
            with self.subTest(expected_code=expected_code):
                with tempfile.TemporaryDirectory() as tmpdir:
                    definition = self._create_skill(Path(tmpdir), body=body)
                    trace = RecordingTraceSink()

                    with self.assertRaises(SkillLoadError) as caught:
                        load_skill(definition, trace=trace, max_chars=limit)

                self.assertEqual(caught.exception.code, expected_code)
                self.assertEqual(len(trace.events), 1)
                self.assertEqual(trace.events[0][0], "skill.load.failed")

    def test_reads_only_manifest_declared_markdown_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            definition = self._create_skill(root)
            references_dir = definition.root_path / "references"
            references_dir.mkdir()
            (references_dir / "guide.md").write_text("private reference", encoding="utf-8")
            (references_dir / "other.md").write_text("not declared", encoding="utf-8")
            (references_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "references": {
                            "guide": {
                                "path": "references/guide.md",
                                "description": "When to use the guide.",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            trace = RecordingTraceSink()

            reference = read_skill_reference(definition, "guide", trace=trace)

        self.assertEqual(reference.content, "private reference")
        self.assertEqual(reference.relative_path, "references/guide.md")
        self.assertEqual(
            trace.events,
            [
                (
                    "skill.reference.loaded",
                    {"skill_id": "example", "reference_id": "guide"},
                )
            ],
        )
        self.assertNotIn("private reference", str(trace.events))

    def test_rejects_undeclared_reference_and_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            definition = self._create_skill(root)
            references_dir = definition.root_path / "references"
            references_dir.mkdir()
            manifest = references_dir / "manifest.json"
            manifest.write_text('{"references": {}}', encoding="utf-8")

            with self.assertRaises(SkillReferenceError) as undeclared:
                read_skill_reference(definition, "secret")

            manifest.write_text(
                '{"references":{"secret":{"path":"../secret.md","description":"bad"}}}',
                encoding="utf-8",
            )
            with self.assertRaises(SkillReferenceError) as traversal:
                read_skill_reference(definition, "secret")

        self.assertEqual(undeclared.exception.code, "skill_reference_not_declared")
        self.assertEqual(traversal.exception.code, "skill_reference_forbidden")

    def test_reference_failure_trace_does_not_include_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            definition = self._create_skill(Path(tmpdir))
            trace = RecordingTraceSink()

            with self.assertRaises(SkillReferenceError):
                read_skill_reference(definition, "missing", trace=trace)

        self.assertEqual(len(trace.events), 1)
        self.assertEqual(trace.events[0][0], "skill.reference.load.failed")

    def _create_skill(self, root: Path, *, body: str = "# Body"):
        skill_dir = root / "example"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: example\ndescription: Example skill.\n---\n" + body,
            encoding="utf-8",
        )
        return discover_skills(root)[0]


class RecordingTraceSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any] | None]] = []

    def append(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        self.events.append((event_type, payload))


if __name__ == "__main__":
    unittest.main()
