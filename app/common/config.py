"""Application configuration loading."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.common.errors import ConfigError

DEFAULT_CONFIG_PATH = Path("config/default.json")


@dataclass(frozen=True)
class AppConfig:
    database_path: Path


def load_app_config(path: str | Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    """Load application defaults from a JSON config file."""
    config_path = Path(path)
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(
            "Application config file was not found.",
            code="config_not_found",
            details={"path": str(config_path)},
        ) from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(
            "Application config file is not valid JSON.",
            code="config_invalid_json",
            details={"path": str(config_path), "position": exc.pos},
        ) from exc

    database_path = _read_database_path(raw, config_path)
    return AppConfig(database_path=database_path)


def _read_database_path(raw: Any, config_path: Path) -> Path:
    try:
        value = raw["database"]["path"]
    except (KeyError, TypeError) as exc:
        raise ConfigError(
            "Application config must define database.path.",
            code="config_database_path_missing",
            details={"path": str(config_path)},
        ) from exc

    if not isinstance(value, str) or not value.strip():
        raise ConfigError(
            "Application config database.path must be a non-empty string.",
            code="config_database_path_invalid",
            details={"path": str(config_path)},
        )

    return Path(value)
