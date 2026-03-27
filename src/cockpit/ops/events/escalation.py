"""On-call and escalation domain events."""

from __future__ import annotations

from dataclasses import dataclass

from cockpit.core.events.base import DomainEvent
from cockpit.core.enums import EngagementDeliveryPurpose, EngagementStatus


@dataclass(slots=True, kw_only=True)
class IncidentEngagementCreated(DomainEvent):
    engagement_id: str
    incident_id: str
    team_id: str
    policy_id: str


@dataclass(slots=True, kw_only=True)
class EngagementStatusChanged(DomainEvent):
    engagement_id: str
    incident_id: str
    previous_status: EngagementStatus | None
    new_status: EngagementStatus
    message: str


@dataclass(slots=True, kw_only=True)
class EngagementPaged(DomainEvent):
    engagement_id: str
    incident_id: str
    notification_id: str
    purpose: EngagementDeliveryPurpose
    step_index: int
    target_ref: str


@dataclass(slots=True, kw_only=True)
class EngagementAcknowledged(DomainEvent):
    engagement_id: str
    incident_id: str
    actor: str


@dataclass(slots=True, kw_only=True)
class EngagementHandedOff(DomainEvent):
    engagement_id: str
    incident_id: str
    actor: str
    new_target_ref: str


@dataclass(slots=True, kw_only=True)
class EngagementEscalated(DomainEvent):
    engagement_id: str
    incident_id: str
    step_index: int
    target_ref: str


@dataclass(slots=True, kw_only=True)
class EngagementExhausted(DomainEvent):
    engagement_id: str
    incident_id: str
    message: str
