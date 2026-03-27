"""Escalation policy and engagement runtime models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from cockpit.core.enums import (
    EngagementDeliveryPurpose,
    EngagementStatus,
    EscalationTargetKind,
)
from cockpit.core.utils import serialize_contract


@dataclass(slots=True)
class EscalationTarget:
    """Addressable escalation target abstraction."""

    kind: EscalationTargetKind
    ref: str
    display_name: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable payload."""

        return serialize_contract(self)


@dataclass(slots=True)
class EscalationPolicy:
    """Ordered escalation policy definition."""

    id: str
    name: str
    enabled: bool = True
    default_ack_timeout_seconds: int = 900
    default_repeat_page_seconds: int = 300
    max_repeat_pages: int = 2
    terminal_behavior: str = "exhaust"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable payload."""

        return serialize_contract(self)


@dataclass(slots=True)
class EscalationStep:
    """Single escalation step within a policy."""

    id: str
    policy_id: str
    step_index: int
    target_kind: EscalationTargetKind
    target_ref: str
    ack_timeout_seconds: int | None = None
    repeat_page_seconds: int | None = None
    max_repeat_pages: int | None = None
    reminder_enabled: bool = True
    stop_on_ack: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable payload."""

        return serialize_contract(self)


@dataclass(slots=True)
class IncidentEngagement:
    """Active escalation runtime attached to an incident."""

    id: str
    incident_id: str
    incident_component_id: str
    team_id: str | None
    policy_id: str | None
    status: EngagementStatus = EngagementStatus.ACTIVE
    current_step_index: int = 0
    current_target_kind: EscalationTargetKind | None = None
    current_target_ref: str | None = None
    resolved_person_id: str | None = None
    acknowledged_by: str | None = None
    acknowledged_at: datetime | None = None
    handoff_count: int = 0
    repeat_page_count: int = 0
    next_action_at: datetime | None = None
    ack_deadline_at: datetime | None = None
    last_page_at: datetime | None = None
    exhausted: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
    closed_at: datetime | None = None
    payload: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable payload."""

        return serialize_contract(self)


@dataclass(slots=True)
class EngagementTimelineEntry:
    """Structured event in an engagement timeline."""

    id: int | None
    engagement_id: str
    incident_id: str
    event_type: str
    message: str
    recorded_at: datetime
    payload: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable payload."""

        return serialize_contract(self)


@dataclass(slots=True)
class EngagementDeliveryLink:
    """Correlation record between engagement actions and notifications."""

    id: int | None
    engagement_id: str
    notification_id: str
    delivery_id: str | None = None
    purpose: EngagementDeliveryPurpose = EngagementDeliveryPurpose.PAGE
    step_index: int = 0
    created_at: datetime | None = None
    payload: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable payload."""

        return serialize_contract(self)
