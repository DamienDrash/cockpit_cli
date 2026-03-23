"""Health, incident, and recovery models for operator-grade supervision."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from cockpit.shared.enums import (
    ComponentKind,
    HealthStatus,
    IncidentSeverity,
    IncidentStatus,
    RecoveryAttemptStatus,
    SessionTargetKind,
)
from cockpit.shared.utils import serialize_contract


@dataclass(slots=True, frozen=True)
class ComponentRef:
    """Stable runtime identity for a supervised component.

    Parameters
    ----------
    component_id:
        Persistent component key, for example ``pty:work-panel``.
    kind:
        Component type used for policy routing and diagnostics grouping.
    display_name:
        Human-readable operator label.
    """

    component_id: str
    kind: ComponentKind
    display_name: str

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class ComponentHealthState:
    """Current health state for a supervised runtime component."""

    component_id: str
    component_kind: ComponentKind
    display_name: str
    status: HealthStatus
    workspace_id: str | None = None
    session_id: str | None = None
    target_kind: SessionTargetKind = SessionTargetKind.LOCAL
    target_ref: str | None = None
    last_heartbeat_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_recovery_at: datetime | None = None
    next_recovery_at: datetime | None = None
    cooldown_until: datetime | None = None
    consecutive_failures: int = 0
    exhaustion_count: int = 0
    quarantined: bool = False
    quarantine_reason: str | None = None
    last_incident_id: str | None = None
    payload: dict[str, object] = field(default_factory=dict)
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class IncidentRecord:
    """Persisted incident record."""

    id: str
    component_id: str
    component_kind: ComponentKind
    severity: IncidentSeverity
    status: IncidentStatus
    title: str
    summary: str
    workspace_id: str | None = None
    session_id: str | None = None
    opened_at: datetime | None = None
    updated_at: datetime | None = None
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None
    closed_at: datetime | None = None
    payload: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class IncidentTimelineEntry:
    """Structured timeline event linked to an incident."""

    id: int | None
    incident_id: str
    event_type: str
    message: str
    recorded_at: datetime
    payload: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class RecoveryPolicy:
    """Deterministic recovery policy for a supervised component family."""

    component_kind: ComponentKind
    max_attempts: int
    retry_window_seconds: int
    base_backoff_seconds: int
    max_backoff_seconds: int
    cooldown_seconds: int
    quarantine_after_exhaustion: bool = True
    non_recoverable_markers: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class RecoveryAttempt:
    """Persisted recovery attempt entry."""

    id: str
    incident_id: str
    component_id: str
    attempt_number: int
    status: RecoveryAttemptStatus
    trigger: str
    action: str
    backoff_ms: int = 0
    scheduled_for: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    payload: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)
