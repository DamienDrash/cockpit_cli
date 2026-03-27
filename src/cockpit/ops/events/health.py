"""Health, incident, recovery, and policy domain events."""

from __future__ import annotations

from dataclasses import dataclass, field

from cockpit.core.events.base import DomainEvent, RuntimeEvent
from cockpit.core.enums import (
    ComponentKind,
    GuardActionKind,
    GuardDecisionOutcome,
    HealthStatus,
    IncidentSeverity,
    IncidentStatus,
    RecoveryAttemptStatus,
    WatchProbeOutcome,
)


@dataclass(slots=True, kw_only=True)
class ComponentHealthChanged(DomainEvent):
    component_id: str
    component_kind: ComponentKind
    previous_status: HealthStatus | None = None
    new_status: HealthStatus
    reason: str


@dataclass(slots=True, kw_only=True)
class IncidentOpened(DomainEvent):
    incident_id: str
    component_id: str
    component_kind: ComponentKind
    severity: IncidentSeverity
    title: str


@dataclass(slots=True, kw_only=True)
class IncidentStatusChanged(DomainEvent):
    incident_id: str
    component_id: str
    component_kind: ComponentKind
    previous_status: IncidentStatus | None = None
    new_status: IncidentStatus
    message: str


@dataclass(slots=True, kw_only=True)
class RecoveryAttemptRecorded(DomainEvent):
    attempt_id: str
    incident_id: str
    component_id: str
    component_kind: ComponentKind
    status: RecoveryAttemptStatus
    action: str
    attempt_number: int


@dataclass(slots=True, kw_only=True)
class ComponentQuarantined(DomainEvent):
    component_id: str
    component_kind: ComponentKind
    reason: str


@dataclass(slots=True, kw_only=True)
class ComponentQuarantineCleared(DomainEvent):
    component_id: str
    component_kind: ComponentKind
    reason: str


@dataclass(slots=True, kw_only=True)
class GuardDecisionRecorded(DomainEvent):
    command_id: str
    action_kind: GuardActionKind
    outcome: GuardDecisionOutcome
    explanation: str


@dataclass(slots=True, kw_only=True)
class TaskHeartbeatMissed(RuntimeEvent):
    task_name: str
    heartbeat_timeout_seconds: float
    age_seconds: float
    restartable: bool
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True, kw_only=True)
class TaskExitedUnexpectedly(RuntimeEvent):
    task_name: str
    restartable: bool
    error_message: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True, kw_only=True)
class TunnelFailureDetected(RuntimeEvent):
    profile_id: str
    target_ref: str
    remote_host: str
    remote_port: int
    reconnect_count: int
    reason: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True, kw_only=True)
class ComponentWatchObserved(RuntimeEvent):
    component_id: str
    component_kind: ComponentKind
    outcome: WatchProbeOutcome
    status: str
    summary: str
    target_ref: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
