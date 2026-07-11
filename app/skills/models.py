"""Framework-independent Skill System models."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from app.common.validation import (
    require_non_empty_string,
    require_unique_non_empty_strings,
)


_SKILL_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class SkillReferenceDefinition:
    """A reference declared by a Skill and addressable by stable ID."""

    reference_id: str
    relative_path: str
    description: str | None = None

    def __post_init__(self) -> None:
        require_non_empty_string(self.reference_id, "reference_id")
        require_non_empty_string(self.relative_path, "relative_path")
        if self.description is not None:
            require_non_empty_string(self.description, "description")


@dataclass(frozen=True)
class SkillReference:
    """One declared Skill reference loaded on demand."""

    skill_id: str
    reference_id: str
    description: str
    relative_path: str
    content: str

    def __post_init__(self) -> None:
        require_non_empty_string(self.skill_id, "skill_id")
        require_non_empty_string(self.reference_id, "reference_id")
        require_non_empty_string(self.relative_path, "relative_path")
        require_non_empty_string(self.content, "content")
        if not isinstance(self.description, str):
            raise ValueError("description must be a string.")


@dataclass(frozen=True)
class SkillDefinition:
    """Lightweight Skill metadata safe to load at runtime startup."""

    skill_id: str
    description: str
    root_path: Path
    capability_hints: tuple[str, ...] = field(default_factory=tuple)
    references: tuple[SkillReferenceDefinition, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        require_non_empty_string(self.skill_id, "skill_id")
        require_non_empty_string(self.description, "description")
        if len(self.skill_id) > 64 or not _SKILL_ID_PATTERN.fullmatch(self.skill_id):
            raise ValueError(
                "skill_id must be at most 64 characters and contain only "
                "lowercase letters, numbers, and single hyphens."
            )
        if len(self.description) > 1024:
            raise ValueError("description must be at most 1024 characters.")
        if not isinstance(self.root_path, Path):
            raise ValueError("root_path must be a Path.")
        require_unique_non_empty_strings(self.capability_hints, "capability_hints")
        if not isinstance(self.references, tuple):
            raise ValueError("references must be a tuple.")
        if any(not isinstance(item, SkillReferenceDefinition) for item in self.references):
            raise ValueError("references must contain SkillReferenceDefinition values.")
        reference_ids = [item.reference_id for item in self.references]
        if len(set(reference_ids)) != len(reference_ids):
            raise ValueError("references must not contain duplicate reference IDs.")


@dataclass(frozen=True)
class LoadedSkill:
    """A selected Skill whose instruction body has been loaded on demand."""

    definition: SkillDefinition
    body: str

    def __post_init__(self) -> None:
        if not isinstance(self.definition, SkillDefinition):
            raise ValueError("definition must be a SkillDefinition.")
        require_non_empty_string(self.body, "body")


@dataclass(frozen=True)
class SkillSelection:
    """Validated request-local result produced by a future Skill selector."""

    selected_skill_ids: tuple[str, ...] = field(default_factory=tuple)
    reason: str | None = None

    def __post_init__(self) -> None:
        require_unique_non_empty_strings(self.selected_skill_ids, "selected_skill_ids")
        if self.reason is not None:
            require_non_empty_string(self.reason, "reason")


@dataclass(frozen=True)
class PromptContribution:
    """Skill instructions supplied to future context/prompt assembly."""

    skill_id: str
    instructions: str
    capability_hints: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        require_non_empty_string(self.skill_id, "skill_id")
        require_non_empty_string(self.instructions, "instructions")
        require_unique_non_empty_strings(self.capability_hints, "capability_hints")


@dataclass(frozen=True)
class SkillPreparation:
    """Request-local output of the complete Skill preparation stage."""

    selection: SkillSelection
    loaded_skill_ids: tuple[str, ...] = field(default_factory=tuple)
    prompt_contributions: tuple[PromptContribution, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.selection, SkillSelection):
            raise ValueError("selection must be a SkillSelection.")
        require_unique_non_empty_strings(self.loaded_skill_ids, "loaded_skill_ids")
        if not isinstance(self.prompt_contributions, tuple):
            raise ValueError("prompt_contributions must be a tuple.")
        if any(
            not isinstance(item, PromptContribution)
            for item in self.prompt_contributions
        ):
            raise ValueError(
                "prompt_contributions must contain PromptContribution values."
            )
        contribution_ids = tuple(
            item.skill_id for item in self.prompt_contributions
        )
        if contribution_ids != self.loaded_skill_ids:
            raise ValueError(
                "prompt_contributions must match loaded_skill_ids in order."
            )
