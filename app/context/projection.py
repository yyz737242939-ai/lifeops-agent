"""Consumer-safe projection rules for one frozen ContextAssembly."""

from __future__ import annotations

from app.context.models import (
    ContextAssembly,
    ContextContribution,
    ContextContributionKind,
    ContextQueryOrigin,
)


def project_context_contributions(
    assembly: ContextAssembly | None,
) -> tuple[ContextContribution, ...]:
    """Avoid repeating natural current input already carried by typed model input."""

    if assembly is None:
        return ()
    if not isinstance(assembly, ContextAssembly):
        raise ValueError("assembly must be a ContextAssembly when provided.")
    if assembly.query.origin != ContextQueryOrigin.CURRENT_USER_GOAL:
        return assembly.contributions
    if not any(
        item.kind == ContextContributionKind.CURRENT_INPUT
        for item in assembly.contributions
    ):
        return assembly.contributions
    return tuple(
        item
        for item in assembly.contributions
        if item.kind != ContextContributionKind.CURRENT_INPUT
    )
