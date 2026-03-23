"""Incident Center application service."""

from __future__ import annotations

from dataclasses import dataclass

from cockpit.application.services.self_healing_service import SelfHealingService
from cockpit.domain.models.health import IncidentRecord, IncidentTimelineEntry, RecoveryAttempt
from cockpit.infrastructure.persistence.ops_repositories import (
    ComponentHealthRepository,
    IncidentRepository,
    RecoveryAttemptRepository,
)
from cockpit.shared.enums import ComponentKind, IncidentSeverity, IncidentStatus
from cockpit.shared.utils import utc_now


@dataclass(slots=True, frozen=True)
class IncidentDetail:
    """Structured incident detail payload for admin surfaces."""

    incident: IncidentRecord
    timeline: list[IncidentTimelineEntry]
    recovery_attempts: list[RecoveryAttempt]
    current_health: dict[str, object] | None


class IncidentService:
    """Provide list/detail/action operations for incidents."""

    def __init__(
        self,
        *,
        incident_repository: IncidentRepository,
        recovery_attempt_repository: RecoveryAttemptRepository,
        component_health_repository: ComponentHealthRepository,
        self_healing_service: SelfHealingService,
    ) -> None:
        self._incident_repository = incident_repository
        self._recovery_attempt_repository = recovery_attempt_repository
        self._component_health_repository = component_health_repository
        self._self_healing_service = self_healing_service

    def list_incidents(
        self,
        *,
        limit: int = 50,
        statuses: tuple[IncidentStatus, ...] | None = None,
        severities: tuple[IncidentSeverity, ...] | None = None,
        component_kind: ComponentKind | None = None,
        search: str | None = None,
    ) -> list[IncidentRecord]:
        return self._incident_repository.list_recent(
            limit=limit,
            statuses=statuses,
            severities=severities,
            component_kind=component_kind,
            search=search,
        )

    def get_incident_detail(self, incident_id: str) -> IncidentDetail | None:
        incident = self._incident_repository.get(incident_id)
        if incident is None:
            return None
        health_state = self._component_health_repository.get(incident.component_id)
        return IncidentDetail(
            incident=incident,
            timeline=self._incident_repository.list_timeline(incident_id),
            recovery_attempts=self._recovery_attempt_repository.list_for_incident(incident_id),
            current_health=health_state.to_dict() if health_state is not None else None,
        )

    def acknowledge_incident(self, incident_id: str) -> IncidentRecord:
        incident = self._require_incident(incident_id)
        incident.status = IncidentStatus.ACKNOWLEDGED
        incident.acknowledged_at = utc_now()
        incident.updated_at = incident.acknowledged_at
        self._incident_repository.save(incident)
        self._incident_repository.add_timeline_entry(
            incident_id=incident.id,
            event_type="acknowledged",
            message="Incident acknowledged by operator.",
        )
        return incident

    def close_incident(self, incident_id: str) -> IncidentRecord:
        incident = self._require_incident(incident_id)
        incident.status = IncidentStatus.CLOSED
        incident.closed_at = utc_now()
        incident.updated_at = incident.closed_at
        self._incident_repository.save(incident)
        self._incident_repository.add_timeline_entry(
            incident_id=incident.id,
            event_type="closed",
            message="Incident closed by operator.",
        )
        return incident

    def reset_quarantine(self, component_id: str) -> None:
        self._self_healing_service.reset_quarantine(component_id, reason="operator reset")

    def retry_component(self, component_id: str) -> bool:
        return self._self_healing_service.retry_component(component_id)

    def _require_incident(self, incident_id: str) -> IncidentRecord:
        incident = self._incident_repository.get(incident_id)
        if incident is None:
            raise LookupError(f"Incident '{incident_id}' was not found.")
        return incident
