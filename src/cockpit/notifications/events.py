"""Notification and suppression domain events."""

from __future__ import annotations

from dataclasses import dataclass

from cockpit.core.events.base import DomainEvent
from cockpit.core.enums import (
    IncidentSeverity,
    NotificationChannelKind,
    NotificationDeliveryStatus,
    NotificationEventClass,
    NotificationStatus,
    TargetRiskLevel,
)


@dataclass(slots=True, kw_only=True)
class NotificationQueued(DomainEvent):
    notification_id: str
    event_class: NotificationEventClass
    severity: IncidentSeverity
    risk_level: TargetRiskLevel
    suppressed: bool = False


@dataclass(slots=True, kw_only=True)
class NotificationSuppressed(DomainEvent):
    notification_id: str
    event_class: NotificationEventClass
    reason: str


@dataclass(slots=True, kw_only=True)
class NotificationDeliveryStarted(DomainEvent):
    delivery_id: str
    notification_id: str
    channel_id: str
    channel_kind: NotificationChannelKind
    attempt_number: int


@dataclass(slots=True, kw_only=True)
class NotificationDelivered(DomainEvent):
    delivery_id: str
    notification_id: str
    channel_id: str
    channel_kind: NotificationChannelKind
    status: NotificationDeliveryStatus


@dataclass(slots=True, kw_only=True)
class NotificationDeliveryFailed(DomainEvent):
    delivery_id: str
    notification_id: str
    channel_id: str
    channel_kind: NotificationChannelKind
    status: NotificationDeliveryStatus
    error_message: str


@dataclass(slots=True, kw_only=True)
class NotificationStatusChanged(DomainEvent):
    notification_id: str
    previous_status: NotificationStatus | None
    new_status: NotificationStatus
    message: str


@dataclass(slots=True, kw_only=True)
class SuppressionRuleChanged(DomainEvent):
    suppression_rule_id: str
    enabled: bool
    message: str
