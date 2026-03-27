"""SQLAlchemy-backed datasource adapter."""

from __future__ import annotations

from dataclasses import dataclass

from cockpit.datasources.models.datasource import (
    DataSourceOperationResult,
    DataSourceProfile,
)
from cockpit.datasources.adapters.backends.base import DataSourceInspection

try:
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.exc import SQLAlchemyError
except Exception:  # pragma: no cover - optional dependency guard
    create_engine = None
    inspect = None
    text = None
    SQLAlchemyError = Exception


SQL_BACKENDS = {
    "sqlite",
    "postgres",
    "postgresql",
    "mysql",
    "mariadb",
    "mssql",
    "duckdb",
    "bigquery",
    "snowflake",
}


@dataclass(slots=True)
class SQLAlchemyDatasourceAdapter:
    """Run SQL-style datasource operations through SQLAlchemy."""

    def inspect(self, profile: DataSourceProfile) -> DataSourceInspection:
        if create_engine is None or inspect is None:
            return DataSourceInspection(
                success=False,
                profile_id=profile.id,
                backend=profile.backend,
                summary="SQLAlchemy is not installed.",
                details={},
            )
        try:
            engine = self._engine(profile)
            with engine.connect() as connection:
                inspector = inspect(connection)
                schema_names = []
                try:
                    schema_names = [
                        str(name) for name in inspector.get_schema_names()[:12]
                    ]
                except Exception:
                    schema_names = []
                table_names = []
                try:
                    table_names = [
                        str(name) for name in inspector.get_table_names()[:25]
                    ]
                except Exception:
                    table_names = []
            return DataSourceInspection(
                success=True,
                profile_id=profile.id,
                backend=profile.backend,
                summary=f"Connected to {profile.name}.",
                details={
                    "schemas": schema_names,
                    "tables": table_names,
                    "dialect": engine.dialect.name,
                    "driver": engine.dialect.driver,
                },
            )
        except Exception as exc:
            return DataSourceInspection(
                success=False,
                profile_id=profile.id,
                backend=profile.backend,
                summary=str(exc),
                details={},
            )

    def run(
        self,
        profile: DataSourceProfile,
        statement: str,
        *,
        operation: str = "query",
        row_limit: int = 50,
    ) -> DataSourceOperationResult:
        if create_engine is None or text is None:
            return DataSourceOperationResult(
                success=False,
                profile_id=profile.id,
                backend=profile.backend,
                operation=operation,
                message="SQLAlchemy is not installed.",
            )
        try:
            engine = self._engine(profile)
            with engine.begin() as connection:
                result = connection.execute(text(statement))
                if result.returns_rows:
                    rows = result.fetchmany(max(1, int(row_limit)))
                    return DataSourceOperationResult(
                        success=True,
                        profile_id=profile.id,
                        backend=profile.backend,
                        operation=operation,
                        columns=[str(column) for column in result.keys()],
                        rows=[
                            [self._stringify_cell(cell) for cell in row] for row in rows
                        ],
                        message=f"Returned {len(rows)} row(s).",
                    )
                affected_rows = (
                    result.rowcount
                    if result.rowcount is not None and result.rowcount >= 0
                    else 0
                )
                return DataSourceOperationResult(
                    success=True,
                    profile_id=profile.id,
                    backend=profile.backend,
                    operation=operation,
                    affected_rows=affected_rows,
                    message=f"Affected {affected_rows} row(s).",
                )
        except SQLAlchemyError as exc:
            return DataSourceOperationResult(
                success=False,
                profile_id=profile.id,
                backend=profile.backend,
                operation=operation,
                message=str(exc),
            )
        except Exception as exc:
            return DataSourceOperationResult(
                success=False,
                profile_id=profile.id,
                backend=profile.backend,
                operation=operation,
                message=str(exc),
            )

    @staticmethod
    def _stringify_cell(value: object) -> str:
        if value is None:
            return "NULL"
        return str(value)

    def _engine(self, profile: DataSourceProfile):
        if not profile.connection_url:
            raise ValueError(
                f"Datasource '{profile.name}' is missing a connection URL."
            )
        return create_engine(profile.connection_url, future=True)
