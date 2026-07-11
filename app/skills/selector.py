"""Request-local LLM Skill selection and LifeOps-owned validation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from app.observability.logger import TraceSink
from app.runtime.models import RuntimeRequest
from app.skills.errors import SkillSelectionError
from app.skills.models import SkillDefinition, SkillSelection


class SkillSelectionClient(Protocol):
    """Thin model boundary; implementations return JSON-like structured output."""

    def select(
        self,
        request: RuntimeRequest,
        skill_metadata: tuple[SkillDefinition, ...],
    ) -> Mapping[str, Any]:
        """Select zero or more Skills using all supplied metadata."""


def select_skills(
    request: RuntimeRequest,
    skill_metadata: Sequence[SkillDefinition],
    llm: SkillSelectionClient,
    *,
    trace: TraceSink | None = None,
) -> SkillSelection:
    """Ask an LLM to select Skills, then validate against LifeOps metadata."""

    try:
        metadata = _validate_metadata(skill_metadata)
        raw = llm.select(request, metadata)
        selection = _validate_selection(raw, metadata)
    except Exception as exc:
        if trace is not None:
            trace.append(
                "skill.selection.failed",
                {
                    "error_code": getattr(exc, "code", None) or "skill_selection_failed",
                    "error_type": exc.__class__.__name__,
                },
            )
        if isinstance(exc, SkillSelectionError):
            raise
        raise SkillSelectionError(
            "Skill selection model call failed.",
            code="skill_selection_model_failed",
            details={"error_type": exc.__class__.__name__},
        ) from exc

    if trace is not None:
        trace.append(
            "skill.selected",
            {
                "selected_skill_ids": list(selection.selected_skill_ids),
                "selection_count": len(selection.selected_skill_ids),
            },
        )
    return selection


def _validate_metadata(
    skill_metadata: Sequence[SkillDefinition],
) -> tuple[SkillDefinition, ...]:
    if isinstance(skill_metadata, (str, bytes)) or not isinstance(skill_metadata, Sequence):
        raise SkillSelectionError(
            "skill_metadata must be a sequence of SkillDefinition values.",
            code="skill_selection_invalid_metadata",
        )
    metadata = tuple(skill_metadata)
    if any(not isinstance(item, SkillDefinition) for item in metadata):
        raise SkillSelectionError(
            "skill_metadata must contain SkillDefinition values.",
            code="skill_selection_invalid_metadata",
        )
    ids = [item.skill_id for item in metadata]
    if len(set(ids)) != len(ids):
        raise SkillSelectionError(
            "skill_metadata contains duplicate Skill IDs.",
            code="skill_selection_duplicate_metadata_id",
        )
    return metadata


def _validate_selection(
    raw: Mapping[str, Any],
    metadata: tuple[SkillDefinition, ...],
) -> SkillSelection:
    if not isinstance(raw, Mapping):
        raise SkillSelectionError(
            "Skill selection output must be an object.",
            code="skill_selection_invalid_output",
        )
    expected_fields = {"selected_skill_ids", "reason"}
    if set(raw) != expected_fields:
        raise SkillSelectionError(
            "Skill selection output must contain only selected_skill_ids and reason.",
            code="skill_selection_invalid_output",
        )
    selected_ids = raw["selected_skill_ids"]
    reason = raw["reason"]
    if not isinstance(selected_ids, list) or any(not isinstance(item, str) for item in selected_ids):
        raise SkillSelectionError(
            "selected_skill_ids must be a list of strings.",
            code="skill_selection_invalid_ids",
        )
    if not isinstance(reason, str) or not reason.strip():
        raise SkillSelectionError(
            "reason must be a non-empty string.",
            code="skill_selection_invalid_reason",
        )
    if len(set(selected_ids)) != len(selected_ids):
        raise SkillSelectionError(
            "selected_skill_ids must not contain duplicates.",
            code="skill_selection_duplicate_id",
        )
    known_ids = {item.skill_id for item in metadata}
    unknown_ids = sorted(set(selected_ids) - known_ids)
    if unknown_ids:
        raise SkillSelectionError(
            "Skill selection contains unknown Skill IDs.",
            code="skill_selection_unknown_id",
            details={"unknown_skill_ids": unknown_ids},
        )
    return SkillSelection(tuple(selected_ids), reason.strip())
