from pathlib import Path
import unittest


class MemorySkeletonTests(unittest.TestCase):
    def test_memory_package_can_be_imported(self) -> None:
        import app.memory  # noqa: F401

    def test_profile_template_exists(self) -> None:
        profile_path = Path("data/memory/profile.md")

        self.assertTrue(profile_path.exists())


if __name__ == "__main__":
    unittest.main()
