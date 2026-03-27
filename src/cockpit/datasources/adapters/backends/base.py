"""Datasource adapter contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from cockpit.datasources.models.datasource import (
    DataSourceOperationResult,
    DataSourceProfile,
)


@dataclass(slots=True, frozen=True)
class DataSourceInspection:
    success: bool
    profile_id: str
    backend: str
    summary: str
    details: dict[str, object]

    def to_operation_result(self) -> DataSourceOperationResult:
        return DataSourceOperationResult(
            success=self.success,
            profile_id=self.profile_id,
            backend=self.backend,
            operation="inspect",
            message=self.summary,
            metadata=dict(self.details),
        )


class DataSourceAdapter(Protocol):
    def inspect(self, profile: DataSourceProfile) -> DataSourceInspection: ...

    def run(
        self,
        profile: DataSourceProfile,
        statement: str,
        *,
        operation: str = "query",
        row_limit: int = 50,
    ) -> DataSourceOperationResult: ...
