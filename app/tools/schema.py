"""Validation for the small JSON Schema subset supported by Tool System V1."""

from __future__ import annotations

import json
import re
from typing import Any

from app.tools.errors import ToolSchemaError


_SUPPORTED_TYPES = {"object", "array", "string", "integer", "number", "boolean", "null"}
_COMMON_KEYWORDS = {"type", "description", "enum", "default"}
_TYPE_KEYWORDS = {
    "object": {"properties", "required", "additionalProperties"},
    "array": {"items", "minItems", "maxItems"},
    "string": {"minLength", "maxLength", "pattern", "format"},
    "integer": {"minimum", "maximum"},
    "number": {"minimum", "maximum"},
    "boolean": set(),
    "null": set(),
}


def validate_tool_schema(schema: dict[str, Any], field_name: str) -> None:
    """Validate one top-level object schema and its nested property schemas."""

    if not isinstance(schema, dict):
        _raise(field_name, "schema must be an object")
    if schema.get("type") != "object":
        _raise(field_name, 'top-level schema must declare type="object"')
    _validate_node(schema, field_name)


def validate_tool_value(value: Any, schema: dict[str, Any], field_name: str) -> None:
    """Validate one JSON-compatible value against the supported schema subset."""

    _validate_value(value, schema, field_name)


def _validate_value(value: Any, schema: dict[str, Any], path: str) -> None:
    schema_type = schema["type"]
    if not _matches_type(value, schema_type):
        _raise(path, f"value must have type {schema_type}")
    if "enum" in schema and value not in schema["enum"]:
        _raise(path, "value must be one of the declared enum values")

    if schema_type == "object":
        properties = schema.get("properties", {})
        missing = sorted(set(schema.get("required", [])) - set(value))
        if missing:
            _raise(path, f"missing required properties: {missing}")
        if not schema.get("additionalProperties", False):
            unknown = sorted(set(value) - set(properties))
            if unknown:
                _raise(path, f"unknown properties: {unknown}")
        for name, item in value.items():
            if name in properties:
                _validate_value(item, properties[name], f"{path}.{name}")
    elif schema_type == "array":
        _validate_length(value, schema, path, "minItems", "maxItems")
        for index, item in enumerate(value):
            _validate_value(item, schema["items"], f"{path}[{index}]")
    elif schema_type == "string":
        _validate_length(value, schema, path, "minLength", "maxLength")
        pattern = schema.get("pattern")
        if pattern is not None and re.search(pattern, value) is None:
            _raise(path, "value does not match pattern")
    elif schema_type in {"integer", "number"}:
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            _raise(path, f"value must be at least {minimum}")
        if maximum is not None and value > maximum:
            _raise(path, f"value must be at most {maximum}")


def _matches_type(value: Any, schema_type: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }[schema_type]


def _validate_length(
    value: Any,
    schema: dict[str, Any],
    path: str,
    minimum_key: str,
    maximum_key: str,
) -> None:
    minimum = schema.get(minimum_key)
    maximum = schema.get(maximum_key)
    if minimum is not None and len(value) < minimum:
        _raise(path, f"length must be at least {minimum}")
    if maximum is not None and len(value) > maximum:
        _raise(path, f"length must be at most {maximum}")


def _validate_node(schema: dict[str, Any], path: str) -> None:
    if not isinstance(schema, dict):
        _raise(path, "schema node must be an object")

    schema_type = schema.get("type")
    if schema_type not in _SUPPORTED_TYPES:
        _raise(path, "type must be one supported JSON Schema type")

    unknown = set(schema) - _COMMON_KEYWORDS - _TYPE_KEYWORDS[schema_type]
    if unknown:
        _raise(path, f"unsupported keywords: {sorted(unknown)}")

    description = schema.get("description")
    if description is not None and (
        not isinstance(description, str) or not description.strip()
    ):
        _raise(path, "description must be a non-empty string")

    if "enum" in schema:
        enum_values = schema["enum"]
        if not isinstance(enum_values, list) or not enum_values:
            _raise(path, "enum must be a non-empty list")
        serialized = [_json_value(value, f"{path}.enum") for value in enum_values]
        if len(set(serialized)) != len(serialized):
            _raise(path, "enum must not contain duplicates")

    if "default" in schema:
        _json_value(schema["default"], f"{path}.default")

    if schema_type == "object":
        _validate_object(schema, path)
    elif schema_type == "array":
        _validate_array(schema, path)
    elif schema_type == "string":
        _validate_string(schema, path)
    elif schema_type in {"integer", "number"}:
        _validate_number(schema, path)


def _validate_object(schema: dict[str, Any], path: str) -> None:
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        _raise(path, "properties must be an object")
    for name, property_schema in properties.items():
        if not isinstance(name, str) or not name.strip():
            _raise(path, "property names must be non-empty strings")
        _validate_node(property_schema, f"{path}.properties.{name}")

    required = schema.get("required", [])
    if not isinstance(required, list) or any(
        not isinstance(name, str) or not name.strip() for name in required
    ):
        _raise(path, "required must be a list of non-empty strings")
    if len(set(required)) != len(required):
        _raise(path, "required must not contain duplicates")
    unknown_required = sorted(set(required) - set(properties))
    if unknown_required:
        _raise(path, f"required references unknown properties: {unknown_required}")

    additional = schema.get("additionalProperties", False)
    if not isinstance(additional, bool):
        _raise(path, "additionalProperties must be a bool")


def _validate_array(schema: dict[str, Any], path: str) -> None:
    if "items" not in schema:
        _raise(path, "array schema must declare items")
    _validate_node(schema["items"], f"{path}.items")
    _validate_non_negative_bounds(schema, path, "minItems", "maxItems")


def _validate_string(schema: dict[str, Any], path: str) -> None:
    _validate_non_negative_bounds(schema, path, "minLength", "maxLength")
    for keyword in ("pattern", "format"):
        value = schema.get(keyword)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            _raise(path, f"{keyword} must be a non-empty string")
    pattern = schema.get("pattern")
    if pattern is not None:
        try:
            re.compile(pattern)
        except re.error as exc:
            _raise(path, "pattern must be a valid regular expression", cause=exc)


def _validate_number(schema: dict[str, Any], path: str) -> None:
    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    for keyword, value in (("minimum", minimum), ("maximum", maximum)):
        if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool)):
            _raise(path, f"{keyword} must be a number")
    if minimum is not None and maximum is not None and minimum > maximum:
        _raise(path, "minimum must not exceed maximum")


def _validate_non_negative_bounds(
    schema: dict[str, Any], path: str, minimum_key: str, maximum_key: str
) -> None:
    minimum = schema.get(minimum_key)
    maximum = schema.get(maximum_key)
    for keyword, value in ((minimum_key, minimum), (maximum_key, maximum)):
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            _raise(path, f"{keyword} must be a non-negative integer")
    if minimum is not None and maximum is not None and minimum > maximum:
        _raise(path, f"{minimum_key} must not exceed {maximum_key}")


def _json_value(value: Any, path: str) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        _raise(path, "value must be JSON serializable", cause=exc)


def _raise(path: str, message: str, *, cause: Exception | None = None) -> None:
    error = ToolSchemaError(
        f"Invalid Tool schema at {path}: {message}.",
        code="tool_schema_invalid",
        details={"path": path, "reason": message},
    )
    if cause is None:
        raise error
    raise error from cause
