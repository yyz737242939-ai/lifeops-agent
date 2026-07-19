from __future__ import annotations

import hashlib
import inspect
import os
import tempfile
import unittest
from pathlib import Path

from app.context.errors import ContextErrorCode, ContextProviderError
from app.context.models import ContextContributionKind
from app.memory.profile import PROFILE_FILENAME, FileProfileProvider


class FileProfileProviderTest(unittest.TestCase):
    def test_missing_or_blank_fixed_profile_degrades_to_empty_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "memory"
            provider = FileProfileProvider(root)

            self.assertIsNone(provider.load_profile())
            self.assertFalse(root.exists())

            root.mkdir()
            path = root / PROFILE_FILENAME
            path.write_text(" \n\t", encoding="utf-8")
            self.assertIsNone(provider.load_profile())
            self.assertEqual(path.read_text(encoding="utf-8"), " \n\t")

    def test_valid_utf8_profile_returns_typed_content_hash_and_fixed_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "memory"
            root.mkdir()
            content = "# 我的 Profile\n\n- 偏好步行。\n"
            path = root / PROFILE_FILENAME
            path.write_text(content, encoding="utf-8")
            provider = FileProfileProvider(root)

            contribution = provider.load_profile()

            self.assertIsNotNone(contribution)
            self.assertEqual(contribution.kind, ContextContributionKind.PROFILE)
            self.assertEqual(contribution.source, "profile")
            self.assertEqual(contribution.content, content)
            self.assertEqual(contribution.provenance.reference, "profile://profile.md")
            self.assertEqual(
                dict(contribution.provenance.attributes),
                {
                    "relative_path": PROFILE_FILENAME,
                    "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                },
            )
            self.assertEqual(path.read_text(encoding="utf-8"), content)

    def test_invalid_utf8_or_non_file_fails_with_safe_profile_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "memory"
            root.mkdir()
            path = root / PROFILE_FILENAME
            path.write_bytes(b"\xffsecret-invalid-profile")

            with self.assertRaises(ContextProviderError) as caught:
                FileProfileProvider(root).load_profile()
            self.assertEqual(
                caught.exception.code,
                ContextErrorCode.PROFILE_PROVIDER_FAILED.value,
            )
            self.assertNotIn("secret", str(caught.exception))

            path.unlink()
            path.mkdir()
            with self.assertRaises(ContextProviderError) as non_file:
                FileProfileProvider(root).load_profile()
            self.assertEqual(
                non_file.exception.code,
                ContextErrorCode.PROFILE_PROVIDER_FAILED.value,
            )

    def test_fixed_path_has_no_caller_path_or_write_surface(self) -> None:
        parameters = tuple(inspect.signature(FileProfileProvider.load_profile).parameters)
        self.assertEqual(parameters, ("self",))
        self.assertEqual(PROFILE_FILENAME, "profile.md")
        self.assertFalse(hasattr(FileProfileProvider, "save_profile"))
        self.assertFalse(hasattr(FileProfileProvider, "write_profile"))

    def test_symlinked_profile_cannot_escape_memory_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "memory"
            root.mkdir()
            outside = base / "outside.md"
            outside.write_text("secret outside", encoding="utf-8")
            try:
                os.symlink(outside, root / PROFILE_FILENAME)
            except OSError as exc:
                self.skipTest(f"symlink creation is unavailable: {exc.__class__.__name__}")

            with self.assertRaises(ContextProviderError) as caught:
                FileProfileProvider(root).load_profile()
            self.assertEqual(
                caught.exception.code,
                ContextErrorCode.PROFILE_PROVIDER_FAILED.value,
            )


if __name__ == "__main__":
    unittest.main()
