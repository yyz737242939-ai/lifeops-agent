"""Read-only Inspector query and result contracts."""

from app.inspection.errors import (
    InspectorError,
    InspectorErrorCode,
    InspectorValidationCode,
    InspectorValidationError,
)
from app.inspection.models import (
    InspectionQuery,
    InspectionResult,
    InspectionTarget,
    InspectionView,
)
from app.inspection.service import InspectorService
from app.inspection.renderers import InspectionOutputFormat, InspectionRenderer
from app.inspection.diagnostics import (
    DiagnosticRegistry,
    DiagnosticRegistryResult,
    DiagnosticRule,
    default_diagnostic_registry,
)
from app.inspection.composition import (
    DEFAULT_TRACE_INDEX,
    FallbackAwareTraceReader,
    build_inspector_service,
)

__all__ = [
    "InspectionQuery",
    "InspectionResult",
    "InspectionTarget",
    "InspectionView",
    "InspectorError",
    "InspectorErrorCode",
    "InspectionOutputFormat",
    "InspectionRenderer",
    "DiagnosticRegistry",
    "DiagnosticRegistryResult",
    "DiagnosticRule",
    "default_diagnostic_registry",
    "DEFAULT_TRACE_INDEX",
    "FallbackAwareTraceReader",
    "build_inspector_service",
    "InspectorService",
    "InspectorValidationCode",
    "InspectorValidationError",
]
