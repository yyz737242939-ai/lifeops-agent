"""Read-only Profile Memory loading."""

from dataclasses import dataclass
from pathlib import Path
import re


DEFAULT_PROFILE_PATH = Path("data/memory/profile.md")
_HTML_COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)


@dataclass(frozen=True)
class ProfileMemory:
    """A snapshot of the user-maintained read-only profile file."""

    path: str
    content: str
    exists: bool
    loaded: bool
    char_count: int


class ProfileLoader:
    """Load Profile Memory without creating or modifying files."""

    def __init__(self, path: str | Path = DEFAULT_PROFILE_PATH) -> None:
        self.path = Path(path)

    def load(self) -> ProfileMemory:
        if not self.path.exists():
            return ProfileMemory(
                path=str(self.path),
                content="",
                exists=False,
                loaded=False,
                char_count=0,
            )

        content = self.path.read_text(encoding="utf-8")
        content = _strip_markdown_comments(content).strip()
        return ProfileMemory(
            path=str(self.path),
            content=content,
            exists=True,
            loaded=bool(content),
            char_count=len(content),
        )


def _strip_markdown_comments(content: str) -> str:
    return _HTML_COMMENT_PATTERN.sub("", content)
