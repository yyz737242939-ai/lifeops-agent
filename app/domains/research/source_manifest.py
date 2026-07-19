"""Strict loading for Research Skill-owned external source declarations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.common.errors import AppError
from app.common.validation import require_non_empty_string


SOURCE_MANIFEST = Path("sources/manifest.json")
ALLOWED_RESEARCH_SOURCE_URLS = frozenset(
    {
        "https://huggingface.co/papers",
        "https://huggingface.co/blog",
    }
)


class ResearchSourceManifestError(AppError):
    """Raised when a Research source declaration is missing or unsafe."""


@dataclass(frozen=True)
class ResearchSourceDefinition:
    source_key: str
    name: str
    url: str
    content_type: str
    description: str
    relative_path: str

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            require_non_empty_string(getattr(self, field_name), field_name)


def load_research_source(
    skill_root: Path, source_key: str
) -> ResearchSourceDefinition:
    """Load one declared source by stable key without performing network I/O."""
    if not isinstance(skill_root, Path):
        raise _error("research_source_invalid_root", "skill_root must be a Path.")
    if not isinstance(source_key, str) or not source_key.strip():
        raise _error(
            "research_source_invalid_key", "source_key must be a non-empty string."
        )

    resolved_root = skill_root.resolve()
    manifest = _read_json(resolved_root / SOURCE_MANIFEST, "research_source_manifest_not_found")
    if set(manifest) != {"sources"} or not isinstance(manifest["sources"], dict):
        raise _error(
            "research_source_manifest_invalid",
            "Source manifest must contain only a sources object.",
        )
    declaration_ref = manifest["sources"].get(source_key)
    if not isinstance(declaration_ref, dict):
        raise _error(
            "research_source_not_declared",
            f"Research source is not declared: {source_key}",
        )
    if set(declaration_ref) != {"path"}:
        raise _error(
            "research_source_manifest_invalid",
            "Source manifest entry must contain only path.",
        )

    declaration_path = _resolve_declaration_path(
        resolved_root, declaration_ref["path"], source_key
    )
    declaration = _read_json(declaration_path, "research_source_declaration_not_found")
    expected_fields = {"source_key", "name", "url", "content_type", "description"}
    if set(declaration) != expected_fields:
        raise _error(
            "research_source_declaration_invalid",
            "Source declaration fields do not match the supported schema.",
        )
    if declaration["source_key"] != source_key:
        raise _error(
            "research_source_declaration_invalid",
            "Source declaration key does not match its manifest key.",
        )
    try:
        definition = ResearchSourceDefinition(
            source_key=declaration["source_key"],
            name=declaration["name"],
            url=declaration["url"],
            content_type=declaration["content_type"],
            description=declaration["description"],
            relative_path=declaration_path.relative_to(resolved_root).as_posix(),
        )
    except (TypeError, ValueError) as exc:
        raise _error(
            "research_source_declaration_invalid",
            "Source declaration contains invalid values.",
        ) from exc
    _validate_definition(definition)
    return definition


def _resolve_declaration_path(
    skill_root: Path, raw_path: Any, source_key: str
) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise _error(
            "research_source_manifest_invalid", "Source path must be a non-empty string."
        )
    relative_path = Path(raw_path)
    if (
        relative_path.is_absolute()
        or ".." in relative_path.parts
        or relative_path.suffix.lower() != ".json"
    ):
        raise _error(
            "research_source_forbidden",
            f"Source declaration path is forbidden: {source_key}",
        )
    resolved = (skill_root / relative_path).resolve()
    try:
        resolved.relative_to(skill_root)
    except ValueError as exc:
        raise _error(
            "research_source_forbidden", "Source declaration escapes the Skill root."
        ) from exc
    return resolved


def _validate_definition(definition: ResearchSourceDefinition) -> None:
    parsed = urlparse(definition.url)
    if definition.content_type != "html":
        raise _error(
            "research_source_forbidden", "Research source content_type must be html."
        )
    if parsed.scheme != "https" or parsed.hostname != "huggingface.co":
        raise _error(
            "research_source_forbidden",
            "Research sources must use the Hugging Face HTTPS host.",
        )
    if definition.url not in ALLOWED_RESEARCH_SOURCE_URLS:
        raise _error(
            "research_source_forbidden", "Research source URL is not allowlisted."
        )


def _read_json(path: Path, missing_code: str) -> dict[str, Any]:
    if not path.is_file():
        raise _error(missing_code, f"Research source file does not exist: {path.name}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _error(
            "research_source_manifest_invalid", "Research source file is not valid JSON."
        ) from exc
    if not isinstance(raw, dict):
        raise _error(
            "research_source_manifest_invalid", "Research source file must be an object."
        )
    return raw


def _error(code: str, message: str) -> ResearchSourceManifestError:
    return ResearchSourceManifestError(message, code=code)
