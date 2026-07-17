"""Read-only adapter for the single user-managed Profile Markdown file."""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.context.budget import estimate_tokens
from app.context.errors import ContextErrorCode, ContextProviderError
from app.context.models import (
    ContextContribution,
    ContextContributionKind,
    ContextProvenance,
)


PROFILE_FILENAME = "profile.md"


class FileProfileProvider:
    """Load only ``profile.md`` below one application-owned Memory root."""

    def __init__(self, memory_root: Path) -> None:
        if not isinstance(memory_root, Path):
            raise ValueError("memory_root must be a Path.")
        self._memory_root = memory_root

    def load_profile(self) -> ContextContribution | None:
        profile_path = self._memory_root / PROFILE_FILENAME
        if not profile_path.exists():
            return None
        try:
            resolved_root = self._memory_root.resolve()
            resolved_profile = profile_path.resolve(strict=True)
            if (
                resolved_profile.parent != resolved_root
                or resolved_profile.name != PROFILE_FILENAME
                or not resolved_profile.is_file()
            ):
                raise _profile_failure()
            content = resolved_profile.read_text(encoding="utf-8")
        except ContextProviderError:
            raise
        except (OSError, UnicodeError) as exc:
            raise _profile_failure() from exc
        if not content.strip():
            return None
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return ContextContribution(
            kind=ContextContributionKind.PROFILE,
            source="profile",
            content=content,
            estimated_tokens=estimate_tokens(content),
            provenance=ContextProvenance(
                reference="profile://profile.md",
                attributes=(
                    ("relative_path", PROFILE_FILENAME),
                    ("content_hash", content_hash),
                ),
            ),
        )


def _profile_failure() -> ContextProviderError:
    return ContextProviderError(
        "The user Profile could not be loaded safely.",
        code=ContextErrorCode.PROFILE_PROVIDER_FAILED,
    )
