"""Datasource models."""

from __future__ import annotations

from dataclasses import dataclass, field

from cockpit.core.enums import SessionTargetKind
from cockpit.core.utils import serialize_contract


@dataclass(slots=True)
class DataSourceProfile:
    id: str
    name: str
    backend: str
    driver: str | None = None
    connection_url: str | None = None
    target_kind: SessionTargetKind = SessionTargetKind.LOCAL
    target_ref: str | None = None
    database_name: str | None = None
    risk_level: str = "dev"
    capabilities: list[str] = field(default_factory=list)
    options: dict[str, object] = field(default_factory=dict)
    secret_refs: dict[str, object] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    managed_by_plugin: str | None = None
    enabled: bool = True

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class DataSourceOperationResult:
    success: bool
    profile_id: str
    backend: str
    operation: str
    columns: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    message: str | None = None
    affected_rows: int | None = None
    output_text: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)
