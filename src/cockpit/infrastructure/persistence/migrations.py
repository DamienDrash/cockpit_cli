"""SQLite migration management."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import sqlite3

from cockpit.infrastructure.persistence.schema import (
    CREATE_MIGRATIONS_TABLE,
    DATABASE_VERSION,
    V1_STATEMENTS,
)


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    statements: tuple[str, ...]


MIGRATIONS: tuple[Migration, ...] = (
    Migration(version=1, statements=V1_STATEMENTS),
)


def apply_migrations(connection: sqlite3.Connection) -> int:
    """Apply all pending migrations and return the current DB version."""
    connection.execute(CREATE_MIGRATIONS_TABLE)
    applied_versions = {
        row[0]
        for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
    }

    for migration in MIGRATIONS:
        if migration.version in applied_versions:
            continue
        with connection:
            for statement in migration.statements:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (migration.version, datetime.now(UTC).isoformat()),
            )

    return current_version(connection)


def current_version(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    value = row[0] if row is not None else None
    return int(value or 0)


def is_current(connection: sqlite3.Connection) -> bool:
    return current_version(connection) >= DATABASE_VERSION
