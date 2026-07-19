"""Expected Skill System failures."""

from app.common.errors import AppError


class SkillError(AppError):
    """Base error for expected Skill System failures."""


class SkillDiscoveryError(SkillError):
    """Raised when a Skill root cannot be discovered safely."""


class SkillMetadataError(SkillError):
    """Raised when SKILL.md metadata violates the supported contract."""


class SkillSelectionError(SkillError):
    """Raised when Skill selection fails or returns an invalid structure."""


class SkillLoadError(SkillError):
    """Raised when a selected Skill body cannot be loaded safely."""


class SkillReferenceError(SkillError):
    """Raised when a Skill reference is missing, invalid, or forbidden."""


class SkillPromptError(SkillError):
    """Raised when loaded Skills cannot form prompt contributions safely."""


class SkillRegistryError(SkillError):
    """Raised when Skill registry contents are invalid."""


class SkillNotFoundError(SkillRegistryError):
    """Raised when a requested Skill is not registered."""
