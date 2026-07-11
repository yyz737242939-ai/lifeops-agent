"""Native SKILL.md metadata discovery with no agent-framework dependency."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.observability.logger import TraceSink
from app.skills.errors import SkillDiscoveryError, SkillLoadError, SkillMetadataError
from app.skills.models import LoadedSkill, SkillDefinition
from app.skills.registry import SkillRegistry


SKILL_FILENAME = "SKILL.md"
MAX_SKILL_BODY_CHARS = 50_000
SUPPORTED_FRONTMATTER_FIELDS = frozenset({"name", "description"})
_FIELD_PATTERN = re.compile(r"^([A-Za-z][A-Za-z0-9-]*):(?:[ \t]*(.*))?$")


def discover_skills(root: Path) -> list[SkillDefinition]:
    """Discover direct child Skill directories and load metadata only.

    This intentionally implements a strict LifeOps subset of Agent Skills YAML:
    required ``name`` and ``description`` scalar fields. Full bodies and
    supporting resources remain unloaded for progressive disclosure.
    """

    if not isinstance(root, Path):
        raise SkillDiscoveryError(
            "Skill root must be a Path.",
            code="skill_root_invalid",
        )
    if not root.exists():
        raise SkillDiscoveryError(
            f"Skill root does not exist: {root}",
            code="skill_root_not_found",
            details={"root": str(root)},
        )
    if not root.is_dir():
        raise SkillDiscoveryError(
            f"Skill root is not a directory: {root}",
            code="skill_root_not_directory",
            details={"root": str(root)},
        )

    definitions: list[SkillDefinition] = []
    for skill_dir in sorted((path for path in root.iterdir() if path.is_dir()), key=lambda p: p.name):
        skill_file = skill_dir / SKILL_FILENAME
        if not skill_file.is_file():
            continue
        definitions.append(_read_skill_metadata(skill_file))

    # Keep duplicate-ID validation at the shared registry boundary.
    return list(SkillRegistry(definitions).list_definitions())


def load_skill(
    definition: SkillDefinition,
    *,
    trace: TraceSink | None = None,
    max_chars: int = MAX_SKILL_BODY_CHARS,
) -> LoadedSkill:
    """Load one selected Skill body without loading supporting resources."""

    try:
        if not isinstance(definition, SkillDefinition):
            raise SkillLoadError(
                "definition must be a SkillDefinition.",
                code="skill_load_invalid_definition",
            )
        if max_chars <= 0:
            raise SkillLoadError(
                "max_chars must be positive.",
                code="skill_load_invalid_limit",
            )
        skill_file = definition.root_path / SKILL_FILENAME
        try:
            content = skill_file.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            raise SkillLoadError(
                f"Unable to read selected Skill: {definition.skill_id}",
                code="skill_body_read_failed",
                details={"skill_id": definition.skill_id},
            ) from exc
        body = _extract_body(content, skill_file)
        if not body:
            raise SkillLoadError(
                f"Selected Skill body is empty: {definition.skill_id}",
                code="skill_body_empty",
                details={"skill_id": definition.skill_id},
            )
        if len(body) > max_chars:
            raise SkillLoadError(
                f"Selected Skill body exceeds {max_chars} characters.",
                code="skill_body_too_large",
                details={"skill_id": definition.skill_id, "max_chars": max_chars},
            )
        loaded = LoadedSkill(definition=definition, body=body)
    except Exception as exc:
        _trace_failure(trace, "skill.load.failed", exc, skill_id=_safe_skill_id(definition))
        raise

    if trace is not None:
        trace.append("skill.loaded", {"skill_id": definition.skill_id})
    return loaded


def _read_skill_metadata(skill_file: Path) -> SkillDefinition:
    try:
        content = skill_file.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise SkillDiscoveryError(
            f"Unable to read Skill metadata: {skill_file}",
            code="skill_metadata_read_failed",
            details={"path": str(skill_file)},
        ) from exc

    metadata = _parse_frontmatter(content, skill_file)
    name = metadata.get("name")
    description = metadata.get("description")
    missing = sorted(field for field in SUPPORTED_FRONTMATTER_FIELDS if field not in metadata)
    if missing:
        raise _metadata_error(
            skill_file,
            "skill_metadata_missing_fields",
            f"SKILL.md is missing required frontmatter fields: {', '.join(missing)}",
            missing_fields=missing,
        )
    assert name is not None and description is not None
    if name != skill_file.parent.name:
        raise _metadata_error(
            skill_file,
            "skill_metadata_name_mismatch",
            "Skill name must match its parent directory name.",
            declared_name=name,
            directory_name=skill_file.parent.name,
        )

    try:
        return SkillDefinition(
            skill_id=name,
            description=description,
            root_path=skill_file.parent,
        )
    except ValueError as exc:
        raise _metadata_error(
            skill_file,
            "skill_metadata_invalid_value",
            str(exc),
        ) from exc


def _parse_frontmatter(content: str, skill_file: Path) -> dict[str, str]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        raise _metadata_error(
            skill_file,
            "skill_frontmatter_missing",
            "SKILL.md must start with YAML frontmatter.",
        )
    closing_index = _frontmatter_end_index(lines, skill_file)

    frontmatter_lines = lines[1:closing_index]
    metadata: dict[str, str] = {}
    index = 0
    while index < len(frontmatter_lines):
        line = frontmatter_lines[index]
        if not line.strip():
            index += 1
            continue
        match = _FIELD_PATTERN.fullmatch(line)
        if match is None:
            raise _metadata_error(
                skill_file,
                "skill_frontmatter_invalid_syntax",
                f"Unsupported frontmatter syntax on line {index + 2}.",
            )
        field_name, raw_value = match.groups()
        if field_name not in SUPPORTED_FRONTMATTER_FIELDS:
            raise _metadata_error(
                skill_file,
                "skill_frontmatter_unknown_field",
                f"Unsupported frontmatter field: {field_name}",
                field=field_name,
            )
        if field_name in metadata:
            raise _metadata_error(
                skill_file,
                "skill_frontmatter_duplicate_field",
                f"Duplicate frontmatter field: {field_name}",
                field=field_name,
            )

        if raw_value in {">", ">-", "|", "|-"}:
            block_lines: list[str] = []
            index += 1
            while index < len(frontmatter_lines) and (
                not frontmatter_lines[index].strip()
                or frontmatter_lines[index].startswith((" ", "\t"))
            ):
                block_lines.append(frontmatter_lines[index].lstrip())
                index += 1
            value = _fold_block(block_lines) if raw_value.startswith(">") else "\n".join(block_lines)
        else:
            value = _parse_scalar(raw_value or "", skill_file, field_name)
            index += 1
        metadata[field_name] = value.strip()

    return metadata


def _extract_body(content: str, skill_file: Path) -> str:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillLoadError(
            "SKILL.md must start with YAML frontmatter.",
            code="skill_frontmatter_missing",
            details={"path": str(skill_file)},
        )
    try:
        closing_index = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    except StopIteration as exc:
        raise SkillLoadError(
            "SKILL.md frontmatter is not closed.",
            code="skill_frontmatter_unclosed",
            details={"path": str(skill_file)},
        ) from exc
    return "\n".join(lines[closing_index + 1 :]).strip()


def _frontmatter_end_index(lines: list[str], skill_file: Path) -> int:
    try:
        return next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    except StopIteration as exc:
        raise _metadata_error(
            skill_file,
            "skill_frontmatter_unclosed",
            "SKILL.md frontmatter is not closed.",
        ) from exc


def _parse_scalar(value: str, skill_file: Path, field_name: str) -> str:
    value = value.strip()
    if value.startswith('"'):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise _metadata_error(
                skill_file,
                "skill_frontmatter_invalid_syntax",
                f"Invalid quoted value for {field_name}.",
            ) from exc
        if not isinstance(parsed, str):
            raise _metadata_error(
                skill_file,
                "skill_frontmatter_invalid_value_type",
                f"Frontmatter field {field_name} must be a string.",
            )
        return parsed
    if value.startswith("'"):
        if len(value) < 2 or not value.endswith("'"):
            raise _metadata_error(
                skill_file,
                "skill_frontmatter_invalid_syntax",
                f"Invalid quoted value for {field_name}.",
            )
        return value[1:-1].replace("''", "'")
    return value


def _fold_block(lines: list[str]) -> str:
    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        if line:
            current.append(line)
        elif current:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return "\n\n".join(paragraphs)


def _metadata_error(
    skill_file: Path,
    code: str,
    message: str,
    **details: object,
) -> SkillMetadataError:
    return SkillMetadataError(
        message,
        code=code,
        details={"path": str(skill_file), **details},
    )


def _safe_skill_id(definition: object) -> str | None:
    value = getattr(definition, "skill_id", None)
    return value if isinstance(value, str) and value else None


def _trace_failure(
    trace: TraceSink | None,
    event_type: str,
    error: Exception,
    **payload: Any,
) -> None:
    if trace is None:
        return
    error_code = getattr(error, "code", None)
    trace.append(
        event_type,
        {
            **payload,
            "error_code": error_code or "skill_unexpected_error",
            "error_type": error.__class__.__name__,
        },
    )
