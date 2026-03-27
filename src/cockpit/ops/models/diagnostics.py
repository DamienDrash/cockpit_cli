"""Structured diagnostics models for Stage 1 operational surfaces."""

from __future__ import annotations

from dataclasses import dataclass, field

from cockpit.core.enums import GuardDecisionOutcome, OperationFamily, TargetRiskLevel
from cockpit.core.utils import serialize_contract


@dataclass(slots=True)
class DockerContainerDiagnostics:
    """Structured Docker container diagnostics payload."""

    container_id: str
    name: str
    image: str
    state: str
    status: str
    health: str | None = None
    restart_policy: str | None = None
    exit_code: int | None = None
    restart_count: int | None = None
    last_error: str | None = None
    last_finished_at: str | None = None
    recent_logs: list[str] = field(default_factory=list)
    risk_level: TargetRiskLevel = TargetRiskLevel.DEV
    last_incident_id: str | None = None
    last_incident_status: str | None = None

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class DatasourceDiagnostics:
    """Structured datasource diagnostics payload."""

    profile_id: str
    name: str
    backend: str
    reachable: str
    target: str
    tunnel_alive: bool | None = None
    risk_level: TargetRiskLevel = TargetRiskLevel.DEV
    capabilities: list[str] = field(default_factory=list)
    recent_failure_count: int = 0
    last_message: str | None = None
    last_operation: str | None = None
    last_guard_outcome: GuardDecisionOutcome | None = None
    safety_hints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class CurlRequestDiagnostics:
    """Structured HTTP request diagnostics payload."""

    subject_ref: str
    method: str
    url: str
    risk_level: TargetRiskLevel
    last_status_code: int | None = None
    last_duration_ms: int | None = None
    success: bool | None = None
    failure_streak: int = 0
    placeholder_names: list[str] = field(default_factory=list)
    last_guard_outcome: GuardDecisionOutcome | None = None
    recent_messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class OperationDiagnosticRecord:
    """Persisted diagnostic history item for operator surfaces."""

    id: int | None
    operation_family: OperationFamily
    component_id: str
    subject_ref: str
    success: bool
    severity: str
    summary: str
    recorded_at: str
    payload: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)
