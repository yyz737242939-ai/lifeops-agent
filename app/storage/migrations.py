"""SQLite schema version migration runner."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from collections.abc import Sequence

from app.common.errors import MigrationError
from app.common.time import utc_now_iso
from app.storage.schema import (
    CURRENT_SCHEMA_VERSION,
    MIGRATIONS,
    SCHEMA_MIGRATIONS_TABLE_SQL,
    SchemaMigration,
)


@dataclass(frozen=True)
class MigrationReport:
    previous_version: int
    current_version: int
    applied_versions: tuple[int, ...]


def migrate(
    conn: sqlite3.Connection,
    migrations: Sequence[SchemaMigration] = MIGRATIONS,
) -> MigrationReport:
    """Apply pending SQLite schema migrations."""
    try:
        _ensure_schema_migrations_table(conn)
        previous_version = get_schema_version(conn)
        latest_known_version = _latest_known_version(migrations)
        if previous_version > latest_known_version:
            raise MigrationError(
                "SQLite schema version is newer than this code supports.",
                code="schema_version_too_new",
                details={
                    "database_version": previous_version,
                    "code_version": latest_known_version,
                },
            )

        applied: list[int] = []
        for migration in migrations:
            if migration.version <= previous_version:
                continue
            _apply_migration(conn, migration)
            applied.append(migration.version)

        return MigrationReport(
            previous_version=previous_version,
            current_version=get_schema_version(conn),
            applied_versions=tuple(applied),
        )
    except MigrationError:
        raise
    except sqlite3.Error as exc:
        raise MigrationError(
            "SQLite schema migration failed.",
            code="schema_migration_failed",
        ) from exc


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Return the latest applied schema version, or 0 for an empty database."""
    if not _table_exists(conn, "schema_migrations"):
        return 0

    row = conn.execute("SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations").fetchone()
    return int(row["version"])


def _ensure_schema_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(SCHEMA_MIGRATIONS_TABLE_SQL)


def _apply_migration(conn: sqlite3.Connection, migration: SchemaMigration) -> None:
    try:
        conn.execute("BEGIN")
        _execute_sql_script(conn, migration.sql)
        conn.execute(
            """
            INSERT INTO schema_migrations (version, name, applied_at)
            VALUES (?, ?, ?)
            """,
            (migration.version, migration.name, utc_now_iso()),
        )
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        raise MigrationError(
            "SQLite schema migration failed.",
            code="schema_migration_failed",
            details={"version": migration.version, "name": migration.name},
        ) from exc


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def _latest_known_version(migrations: Sequence[SchemaMigration]) -> int:
    if not migrations:
        return CURRENT_SCHEMA_VERSION
    return max(migration.version for migration in migrations)


def _execute_sql_script(conn: sqlite3.Connection, sql: str) -> None:
    statements = [statement.strip() for statement in sql.split(";") if statement.strip()]
    for statement in statements:
        conn.execute(statement)
