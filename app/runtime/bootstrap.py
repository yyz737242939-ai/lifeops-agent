"""Runtime service bootstrap helpers."""

from __future__ import annotations

from pathlib import Path

from app.common.config import load_app_config
from app.runtime.service import RuntimeService
from app.storage.migrations import migrate
from app.storage.sqlite import connect_sqlite


def build_runtime_service(config_path: str | Path = "config/default.json") -> RuntimeService:
    """Build a RuntimeService with configured SQLite storage and migrations."""

    config = load_app_config(config_path)
    conn = connect_sqlite(config.database_path)
    migrate(conn)
    return RuntimeService(conn=conn)
