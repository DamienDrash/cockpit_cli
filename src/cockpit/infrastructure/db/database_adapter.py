"""Structured local database discovery and query execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import sqlite3

from cockpit.shared.enums import SessionTargetKind


SQLITE_SUFFIXES = (".db", ".sqlite", ".sqlite3")
MUTATING_SQL_PREFIXES = {
    "alter",
    "attach",
    "create",
    "delete",
    "detach",
    "drop",
    "insert",
    "pragma",
    "reindex",
    "replace",
    "truncate",
    "update",
    "vacuum",
}


@dataclass(slots=True, frozen=True)
class DatabaseCatalogSnapshot:
    databases: list[str] = field(default_factory=list)
    is_available: bool = True
    message: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class DatabaseQueryResult:
    success: bool
    database_path: str
    query: str
    columns: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    row_count: int = 0
    affected_rows: int | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class DatabaseAdapter:
    """Discover SQLite databases and execute queries against them."""

    def list_databases(
        self,
        root_path: str,
        *,
        target_kind: SessionTargetKind = SessionTargetKind.LOCAL,
        target_ref: str | None = None,
    ) -> DatabaseCatalogSnapshot:
        del target_ref
        if target_kind is SessionTargetKind.SSH:
            return DatabaseCatalogSnapshot(
                databases=[],
                is_available=False,
                message="Remote database discovery is not configured yet.",
            )
        root = Path(root_path).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            return DatabaseCatalogSnapshot(
                databases=[],
                is_available=False,
                message=f"Workspace root '{root}' is not available.",
            )

        databases: list[str] = []
        for path in self._walk_sqlite_files(root):
            databases.append(str(path))
        return DatabaseCatalogSnapshot(
            databases=sorted(databases),
            is_available=True,
            message=None if databases else "No SQLite database files were found.",
        )

    def run_query(
        self,
        database_path: str,
        query: str,
        *,
        target_kind: SessionTargetKind = SessionTargetKind.LOCAL,
        target_ref: str | None = None,
        row_limit: int = 50,
    ) -> DatabaseQueryResult:
        del target_ref
        if target_kind is SessionTargetKind.SSH:
            return DatabaseQueryResult(
                success=False,
                database_path=database_path,
                query=query,
                message="Remote database queries are not configured yet.",
            )

        path = Path(database_path).expanduser().resolve()
        if not path.exists():
            return DatabaseQueryResult(
                success=False,
                database_path=str(path),
                query=query,
                message=f"Database '{path}' does not exist.",
            )

        try:
            with sqlite3.connect(path) as connection:
                cursor = connection.execute(query)
                if cursor.description:
                    columns = [str(column[0]) for column in cursor.description]
                    rows = [
                        [self._stringify_cell(cell) for cell in row]
                        for row in cursor.fetchmany(max(1, int(row_limit)))
                    ]
                    message = f"Returned {len(rows)} row(s) from {path.name}."
                    return DatabaseQueryResult(
                        success=True,
                        database_path=str(path),
                        query=query,
                        columns=columns,
                        rows=rows,
                        row_count=len(rows),
                        message=message,
                    )

                affected_rows = cursor.rowcount if cursor.rowcount >= 0 else 0
                connection.commit()
                return DatabaseQueryResult(
                    success=True,
                    database_path=str(path),
                    query=query,
                    affected_rows=affected_rows,
                    message=f"Affected {affected_rows} row(s) in {path.name}.",
                )
        except sqlite3.Error as exc:
            return DatabaseQueryResult(
                success=False,
                database_path=str(path),
                query=query,
                message=str(exc),
            )

    @staticmethod
    def is_mutating_query(query: str) -> bool:
        normalized = query.strip().lstrip("(").lower()
        first_token = normalized.split(maxsplit=1)[0] if normalized else ""
        return first_token in MUTATING_SQL_PREFIXES

    @staticmethod
    def _walk_sqlite_files(root: Path, *, max_depth: int = 4) -> list[Path]:
        matches: list[Path] = []
        root_depth = len(root.parts)
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if len(path.parts) - root_depth > max_depth:
                continue
            if path.suffix.lower() in SQLITE_SUFFIXES:
                matches.append(path)
        return matches

    @staticmethod
    def _stringify_cell(value: object) -> str:
        if value is None:
            return "NULL"
        return str(value)
