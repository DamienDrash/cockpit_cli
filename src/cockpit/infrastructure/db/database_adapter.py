"""Structured local database discovery and query execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import shlex
import sqlite3

from cockpit.infrastructure.ssh.command_runner import SSHCommandRunner
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
DESTRUCTIVE_SQL_PREFIXES = {
    "alter",
    "attach",
    "detach",
    "drop",
    "reindex",
    "replace",
    "truncate",
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

    def __init__(self, ssh_command_runner: SSHCommandRunner | None = None) -> None:
        self._ssh_command_runner = ssh_command_runner

    def list_databases(
        self,
        root_path: str,
        *,
        target_kind: SessionTargetKind = SessionTargetKind.LOCAL,
        target_ref: str | None = None,
    ) -> DatabaseCatalogSnapshot:
        if target_kind is SessionTargetKind.SSH:
            return self._list_remote_databases(root_path, target_ref)
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
        if target_kind is SessionTargetKind.SSH:
            return self._run_remote_query(
                database_path,
                query,
                target_ref=target_ref,
                row_limit=row_limit,
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
    def is_destructive_query(query: str) -> bool:
        normalized = query.strip().lstrip("(").lower()
        first_token = normalized.split(maxsplit=1)[0] if normalized else ""
        return first_token in DESTRUCTIVE_SQL_PREFIXES

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

    def _list_remote_databases(
        self,
        root_path: str,
        target_ref: str | None,
    ) -> DatabaseCatalogSnapshot:
        if not target_ref:
            return DatabaseCatalogSnapshot(
                databases=[],
                is_available=False,
                message="No SSH target is configured for this workspace.",
            )
        if self._ssh_command_runner is None:
            return DatabaseCatalogSnapshot(
                databases=[],
                is_available=False,
                message="SSH database discovery is not configured.",
            )
        script = "\n".join(
            [
                "import json",
                "import os",
                "import sys",
                "root = sys.argv[1]",
                "suffixes = ('.db', '.sqlite', '.sqlite3')",
                "matches = []",
                "root_depth = len(os.path.abspath(root).split(os.sep))",
                "for current_root, dirs, files in os.walk(root):",
                "    current_depth = len(os.path.abspath(current_root).split(os.sep)) - root_depth",
                "    if current_depth > 4:",
                "        dirs[:] = []",
                "        continue",
                "    for filename in files:",
                "        if filename.lower().endswith(suffixes):",
                "            matches.append(os.path.join(current_root, filename))",
                "print(json.dumps(sorted(matches)))",
            ]
        )
        result = self._ssh_command_runner.run(
            target_ref,
            f"python3 -c {shlex.quote(script)} -- {shlex.quote(root_path)}",
        )
        if not result.is_available:
            return DatabaseCatalogSnapshot(
                databases=[],
                is_available=False,
                message=result.message or "SSH is unavailable.",
            )
        if result.returncode != 0:
            return DatabaseCatalogSnapshot(
                databases=[],
                is_available=False,
                message=result.stderr.strip() or "Remote database discovery failed.",
            )
        try:
            payload = json.loads(result.stdout or "[]")
        except json.JSONDecodeError:
            payload = []
        databases = [str(item) for item in payload if isinstance(item, str)]
        return DatabaseCatalogSnapshot(
            databases=databases,
            is_available=True,
            message=None if databases else "No SQLite database files were found.",
        )

    def _run_remote_query(
        self,
        database_path: str,
        query: str,
        *,
        target_ref: str | None,
        row_limit: int,
    ) -> DatabaseQueryResult:
        if not target_ref:
            return DatabaseQueryResult(
                success=False,
                database_path=database_path,
                query=query,
                message="No SSH target is configured for this workspace.",
            )
        if self._ssh_command_runner is None:
            return DatabaseQueryResult(
                success=False,
                database_path=database_path,
                query=query,
                message="SSH database queries are not configured.",
            )
        script = "\n".join(
            [
                "import json",
                "import sqlite3",
                "import sys",
                "path, query, limit = sys.argv[1], sys.argv[2], int(sys.argv[3])",
                "payload = {'success': False, 'database_path': path, 'query': query}",
                "try:",
                "    with sqlite3.connect(path) as connection:",
                "        cursor = connection.execute(query)",
                "        if cursor.description:",
                "            columns = [str(column[0]) for column in cursor.description]",
                "            rows = [[('NULL' if value is None else str(value)) for value in row] for row in cursor.fetchmany(max(1, limit))]",
                "            payload.update({'success': True, 'columns': columns, 'rows': rows, 'row_count': len(rows), 'message': f'Returned {len(rows)} row(s) from {path}.'})",
                "        else:",
                "            connection.commit()",
                "            affected = cursor.rowcount if cursor.rowcount >= 0 else 0",
                "            payload.update({'success': True, 'affected_rows': affected, 'message': f'Affected {affected} row(s) in {path}.'})",
                "except sqlite3.Error as exc:",
                "    payload['message'] = str(exc)",
                "print(json.dumps(payload))",
            ]
        )
        result = self._ssh_command_runner.run(
            target_ref,
            " ".join(
                [
                    "python3 -c",
                    shlex.quote(script),
                    "--",
                    shlex.quote(database_path),
                    shlex.quote(query),
                    str(max(1, int(row_limit))),
                ]
            ),
            timeout_seconds=10,
        )
        if not result.is_available:
            return DatabaseQueryResult(
                success=False,
                database_path=database_path,
                query=query,
                message=result.message or "SSH is unavailable.",
            )
        if result.returncode != 0:
            return DatabaseQueryResult(
                success=False,
                database_path=database_path,
                query=query,
                message=result.stderr.strip() or "Remote database query failed.",
            )
        try:
            payload = json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            return DatabaseQueryResult(
                success=False,
                database_path=database_path,
                query=query,
                message="Remote database query returned invalid JSON.",
            )
        return DatabaseQueryResult(
            success=bool(payload.get("success")),
            database_path=str(payload.get("database_path", database_path)),
            query=str(payload.get("query", query)),
            columns=[
                str(column)
                for column in payload.get("columns", [])
                if isinstance(column, str)
            ],
            rows=[
                [str(cell) for cell in row if isinstance(row, list)]
                for row in payload.get("rows", [])
                if isinstance(row, list)
            ],
            row_count=int(payload.get("row_count", 0) or 0),
            affected_rows=(
                int(payload["affected_rows"])
                if payload.get("affected_rows") is not None
                else None
            ),
            message=(
                str(payload["message"])
                if payload.get("message") is not None
                else None
            ),
        )
