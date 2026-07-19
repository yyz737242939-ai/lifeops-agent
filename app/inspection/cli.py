"""Independent command-line dispatch for the read-only Inspector."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from app.inspection.composition import build_inspector_service
from app.inspection.diagnostics import default_diagnostic_registry
from app.inspection.errors import (
    InspectorError,
    InspectorValidationCode,
    InspectorValidationError,
)
from app.inspection.models import InspectionQuery, InspectionTarget, InspectionView
from app.inspection.renderers import (
    InspectionOutputFormat,
    InspectionRenderer,
)


def run_inspector_cli(
    argv: Sequence[str],
    *,
    default_log_root: str | Path = "logs/sessions",
) -> int:
    parser = argparse.ArgumentParser(description="Inspect LifeOps runtime traces.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--trace-id")
    target.add_argument("--run-id")
    target.add_argument("--plan-id")
    parser.add_argument("--session-id")
    parser.add_argument("--log-root", default=str(default_log_root))
    parser.add_argument("--index-path")
    parser.add_argument("--view", default="summary")
    parser.add_argument("--span-id")
    parser.add_argument("--include-sensitive", action="store_true")
    parser.add_argument(
        "--format",
        choices=tuple(item.value for item in InspectionOutputFormat),
        default=InspectionOutputFormat.TEXT.value,
    )
    args = parser.parse_args(list(argv))
    try:
        views = _parse_views(args.view)
        query = InspectionQuery(
            target=InspectionTarget(
                trace_id=args.trace_id,
                run_id=args.run_id,
                plan_id=args.plan_id,
                session_id=args.session_id,
            ),
            views=views,
            span_id=args.span_id,
            include_sensitive=args.include_sensitive,
        )
        service = build_inspector_service(
            args.log_root,
            index_path=args.index_path,
            diagnostic_registry=(
                default_diagnostic_registry()
                if InspectionView.DIAGNOSE in views
                else None
            ),
        )
        result = service.inspect(query)
        print(
            InspectionRenderer().render(
                result,
                InspectionOutputFormat(args.format),
            )
        )
    except (InspectorError, InspectorValidationError, ValueError) as exc:
        print(f"error: {getattr(exc, 'message', str(exc))}")
        return 1
    return 0


def _parse_views(raw: str) -> tuple[InspectionView, ...]:
    try:
        return tuple(InspectionView(item.strip()) for item in raw.split(",") if item.strip())
    except ValueError as exc:
        raise InspectorValidationError(
            "view contains an unsupported Inspector view.",
            code=InspectorValidationCode.INVALID_FIELD,
        ) from exc
