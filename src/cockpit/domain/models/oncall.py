"""On-call ownership and schedule models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from cockpit.shared.enums import (
    ComponentKind,
    OwnershipSubjectKind,
    ResolutionOutcome,
    RotationIntervalKind,
    ScheduleCoverageKind,
    TargetRiskLevel,
    TeamMembershipRole,
)
from cockpit.shared.utils import serialize_contract


@dataclass(slots=True)
class OperatorContactTarget:
    """Delivery-capable contact route for an operator.

    Parameters
    ----------
    channel_id:
        Reference to a configured Stage 2 notification channel.
    label:
        Human-readable operator-facing description.
    enabled:
        Whether the target should be used for paging.
    priority:
        Lower values are preferred first when targets are ordered.
    """

    channel_id: str
    label: str
    enabled: bool = True
    priority: int = 100

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable payload."""

        return serialize_contract(self)


@dataclass(slots=True)
class OperatorPerson:
    """Operator who may receive ownership or pages."""

    id: str
    display_name: str
    handle: str
    enabled: bool = True
    timezone: str = "UTC"
    contact_targets: tuple[OperatorContactTarget, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable payload."""

        return serialize_contract(self)


@dataclass(slots=True)
class OperatorTeam:
    """Team that owns incidents and schedules."""

    id: str
    name: str
    enabled: bool = True
    description: str | None = None
    default_escalation_policy_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable payload."""

        return serialize_contract(self)


@dataclass(slots=True)
class TeamMembership:
    """Membership relation between a person and a team."""

    id: str
    team_id: str
    person_id: str
    role: TeamMembershipRole = TeamMembershipRole.MEMBER
    enabled: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable payload."""

        return serialize_contract(self)


@dataclass(slots=True)
class OwnershipBinding:
    """Bind runtime subjects to an owning team and optional policy override."""

    id: str
    name: str
    team_id: str
    enabled: bool = True
    component_kind: ComponentKind | None = None
    component_id: str | None = None
    subject_kind: OwnershipSubjectKind | None = None
    subject_ref: str | None = None
    risk_level: TargetRiskLevel | None = None
    escalation_policy_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable payload."""

        return serialize_contract(self)


@dataclass(slots=True)
class OnCallSchedule:
    """Defines a schedule envelope for a team."""

    id: str
    team_id: str
    name: str
    timezone: str = "UTC"
    enabled: bool = True
    coverage_kind: ScheduleCoverageKind = ScheduleCoverageKind.ALWAYS
    schedule_config: dict[str, object] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable payload."""

        return serialize_contract(self)


@dataclass(slots=True)
class RotationRule:
    """Defines rotation behavior within a schedule."""

    id: str
    schedule_id: str
    name: str
    participant_ids: tuple[str, ...]
    enabled: bool = True
    anchor_at: datetime | None = None
    interval_kind: RotationIntervalKind = RotationIntervalKind.DAYS
    interval_count: int = 1
    handoff_time: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable payload."""

        return serialize_contract(self)


@dataclass(slots=True)
class ScheduleOverride:
    """Temporary replacement for a resolved on-call operator."""

    id: str
    schedule_id: str
    replacement_person_id: str
    starts_at: datetime
    ends_at: datetime
    replaced_person_id: str | None = None
    reason: str = ""
    priority: int = 100
    enabled: bool = True
    actor: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable payload."""

        return serialize_contract(self)


@dataclass(slots=True, frozen=True)
class OwnershipResolution:
    """Result of resolving incident ownership."""

    outcome: ResolutionOutcome
    team_id: str | None = None
    escalation_policy_id: str | None = None
    binding_id: str | None = None
    explanation: str = ""

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable payload."""

        return serialize_contract(self)


@dataclass(slots=True, frozen=True)
class OnCallResolution:
    """Result of resolving the active on-call person for a team."""

    outcome: ResolutionOutcome
    team_id: str
    schedule_id: str | None = None
    rotation_id: str | None = None
    person_id: str | None = None
    override_id: str | None = None
    explanation: str = ""

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable payload."""

        return serialize_contract(self)
