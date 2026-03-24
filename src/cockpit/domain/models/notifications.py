"""Notification, routing, suppression, and delivery models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from cockpit.shared.enums import (
    ComponentKind,
    IncidentSeverity,
    IncidentStatus,
    NotificationChannelKind,
    NotificationDeliveryStatus,
    NotificationEventClass,
    NotificationStatus,
    TargetRiskLevel,
)
from cockpit.shared.utils import serialize_contract


@dataclass(slots=True)
class NotificationChannel:
    """Persisted outbound or internal notification destination."""

    id: str
    name: str
    kind: NotificationChannelKind
    enabled: bool = True
    target: dict[str, object] = field(default_factory=dict)
    secret_refs: dict[str, str] = field(default_factory=dict)
    timeout_seconds: int = 5
    max_attempts: int = 3
    base_backoff_seconds: int = 2
    max_backoff_seconds: int = 30
    risk_level: TargetRiskLevel = TargetRiskLevel.DEV
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class NotificationRule:
    """Routing rule for notification channel selection."""

    id: str
    name: str
    enabled: bool = True
    event_classes: tuple[NotificationEventClass, ...] = ()
    component_kinds: tuple[ComponentKind, ...] = ()
    severities: tuple[IncidentSeverity, ...] = ()
    risk_levels: tuple[TargetRiskLevel, ...] = ()
    incident_statuses: tuple[IncidentStatus, ...] = ()
    channel_ids: tuple[str, ...] = ()
    delivery_priority: int = 100
    dedupe_window_seconds: int = 300
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class NotificationSuppressionRule:
    """Time-bounded suppression rule for noisy notifications."""

    id: str
    name: str
    enabled: bool = True
    reason: str = ""
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    event_classes: tuple[NotificationEventClass, ...] = ()
    component_kinds: tuple[ComponentKind, ...] = ()
    severities: tuple[IncidentSeverity, ...] = ()
    risk_levels: tuple[TargetRiskLevel, ...] = ()
    actor: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class NotificationRecord:
    """Structured operator notification persisted before delivery."""

    id: str
    event_class: NotificationEventClass
    severity: IncidentSeverity
    risk_level: TargetRiskLevel
    title: str
    summary: str
    status: NotificationStatus
    dedupe_key: str
    incident_id: str | None = None
    component_id: str | None = None
    component_kind: ComponentKind | None = None
    incident_status: IncidentStatus | None = None
    source_event_id: str | None = None
    suppression_reason: str | None = None
    payload: dict[str, object] = field(default_factory=dict)
    created_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class NotificationDeliveryAttempt:
    """Persisted delivery attempt for a notification and channel."""

    id: str
    notification_id: str
    channel_id: str
    attempt_number: int
    status: NotificationDeliveryStatus
    scheduled_for: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_class: str | None = None
    error_message: str | None = None
    response_payload: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class NotificationCandidate:
    """In-memory normalized notification candidate before persistence."""

    event_class: NotificationEventClass
    severity: IncidentSeverity
    risk_level: TargetRiskLevel
    title: str
    summary: str
    dedupe_key: str
    incident_id: str | None = None
    component_id: str | None = None
    component_kind: ComponentKind | None = None
    incident_status: IncidentStatus | None = None
    source_event_id: str | None = None
    forced_channel_ids: tuple[str, ...] = ()
    payload: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True, frozen=True)
class NotificationRoutingDecision:
    """Routing decision after rule and suppression evaluation."""

    candidate: NotificationCandidate
    channel_ids: tuple[str, ...]
    dedupe_window_seconds: int
    suppressed: bool
    suppression_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)
