import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.skills.skill_loader import SKILLS_DIR


MAX_REFERENCE_CHARS = 12_000


@dataclass(frozen=True)
class SkillReference:
    skill_name: str
    ref_id: str
    description: str
    relative_path: str
    content: str

    @property
    def chars(self) -> int:
        return len(self.content)


class SkillReferenceError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def load_skill_reference(
    skill_name: str,
    ref_id: str,
    *,
    skills_dir: Path = SKILLS_DIR,
    max_chars: int = MAX_REFERENCE_CHARS,
) -> SkillReference:
    """Load one declared Markdown reference from a Skill-owned directory."""
    if not ref_id or not isinstance(ref_id, str):
        raise SkillReferenceError("invalid_arguments", "ref_id must be a non-empty string")

    skill_dir = (skills_dir / skill_name).resolve()
    manifest = _read_manifest(skill_dir)
    references = manifest.get("references")
    if not isinstance(references, dict):
        raise SkillReferenceError(
            "skill_reference_manifest_invalid",
            f"{skill_name} reference manifest must contain a references object",
        )

    declaration = references.get(ref_id)
    if not isinstance(declaration, dict):
        raise SkillReferenceError(
            "skill_reference_not_found",
            f"Reference {ref_id!r} is not declared for skill {skill_name!r}",
        )

    relative_path = _declared_path(declaration, ref_id)
    reference_path = _resolve_reference_path(skill_dir, relative_path)
    content = reference_path.read_text(encoding="utf-8")
    if len(content) > max_chars:
        raise SkillReferenceError(
            "skill_reference_too_large",
            f"Reference {ref_id!r} exceeds {max_chars} characters",
        )

    return SkillReference(
        skill_name=skill_name,
        ref_id=ref_id,
        description=str(declaration.get("description") or ""),
        relative_path=reference_path.relative_to(skill_dir).as_posix(),
        content=content,
    )


def _read_manifest(skill_dir: Path) -> dict[str, Any]:
    manifest_path = skill_dir / "references" / "manifest.json"
    if not manifest_path.is_file():
        raise SkillReferenceError(
            "skill_reference_manifest_not_found",
            f"Reference manifest not found for skill directory {skill_dir}",
        )
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SkillReferenceError(
            "skill_reference_manifest_invalid",
            f"Invalid reference manifest JSON: {error}",
        ) from error
    if not isinstance(raw, dict):
        raise SkillReferenceError(
            "skill_reference_manifest_invalid",
            "Reference manifest root must be a JSON object",
        )
    return raw


def _declared_path(declaration: dict[str, Any], ref_id: str) -> Path:
    raw_path = declaration.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise SkillReferenceError(
            "skill_reference_manifest_invalid",
            f"Reference {ref_id!r} must declare a non-empty path",
        )
    path = Path(raw_path)
    if path.is_absolute() or ".." in path.parts:
        raise SkillReferenceError(
            "skill_reference_forbidden",
            f"Reference {ref_id!r} path must stay inside the skill directory",
        )
    if path.suffix.lower() != ".md":
        raise SkillReferenceError(
            "skill_reference_forbidden",
            f"Reference {ref_id!r} must point to a Markdown file",
        )
    return path


def _resolve_reference_path(skill_dir: Path, relative_path: Path) -> Path:
    resolved = (skill_dir / relative_path).resolve()
    try:
        resolved.relative_to(skill_dir)
    except ValueError as error:
        raise SkillReferenceError(
            "skill_reference_forbidden",
            "Reference path escapes the skill directory",
        ) from error
    if not resolved.is_file():
        raise SkillReferenceError(
            "skill_reference_not_found",
            f"Declared reference file does not exist: {relative_path.as_posix()}",
        )
    return resolved
