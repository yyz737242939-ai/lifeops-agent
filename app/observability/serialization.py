from typing import Any


def json_safe(value: Any) -> Any:
    """Convert SDK, Pydantic, and runtime objects into JSON-compatible values."""
    if hasattr(value, "model_dump"):
        return json_safe(value.model_dump())
    if hasattr(value, "to_dict"):
        return json_safe(value.to_dict())
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)
