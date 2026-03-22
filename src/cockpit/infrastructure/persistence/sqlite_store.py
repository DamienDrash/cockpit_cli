"""Thin SQLite store wrapper."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from threading import RLock

from cockpit.infrastructure.persistence.migrations import apply_migrations
from cockpit.shared.config import default_db_path


class SQLiteStore:
    """Owns the SQLite connection used by the first implementation slice."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        initialize: bool = True,
    ) -> None:
        self.path = (path or default_db_path()).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        if initialize:
            self.initialize()

    def initialize(self) -> int:
        with self._lock:
            return apply_migrations(self.connection)

    def execute(
        self,
        sql: str,
        params: Sequence[object] = (),
    ) -> sqlite3.Cursor:
        with self._lock:
            with self.connection:
                return self.connection.execute(sql, params)

    def fetchone(
        self,
        sql: str,
        params: Sequence[object] = (),
    ) -> sqlite3.Row | None:
        with self._lock:
            return self.connection.execute(sql, params).fetchone()

    def fetchall(
        self,
        sql: str,
        params: Sequence[object] = (),
    ) -> list[sqlite3.Row]:
        with self._lock:
            return list(self.connection.execute(sql, params).fetchall())

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            with self.connection:
                yield self.connection

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    def __enter__(self) -> "SQLiteStore":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
