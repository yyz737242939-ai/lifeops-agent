from pathlib import Path
import tempfile
import unittest

from app.memory.profile_loader import ProfileLoader


class ProfileLoaderTests(unittest.TestCase):
    def test_loads_existing_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile_path = Path(directory) / "profile.md"
            profile_path.write_text("用户偏好中文解释。", encoding="utf-8")

            profile = ProfileLoader(profile_path).load()

        self.assertTrue(profile.exists)
        self.assertTrue(profile.loaded)
        self.assertEqual(profile.content, "用户偏好中文解释。")
        self.assertEqual(profile.char_count, len("用户偏好中文解释。"))

    def test_missing_profile_returns_empty_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile_path = Path(directory) / "missing.md"

            profile = ProfileLoader(profile_path).load()

            self.assertFalse(profile_path.exists())

        self.assertFalse(profile.exists)
        self.assertFalse(profile.loaded)
        self.assertEqual(profile.content, "")

    def test_comment_only_template_is_not_loaded_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile_path = Path(directory) / "profile.md"
            profile_path.write_text(
                "<!--\n在这里填写长期稳定的用户画像。\n-->\n",
                encoding="utf-8",
            )

            profile = ProfileLoader(profile_path).load()

        self.assertTrue(profile.exists)
        self.assertFalse(profile.loaded)
        self.assertEqual(profile.content, "")


if __name__ == "__main__":
    unittest.main()
