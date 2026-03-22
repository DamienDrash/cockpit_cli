"""Redis datasource adapter."""

from __future__ import annotations

import shlex

from cockpit.domain.models.datasource import DataSourceOperationResult, DataSourceProfile
from cockpit.infrastructure.datasources.base import DataSourceInspection

try:
    import redis
except Exception:  # pragma: no cover - optional dependency guard
    redis = None


class RedisDatasourceAdapter:
    def inspect(self, profile: DataSourceProfile) -> DataSourceInspection:
        if redis is None:
            return DataSourceInspection(
                success=False,
                profile_id=profile.id,
                backend=profile.backend,
                summary="redis-py is not installed.",
                details={},
            )
        try:
            client = redis.from_url(profile.connection_url or "redis://localhost:6379/0")
            info = client.info()
            return DataSourceInspection(
                success=True,
                profile_id=profile.id,
                backend=profile.backend,
                summary=f"Connected to Redis datasource {profile.name}.",
                details={
                    "redis_version": str(info.get("redis_version", "")),
                    "db_size": int(client.dbsize()),
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
        del row_limit
        if redis is None:
            return DataSourceOperationResult(
                success=False,
                profile_id=profile.id,
                backend=profile.backend,
                operation=operation,
                message="redis-py is not installed.",
            )
        try:
            command = shlex.split(statement)
            if not command:
                raise ValueError("Redis statement is empty.")
            client = redis.from_url(profile.connection_url or "redis://localhost:6379/0")
            result = client.execute_command(*command)
            output = self._stringify_result(result)
            return DataSourceOperationResult(
                success=True,
                profile_id=profile.id,
                backend=profile.backend,
                operation=operation,
                output_text=output,
                message=f"Executed Redis command {' '.join(command[:2])}.",
            )
        except Exception as exc:
            return DataSourceOperationResult(
                success=False,
                profile_id=profile.id,
                backend=profile.backend,
                operation=operation,
                message=str(exc),
            )

    def _stringify_result(self, value: object) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        if isinstance(value, (list, tuple)):
            return "\n".join(self._stringify_result(item) for item in value)
        return str(value)
