import json
from pathlib import Path
from collections.abc import Sequence
from typing import Any, TypeVar
from uuid import uuid4

from pydantic import BaseModel


ModelT = TypeVar("ModelT", bound=BaseModel)
ValueT = TypeVar("ValueT")


def ensure_json_file(path: Path, default: Any) -> None:
    """Create a JSON file with a typed default value when it does not exist."""
    if not path.exists():
        write_json_file(path, default)


def read_json_file(path: Path, expected_type: type[ValueT]) -> ValueT:
    """Read JSON and validate its top-level container type."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON in {path}") from error
    if not isinstance(payload, expected_type):
        type_name = "list" if expected_type is list else "object"
        raise ValueError(f"{path} must contain a JSON {type_name}")
    return payload


def write_json_file(path: Path, payload: Any) -> None:
    """Atomically replace a UTF-8 JSON file to avoid partial writes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def load_model_list(path: Path, model_type: type[ModelT]) -> list[ModelT]:
    """Load a JSON array and validate each item as a Pydantic model."""
    ensure_json_file(path, [])
    payload = read_json_file(path, list)
    return [model_type.model_validate(item) for item in payload]


def save_model_list(path: Path, models: Sequence[BaseModel]) -> None:
    """Persist Pydantic models using their JSON-compatible representation."""
    write_json_file(path, [model.model_dump(mode="json") for model in models])


def parse_json_object(value: str) -> dict[str, Any] | None:
    """Parse an object-shaped JSON string, returning None for other input."""
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None
