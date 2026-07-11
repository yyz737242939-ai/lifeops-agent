"""Small validation helpers shared by framework-independent models."""

from __future__ import annotations


def require_non_empty_string(value: str, field_name: str) -> None:
    """Require a string containing at least one non-whitespace character."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")


def require_unique_non_empty_strings(
    values: tuple[str, ...], field_name: str
) -> None:
    """Require a tuple containing only unique, non-empty strings."""

    if not isinstance(values, tuple):
        raise ValueError(f"{field_name} must be a tuple.")
    for value in values:
        require_non_empty_string(value, field_name)
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} must not contain duplicates.")
