"""Database response step executor."""

from __future__ import annotations

from cockpit.datasources.services.datasource_service import DataSourceService
from cockpit.datasources.models.datasource import DataSourceOperationResult
from cockpit.datasources.adapters.database_adapter import (
    DatabaseAdapter,
    DatabaseQueryResult,
)
from cockpit.infrastructure.runbooks.executors.base import (
    ExecutorArtifact,
    ExecutorContext,
    ExecutorResult,
)
from cockpit.core.enums import SessionTargetKind


class DatabaseStepExecutor:
    """Execute database steps through datasource or direct SQLite paths."""

    def __init__(
        self,
        *,
        database_adapter: DatabaseAdapter,
        datasource_service: DataSourceService,
    ) -> None:
        self._database_adapter = database_adapter
        self._datasource_service = datasource_service

    def execute(self, context: ExecutorContext) -> ExecutorResult:
        statement = str(context.resolved_config.get("statement", "")).strip()
        profile_id = context.resolved_config.get("profile_id")
        if isinstance(profile_id, str) and profile_id.strip():
            result = self._datasource_service.run_statement(
                profile_id.strip(),
                statement,
                operation=str(context.resolved_config.get("operation", "query")),
                row_limit=int(context.resolved_config.get("row_limit", 50) or 50),
            )
            return self._from_datasource_result(result)

        database_path = str(context.resolved_config.get("database_path", "")).strip()
        target_kind = SessionTargetKind(
            str(context.resolved_config.get("target_kind", "local"))
        )
        target_ref = context.resolved_config.get("target_ref")
        result = self._database_adapter.run_query(
            database_path,
            statement,
            target_kind=target_kind,
            target_ref=str(target_ref)
            if isinstance(target_ref, str) and target_ref
            else None,
            row_limit=int(context.resolved_config.get("row_limit", 50) or 50),
        )
        return self._from_database_result(result)

    def _from_database_result(self, result: DatabaseQueryResult) -> ExecutorResult:
        payload = result.to_dict()
        return ExecutorResult(
            success=result.success,
            summary=result.message or "database step executed",
            payload=payload,
            artifacts=(
                ExecutorArtifact(
                    kind="db_result",
                    label=result.database_path,
                    summary=result.message,
                    payload=payload,
                ),
            ),
            error_message=None if result.success else result.message,
        )

    def _from_datasource_result(
        self, result: DataSourceOperationResult
    ) -> ExecutorResult:
        payload = result.to_dict()
        return ExecutorResult(
            success=result.success,
            summary=result.message or "datasource step executed",
            payload=payload,
            artifacts=(
                ExecutorArtifact(
                    kind="db_result",
                    label=result.subject_ref,
                    summary=result.message,
                    payload=payload,
                ),
            ),
            error_message=None if result.success else result.message,
        )
