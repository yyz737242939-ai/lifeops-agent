"""Skill metadata, loading, and selection primitives."""

from app.skills.errors import (
    SkillDiscoveryError,
    SkillError,
    SkillLoadError,
    SkillMetadataError,
    SkillNotFoundError,
    SkillPromptError,
    SkillReferenceError,
    SkillRegistryError,
    SkillSelectionError,
)
from app.skills.loader import discover_skills, load_skill
from app.skills.models import (
    LoadedSkill,
    PromptContribution,
    SkillDefinition,
    SkillReference,
    SkillReferenceDefinition,
    SkillPreparation,
    SkillSelection,
)
from app.skills.prompt_assembler import build_prompt_contributions
from app.skills.references import read_skill_reference
from app.skills.registry import SkillRegistry
from app.skills.selector import SkillSelectionClient, select_skills
from app.skills.service import SkillService

__all__ = [
    "LoadedSkill",
    "PromptContribution",
    "SkillDefinition",
    "SkillDiscoveryError",
    "SkillError",
    "SkillLoadError",
    "SkillMetadataError",
    "SkillNotFoundError",
    "SkillPromptError",
    "SkillPreparation",
    "SkillReference",
    "SkillReferenceError",
    "SkillReferenceDefinition",
    "SkillRegistry",
    "SkillRegistryError",
    "SkillSelection",
    "SkillSelectionClient",
    "SkillSelectionError",
    "SkillService",
    "build_prompt_contributions",
    "discover_skills",
    "load_skill",
    "read_skill_reference",
    "select_skills",
]
