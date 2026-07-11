"""Manifest-whitelisted Skill reference loading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.observability.logger import TraceSink
from app.skills.errors import SkillReferenceError
from app.skills.models import SkillDefinition, SkillReference


REFERENCE_MANIFEST = Path("references/manifest.json")
MAX_REFERENCE_CHARS = 12_000


def read_skill_reference(
    definition: SkillDefinition,
    reference_id: str,
    *,
    trace: TraceSink | None = None,
    max_chars: int = MAX_REFERENCE_CHARS,
) -> SkillReference:
    """Load one declared Markdown reference by stable manifest ID."""

    try:
        result = _read_skill_reference(definition, reference_id, max_chars=max_chars)
    except Exception as exc:
        if trace is not None:
            trace.append(
                "skill.reference.load.failed",
                {
                    "skill_id": getattr(definition, "skill_id", None),
                    "reference_id": reference_id if isinstance(reference_id, str) else None,
                    "error_code": getattr(exc, "code", None) or "skill_reference_failed",
                    "error_type": exc.__class__.__name__,
                },
            )
        raise

    if trace is not None:
        trace.append(
            "skill.reference.loaded",
            {"skill_id": result.skill_id, "reference_id": result.reference_id},
        )
    return result


def _read_skill_reference(
    definition: SkillDefinition,
    reference_id: str,
    *,
    max_chars: int,
) -> SkillReference:
    if not isinstance(definition, SkillDefinition):
        raise SkillReferenceError(
            "definition must be a SkillDefinition.",
            code="skill_reference_invalid_definition",
        )
    if not isinstance(reference_id, str) or not reference_id.strip():
        raise SkillReferenceError(
            "reference_id must be a non-empty string.",
            code="skill_reference_invalid_id",
        )
    if max_chars <= 0:
        raise SkillReferenceError(
            "max_chars must be positive.",
            code="skill_reference_invalid_limit",
        )

    skill_root = definition.root_path.resolve()
    manifest_path = skill_root / REFERENCE_MANIFEST
    manifest = _read_manifest(manifest_path)
    references = manifest.get("references")
    if not isinstance(references, dict):
        raise _error("skill_reference_manifest_invalid", "Manifest must contain a references object.")
    declaration = references.get(reference_id)
    if not isinstance(declaration, dict):
        raise _error(
            "skill_reference_not_declared",
            f"Reference is not declared: {reference_id}",
            reference_id=reference_id,
        )
    if set(declaration) != {"path", "description"}:
        raise _error(
            "skill_reference_manifest_invalid",
            "Reference declaration must contain only path and description.",
            reference_id=reference_id,
        )
    raw_path = declaration["path"]
    description = declaration["description"]
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise _error("skill_reference_manifest_invalid", "Reference path must be a non-empty string.")
    if not isinstance(description, str):
        raise _error("skill_reference_manifest_invalid", "Reference description must be a string.")
    relative_path = Path(raw_path)
    if relative_path.is_absolute() or ".." in relative_path.parts or relative_path.suffix.lower() != ".md":
        raise _error(
            "skill_reference_forbidden",
            "Reference path must be a relative Markdown path inside the Skill directory.",
            reference_id=reference_id,
        )
    resolved = (skill_root / relative_path).resolve()
    try:
        resolved.relative_to(skill_root)
    except ValueError as exc:
        raise _error("skill_reference_forbidden", "Reference path escapes the Skill directory.") from exc
    if not resolved.is_file():
        raise _error(
            "skill_reference_not_found",
            "Declared reference file does not exist.",
            reference_id=reference_id,
        )
    try:
        content = resolved.read_text(encoding="utf-8-sig").strip()
    except (OSError, UnicodeError) as exc:
        raise _error("skill_reference_read_failed", "Unable to read declared reference.") from exc
    if not content:
        raise _error("skill_reference_empty", "Declared reference is empty.")
    if len(content) > max_chars:
        raise _error(
            "skill_reference_too_large",
            f"Reference exceeds {max_chars} characters.",
            max_chars=max_chars,
        )
    return SkillReference(
        skill_id=definition.skill_id,
        reference_id=reference_id,
        description=description,
        relative_path=relative_path.as_posix(),
        content=content,
    )


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise _error("skill_reference_manifest_not_found", "Reference manifest does not exist.")
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _error("skill_reference_manifest_invalid", "Reference manifest is not valid JSON.") from exc
    if not isinstance(raw, dict) or set(raw) != {"references"}:
        raise _error(
            "skill_reference_manifest_invalid",
            "Reference manifest must contain only a references object.",
        )
    return raw


def _error(code: str, message: str, **details: Any) -> SkillReferenceError:
    return SkillReferenceError(message, code=code, details=details)
