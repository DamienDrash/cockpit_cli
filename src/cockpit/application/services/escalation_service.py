"""Incident engagement runtime and escalation orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.application.services.escalation_policy_service import (
    EscalationPolicyService,
)
from cockpit.application.services.notification_service import NotificationService
from cockpit.application.services.oncall_resolution_service import (
    OnCallResolutionService,
    ResolvedEscalationRecipient,
)
from cockpit.application.services.operations_diagnostics_service import (
    OperationsDiagnosticsService,
)
from cockpit.domain.events.escalation_events import (
    EngagementAcknowledged,
    EngagementEscalated,
    EngagementExhausted,
    EngagementHandedOff,
    EngagementPaged,
    EngagementStatusChanged,
    IncidentEngagementCreated,
)
from cockpit.domain.events.health_events import IncidentOpened, IncidentStatusChanged
from cockpit.domain.events.notification_events import (
    NotificationDelivered,
    NotificationDeliveryFailed,
)
from cockpit.domain.models.escalation import (
    EngagementDeliveryLink,
    EngagementTimelineEntry,
    IncidentEngagement,
)
from cockpit.domain.models.health import IncidentRecord
from cockpit.domain.models.notifications import NotificationCandidate
from cockpit.domain.models.oncall import OwnershipResolution
from cockpit.infrastructure.persistence.ops_repositories import (
    EngagementDeliveryLinkRepository,
    EngagementTimelineRepository,
    IncidentEngagementRepository,
    IncidentRepository,
)
from cockpit.shared.enums import (
    EngagementDeliveryPurpose,
    EngagementStatus,
    EscalationTargetKind,
    IncidentSeverity,
    IncidentStatus,
    NotificationEventClass,
    OperationFamily,
    ResolutionOutcome,
    TargetRiskLevel,
)
from cockpit.shared.utils import make_id, utc_now


@dataclass(slots=True, frozen=True)
class EngagementDetail:
    """Structured engagement detail payload for operator surfaces."""

    engagement: IncidentEngagement
    incident: IncidentRecord | None
    timeline: tuple[EngagementTimelineEntry, ...]
    delivery_links: tuple[EngagementDeliveryLink, ...]


class EscalationService:
    """Create and advance active incident engagements."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        incident_repository: IncidentRepository,
        engagement_repository: IncidentEngagementRepository,
        timeline_repository: EngagementTimelineRepository,
        delivery_link_repository: EngagementDeliveryLinkRepository,
        oncall_resolution_service: OnCallResolutionService,
        escalation_policy_service: EscalationPolicyService,
        notification_service: NotificationService,
        operations_diagnostics_service: OperationsDiagnosticsService,
        now_factory: callable | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._incident_repository = incident_repository
        self._engagement_repository = engagement_repository
        self._timeline_repository = timeline_repository
        self._delivery_link_repository = delivery_link_repository
        self._oncall_resolution_service = oncall_resolution_service
        self._escalation_policy_service = escalation_policy_service
        self._notification_service = notification_service
        self._operations_diagnostics_service = operations_diagnostics_service
        self._now_factory = now_factory or utc_now

        self._event_bus.subscribe(IncidentOpened, self._on_incident_opened)
        self._event_bus.subscribe(IncidentStatusChanged, self._on_incident_status_changed)
        self._event_bus.subscribe(NotificationDelivered, self._on_notification_delivered)
        self._event_bus.subscribe(NotificationDeliveryFailed, self._on_notification_delivery_failed)

    def list_active_engagements(self, *, limit: int = 25) -> list[IncidentEngagement]:
        return self._engagement_repository.list_active(limit=limit)

    def list_recent_engagements(self, *, limit: int = 50) -> list[IncidentEngagement]:
        return self._engagement_repository.list_recent(limit=limit)

    def get_engagement_detail(self, engagement_id: str) -> EngagementDetail | None:
        engagement = self._engagement_repository.get(engagement_id)
        if engagement is None:
            return None
        incident = self._incident_repository.get(engagement.incident_id)
        return EngagementDetail(
            engagement=engagement,
            incident=incident,
            timeline=tuple(self._timeline_repository.list_for_engagement(engagement_id)),
            delivery_links=tuple(self._delivery_link_repository.list_for_engagement(engagement_id)),
        )

    def acknowledge_engagement(self, engagement_id: str, *, actor: str) -> IncidentEngagement:
        engagement = self._require_engagement(engagement_id)
        if engagement.status in {EngagementStatus.RESOLVED, EngagementStatus.CLOSED, EngagementStatus.EXHAUSTED}:
            raise ValueError("Closed or exhausted engagements cannot be acknowledged.")
        previous_status = engagement.status
        now = self._now()
        engagement.status = EngagementStatus.ACKNOWLEDGED
        engagement.acknowledged_by = actor
        engagement.acknowledged_at = now
        engagement.next_action_at = None
        engagement.updated_at = now
        self._engagement_repository.save(engagement)
        self._timeline_repository.add_entry(
            engagement_id=engagement.id,
            incident_id=engagement.incident_id,
            event_type="acknowledged",
            message=f"Engagement acknowledged by {actor}.",
            payload={"actor": actor},
        )
        self._publish_status_change(
            engagement=engagement,
            previous_status=previous_status,
            message=f"Engagement acknowledged by {actor}.",
        )
        self._set_incident_status(
            engagement.incident_id,
            new_status=IncidentStatus.ACKNOWLEDGED,
            message=f"Incident acknowledged by {actor}.",
        )
        self._operations_diagnostics_service.record_operation(
            family=OperationFamily.ENGAGEMENT,
            component_id=f"engagement:{engagement.id}",
            subject_ref=engagement.incident_id,
            success=True,
            severity="info",
            summary="engagement acknowledged",
            payload={"actor": actor},
        )
        self._event_bus.publish(
            EngagementAcknowledged(
                engagement_id=engagement.id,
                incident_id=engagement.incident_id,
                actor=actor,
            )
        )
        return engagement

    def handoff_engagement(
        self,
        engagement_id: str,
        *,
        actor: str,
        target_kind: EscalationTargetKind,
        target_ref: str,
    ) -> IncidentEngagement:
        engagement = self._require_engagement(engagement_id)
        if engagement.status in {EngagementStatus.RESOLVED, EngagementStatus.CLOSED, EngagementStatus.EXHAUSTED}:
            raise ValueError("Closed or exhausted engagements cannot be handed off.")
        incident = self._require_incident(engagement.incident_id)
        policy = self._require_policy(engagement)
        step = self._require_step(engagement)
        now = self._now()
        recipient = self._oncall_resolution_service.resolve_recipient(
            target_kind=target_kind,
            target_ref=target_ref,
            effective_at=now,
        )
        previous_status = engagement.status
        engagement.current_target_kind = target_kind
        engagement.current_target_ref = target_ref
        engagement.resolved_person_id = recipient.person_id
        engagement.handoff_count += 1
        engagement.repeat_page_count = 0
        engagement.acknowledged_by = None
        engagement.acknowledged_at = None
        engagement.ack_deadline_at = self._escalation_policy_service.ack_deadline_for(
            policy=policy,
            step=step,
            effective_at=now,
        )
        if recipient.outcome is ResolutionOutcome.RESOLVED:
            engagement.status = EngagementStatus.ACTIVE
            engagement.next_action_at = self._escalation_policy_service.next_repeat_at(
                policy=policy,
                step=step,
                effective_at=now,
            )
        else:
            engagement.status = EngagementStatus.BLOCKED
            engagement.next_action_at = None
        engagement.updated_at = now
        self._engagement_repository.save(engagement)
        self._timeline_repository.add_entry(
            engagement_id=engagement.id,
            incident_id=engagement.incident_id,
            event_type="handed_off",
            message=f"Engagement handed off by {actor}.",
            payload={
                "actor": actor,
                "target_kind": target_kind.value,
                "target_ref": target_ref,
                "outcome": recipient.outcome.value,
            },
        )
        self._publish_status_change(
            engagement=engagement,
            previous_status=previous_status,
            message=f"Engagement handed off by {actor}.",
        )
        self._operations_diagnostics_service.record_operation(
            family=OperationFamily.ENGAGEMENT,
            component_id=f"engagement:{engagement.id}",
            subject_ref=engagement.incident_id,
            success=recipient.outcome is ResolutionOutcome.RESOLVED,
            severity="info" if recipient.outcome is ResolutionOutcome.RESOLVED else "high",
            summary="engagement handoff",
            payload={
                "actor": actor,
                "target_kind": target_kind.value,
                "target_ref": target_ref,
                "outcome": recipient.outcome.value,
            },
        )
        self._event_bus.publish(
            EngagementHandedOff(
                engagement_id=engagement.id,
                incident_id=engagement.incident_id,
                actor=actor,
                new_target_ref=target_ref,
            )
        )
        if recipient.outcome is ResolutionOutcome.RESOLVED:
            self._page_engagement(
                engagement=engagement,
                incident=incident,
                recipient=recipient,
                purpose=EngagementDeliveryPurpose.HANDOFF,
            )
        return engagement

    def repage_engagement(self, engagement_id: str, *, actor: str | None = None) -> IncidentEngagement:
        engagement = self._require_engagement(engagement_id)
        if engagement.status in {EngagementStatus.RESOLVED, EngagementStatus.CLOSED, EngagementStatus.EXHAUSTED}:
            raise ValueError("Closed or exhausted engagements cannot be re-paged.")
        incident = self._require_incident(engagement.incident_id)
        recipient = self._resolve_current_recipient(engagement, self._now())
        if recipient.outcome is not ResolutionOutcome.RESOLVED:
            previous_status = engagement.status
            engagement.status = EngagementStatus.BLOCKED
            engagement.next_action_at = None
            engagement.updated_at = self._now()
            self._engagement_repository.save(engagement)
            self._timeline_repository.add_entry(
                engagement_id=engagement.id,
                incident_id=engagement.incident_id,
                event_type="blocked",
                message=recipient.explanation,
                payload={"action": "repage"},
            )
            self._publish_status_change(
                engagement=engagement,
                previous_status=previous_status,
                message=recipient.explanation,
            )
            return engagement
        engagement.status = EngagementStatus.ACTIVE
        engagement.updated_at = self._now()
        self._engagement_repository.save(engagement)
        self._page_engagement(
            engagement=engagement,
            incident=incident,
            recipient=recipient,
            purpose=EngagementDeliveryPurpose.REPAGE,
            actor=actor,
        )
        return engagement

    def run_due_actions(self, *, effective_now: datetime | None = None) -> None:
        now = effective_now or self._now()
        for engagement in self._engagement_repository.list_due_actions(now):
            self._run_due_action(engagement, effective_now=now)

    def diagnostics(self) -> dict[str, object]:
        active = self._engagement_repository.list_active(limit=20)
        counts: dict[str, int] = {}
        for engagement in active:
            counts[engagement.status.value] = counts.get(engagement.status.value, 0) + 1
        blocked = [item.to_dict() for item in active if item.status is EngagementStatus.BLOCKED]
        exhausted = [
            item.to_dict()
            for item in self._engagement_repository.list_recent(limit=20)
            if item.status is EngagementStatus.EXHAUSTED
        ]
        return {
            "counts": counts,
            "active": [item.to_dict() for item in active],
            "blocked": blocked,
            "recent_exhausted": exhausted[:10],
        }

    def _on_incident_opened(self, event: IncidentOpened) -> None:
        incident = self._incident_repository.get(event.incident_id)
        if incident is None:
            return
        if self._engagement_repository.get_active_for_incident(incident.id) is not None:
            return
        self._create_engagement_for_incident(incident)

    def _on_incident_status_changed(self, event: IncidentStatusChanged) -> None:
        if event.new_status not in {IncidentStatus.RESOLVED, IncidentStatus.CLOSED}:
            return
        engagement = self._engagement_repository.get_active_for_incident(event.incident_id)
        if engagement is None:
            return
        previous_status = engagement.status
        engagement.status = (
            EngagementStatus.RESOLVED
            if event.new_status is IncidentStatus.RESOLVED
            else EngagementStatus.CLOSED
        )
        engagement.next_action_at = None
        engagement.closed_at = self._now()
        engagement.updated_at = engagement.closed_at
        self._engagement_repository.save(engagement)
        self._timeline_repository.add_entry(
            engagement_id=engagement.id,
            incident_id=engagement.incident_id,
            event_type="closed" if engagement.status is EngagementStatus.CLOSED else "resolved",
            message=event.message,
            payload={"incident_status": event.new_status.value},
        )
        self._publish_status_change(
            engagement=engagement,
            previous_status=previous_status,
            message=event.message,
        )

    def _on_notification_delivered(self, event: NotificationDelivered) -> None:
        for link in self._delivery_link_repository.list_for_notification(event.notification_id):
            self._delivery_link_repository.save(
                EngagementDeliveryLink(
                    id=None,
                    engagement_id=link.engagement_id,
                    notification_id=event.notification_id,
                    delivery_id=event.delivery_id,
                    purpose=link.purpose,
                    step_index=link.step_index,
                    created_at=self._now(),
                    payload={"status": event.status.value, "channel_id": event.channel_id},
                )
            )
            self._timeline_repository.add_entry(
                engagement_id=link.engagement_id,
                incident_id=self._require_engagement(link.engagement_id).incident_id,
                event_type="delivery_succeeded",
                message=f"Notification delivered via channel {event.channel_id}.",
                payload={
                    "notification_id": event.notification_id,
                    "delivery_id": event.delivery_id,
                    "channel_id": event.channel_id,
                },
            )

    def _on_notification_delivery_failed(self, event: NotificationDeliveryFailed) -> None:
        for link in self._delivery_link_repository.list_for_notification(event.notification_id):
            self._delivery_link_repository.save(
                EngagementDeliveryLink(
                    id=None,
                    engagement_id=link.engagement_id,
                    notification_id=event.notification_id,
                    delivery_id=event.delivery_id,
                    purpose=link.purpose,
                    step_index=link.step_index,
                    created_at=self._now(),
                    payload={
                        "status": event.status.value,
                        "channel_id": event.channel_id,
                        "error_message": event.error_message,
                    },
                )
            )
            self._timeline_repository.add_entry(
                engagement_id=link.engagement_id,
                incident_id=self._require_engagement(link.engagement_id).incident_id,
                event_type="delivery_failed",
                message=event.error_message,
                payload={
                    "notification_id": event.notification_id,
                    "delivery_id": event.delivery_id,
                    "channel_id": event.channel_id,
                },
            )

    def _create_engagement_for_incident(self, incident: IncidentRecord) -> IncidentEngagement:
        ownership = self._oncall_resolution_service.resolve_ownership(
            component_kind=incident.component_kind,
            component_id=incident.component_id,
        )
        now = self._now()
        engagement = IncidentEngagement(
            id=make_id("eng"),
            incident_id=incident.id,
            incident_component_id=incident.component_id,
            team_id=ownership.team_id,
            policy_id=ownership.escalation_policy_id,
            status=EngagementStatus.BLOCKED,
            created_at=now,
            updated_at=now,
            payload={"ownership": ownership.to_dict()},
        )
        if ownership.outcome is not ResolutionOutcome.RESOLVED:
            self._engagement_repository.save(engagement)
            self._timeline_repository.add_entry(
                engagement_id=engagement.id,
                incident_id=incident.id,
                event_type="blocked",
                message=ownership.explanation,
                payload={"phase": "ownership"},
            )
            self._event_bus.publish(
                IncidentEngagementCreated(
                    engagement_id=engagement.id,
                    incident_id=incident.id,
                    team_id=ownership.team_id or "",
                    policy_id=ownership.escalation_policy_id or "",
                )
            )
            self._publish_status_change(
                engagement=engagement,
                previous_status=None,
                message=ownership.explanation,
            )
            return engagement

        policy = self._escalation_policy_service.get_policy(ownership.escalation_policy_id or "")
        if policy is None or not policy.enabled:
            engagement.payload["reason"] = "resolved policy is missing or disabled"
            self._engagement_repository.save(engagement)
            self._timeline_repository.add_entry(
                engagement_id=engagement.id,
                incident_id=incident.id,
                event_type="blocked",
                message="Resolved escalation policy is missing or disabled.",
                payload={"phase": "policy"},
            )
            self._event_bus.publish(
                IncidentEngagementCreated(
                    engagement_id=engagement.id,
                    incident_id=incident.id,
                    team_id=ownership.team_id or "",
                    policy_id=ownership.escalation_policy_id or "",
                )
            )
            return engagement
        step = self._escalation_policy_service.first_step(policy.id)
        recipient = self._oncall_resolution_service.resolve_recipient(
            target_kind=step.target_kind,
            target_ref=step.target_ref,
            effective_at=now,
        )
        engagement.current_step_index = step.step_index
        engagement.current_target_kind = step.target_kind
        engagement.current_target_ref = step.target_ref
        engagement.resolved_person_id = recipient.person_id
        engagement.ack_deadline_at = self._escalation_policy_service.ack_deadline_for(
            policy=policy,
            step=step,
            effective_at=now,
        )
        if recipient.outcome is ResolutionOutcome.RESOLVED:
            engagement.status = EngagementStatus.ACTIVE
            engagement.next_action_at = self._escalation_policy_service.next_repeat_at(
                policy=policy,
                step=step,
                effective_at=now,
            )
        else:
            engagement.status = EngagementStatus.BLOCKED
        self._engagement_repository.save(engagement)
        self._timeline_repository.add_entry(
            engagement_id=engagement.id,
            incident_id=incident.id,
            event_type="created",
            message="Engagement created for incident.",
            payload={"ownership": ownership.to_dict(), "recipient": recipient.explanation},
        )
        self._event_bus.publish(
            IncidentEngagementCreated(
                engagement_id=engagement.id,
                incident_id=incident.id,
                team_id=ownership.team_id or "",
                policy_id=policy.id,
            )
        )
        self._publish_status_change(
            engagement=engagement,
            previous_status=None,
            message="Engagement created.",
        )
        if recipient.outcome is ResolutionOutcome.RESOLVED:
            self._page_engagement(
                engagement=engagement,
                incident=incident,
                recipient=recipient,
                purpose=EngagementDeliveryPurpose.PAGE,
            )
        else:
            self._timeline_repository.add_entry(
                engagement_id=engagement.id,
                incident_id=incident.id,
                event_type="blocked",
                message=recipient.explanation,
                payload={"phase": "recipient"},
            )
        return engagement

    def _run_due_action(self, engagement: IncidentEngagement, *, effective_now: datetime) -> None:
        incident = self._require_incident(engagement.incident_id)
        if engagement.status is not EngagementStatus.ACTIVE:
            return
        policy = self._require_policy(engagement)
        step = self._require_step(engagement)
        if engagement.ack_deadline_at and effective_now >= engagement.ack_deadline_at:
            next_step = self._escalation_policy_service.next_step(
                policy.id,
                engagement.current_step_index,
            )
            if next_step is None:
                self._mark_exhausted(engagement, message="Escalation policy exhausted.")
                return
            recipient = self._oncall_resolution_service.resolve_recipient(
                target_kind=next_step.target_kind,
                target_ref=next_step.target_ref,
                effective_at=effective_now,
            )
            previous_status = engagement.status
            engagement.current_step_index = next_step.step_index
            engagement.current_target_kind = next_step.target_kind
            engagement.current_target_ref = next_step.target_ref
            engagement.resolved_person_id = recipient.person_id
            engagement.repeat_page_count = 0
            engagement.ack_deadline_at = self._escalation_policy_service.ack_deadline_for(
                policy=policy,
                step=next_step,
                effective_at=effective_now,
            )
            engagement.updated_at = effective_now
            if recipient.outcome is ResolutionOutcome.RESOLVED:
                engagement.status = EngagementStatus.ACTIVE
                engagement.next_action_at = self._escalation_policy_service.next_repeat_at(
                    policy=policy,
                    step=next_step,
                    effective_at=effective_now,
                )
            else:
                engagement.status = EngagementStatus.BLOCKED
                engagement.next_action_at = None
            self._engagement_repository.save(engagement)
            self._timeline_repository.add_entry(
                engagement_id=engagement.id,
                incident_id=engagement.incident_id,
                event_type="escalated",
                message=f"Escalated to step {next_step.step_index}.",
                payload={
                    "step_index": next_step.step_index,
                    "target_kind": next_step.target_kind.value,
                    "target_ref": next_step.target_ref,
                    "recipient_outcome": recipient.outcome.value,
                },
            )
            self._publish_status_change(
                engagement=engagement,
                previous_status=previous_status,
                message=f"Escalated to step {next_step.step_index}.",
            )
            self._event_bus.publish(
                EngagementEscalated(
                    engagement_id=engagement.id,
                    incident_id=engagement.incident_id,
                    step_index=next_step.step_index,
                    target_ref=next_step.target_ref,
                )
            )
            if recipient.outcome is ResolutionOutcome.RESOLVED:
                self._page_engagement(
                    engagement=engagement,
                    incident=incident,
                    recipient=recipient,
                    purpose=EngagementDeliveryPurpose.PAGE,
                )
            return

        max_repeats = self._escalation_policy_service.max_repeat_pages(policy=policy, step=step)
        if engagement.repeat_page_count >= max_repeats:
            engagement.next_action_at = engagement.ack_deadline_at
            engagement.updated_at = effective_now
            self._engagement_repository.save(engagement)
            return
        recipient = self._resolve_current_recipient(engagement, effective_now)
        if recipient.outcome is not ResolutionOutcome.RESOLVED:
            previous_status = engagement.status
            engagement.status = EngagementStatus.BLOCKED
            engagement.next_action_at = None
            engagement.updated_at = effective_now
            self._engagement_repository.save(engagement)
            self._timeline_repository.add_entry(
                engagement_id=engagement.id,
                incident_id=engagement.incident_id,
                event_type="blocked",
                message=recipient.explanation,
                payload={"phase": "repeat_page"},
            )
            self._publish_status_change(
                engagement=engagement,
                previous_status=previous_status,
                message=recipient.explanation,
            )
            return
        engagement.repeat_page_count += 1
        engagement.updated_at = effective_now
        next_repeat_at = self._escalation_policy_service.next_repeat_at(
            policy=policy,
            step=step,
            effective_at=effective_now,
        )
        if engagement.ack_deadline_at and next_repeat_at >= engagement.ack_deadline_at:
            engagement.next_action_at = engagement.ack_deadline_at
        else:
            engagement.next_action_at = next_repeat_at
        self._engagement_repository.save(engagement)
        purpose = (
            EngagementDeliveryPurpose.REMINDER
            if step.reminder_enabled and engagement.repeat_page_count == 1
            else EngagementDeliveryPurpose.REPAGE
        )
        self._page_engagement(
            engagement=engagement,
            incident=incident,
            recipient=recipient,
            purpose=purpose,
        )

    def _page_engagement(
        self,
        *,
        engagement: IncidentEngagement,
        incident: IncidentRecord,
        recipient: ResolvedEscalationRecipient,
        purpose: EngagementDeliveryPurpose,
        actor: str | None = None,
    ) -> None:
        event_class = self._notification_event_class_for(purpose, engagement.current_step_index)
        title = self._title_for_page(incident, purpose)
        summary = incident.summary
        sequence = engagement.repeat_page_count
        if purpose is EngagementDeliveryPurpose.HANDOFF:
            sequence = engagement.handoff_count
        notification = self._notification_service.send(
            NotificationCandidate(
                event_class=event_class,
                severity=incident.severity if incident.severity is not None else IncidentSeverity.HIGH,
                risk_level=TargetRiskLevel.DEV,
                title=title,
                summary=summary,
                dedupe_key=(
                    f"engagement:{engagement.id}:{purpose.value}:{engagement.current_step_index}:{sequence}"
                ),
                incident_id=incident.id,
                component_id=incident.component_id,
                component_kind=incident.component_kind,
                incident_status=incident.status,
                forced_channel_ids=recipient.channel_ids,
                payload={
                    "engagement_id": engagement.id,
                    "team_id": engagement.team_id,
                    "policy_id": engagement.policy_id,
                    "purpose": purpose.value,
                    "step_index": engagement.current_step_index,
                    "target_kind": engagement.current_target_kind.value
                    if engagement.current_target_kind
                    else None,
                    "target_ref": engagement.current_target_ref,
                    "resolved_person_id": recipient.person_id,
                    "actor": actor,
                },
            )
        )
        engagement.last_page_at = self._now()
        engagement.updated_at = engagement.last_page_at
        self._engagement_repository.save(engagement)
        if notification is None:
            return
        self._delivery_link_repository.save(
            EngagementDeliveryLink(
                id=None,
                engagement_id=engagement.id,
                notification_id=notification.id,
                purpose=purpose,
                step_index=engagement.current_step_index,
                created_at=self._now(),
                payload={"status": notification.status.value},
            )
        )
        self._timeline_repository.add_entry(
            engagement_id=engagement.id,
            incident_id=incident.id,
            event_type="paged",
            message=f"{purpose.value} dispatched to {recipient.target_ref}.",
            payload={
                "purpose": purpose.value,
                "notification_id": notification.id,
                "recipient": recipient.to_dict(),
            },
        )
        self._operations_diagnostics_service.record_operation(
            family=OperationFamily.ENGAGEMENT,
            component_id=f"engagement:{engagement.id}",
            subject_ref=incident.id,
            success=notification.status is not None and notification.status.value != "failed",
            severity=incident.severity.value,
            summary=f"{purpose.value} dispatched",
            payload={
                "notification_id": notification.id,
                "recipient": recipient.to_dict(),
                "purpose": purpose.value,
            },
        )
        self._event_bus.publish(
            EngagementPaged(
                engagement_id=engagement.id,
                incident_id=incident.id,
                notification_id=notification.id,
                purpose=purpose,
                step_index=engagement.current_step_index,
                target_ref=recipient.target_ref,
            )
        )

    def _resolve_current_recipient(
        self,
        engagement: IncidentEngagement,
        effective_at: datetime,
    ) -> ResolvedEscalationRecipient:
        if engagement.current_target_kind is None or not engagement.current_target_ref:
            return ResolvedEscalationRecipient(
                outcome=ResolutionOutcome.BLOCKED,
                target_kind=EscalationTargetKind.CHANNEL,
                target_ref="",
                person_id=None,
                channel_ids=(),
                explanation="Engagement has no current target.",
            )
        recipient = self._oncall_resolution_service.resolve_recipient(
            target_kind=engagement.current_target_kind,
            target_ref=engagement.current_target_ref,
            effective_at=effective_at,
        )
        engagement.resolved_person_id = recipient.person_id
        return recipient

    def _mark_exhausted(self, engagement: IncidentEngagement, *, message: str) -> None:
        previous_status = engagement.status
        now = self._now()
        engagement.status = EngagementStatus.EXHAUSTED
        engagement.exhausted = True
        engagement.next_action_at = None
        engagement.updated_at = now
        self._engagement_repository.save(engagement)
        self._timeline_repository.add_entry(
            engagement_id=engagement.id,
            incident_id=engagement.incident_id,
            event_type="exhausted",
            message=message,
            payload={"step_index": engagement.current_step_index},
        )
        self._publish_status_change(
            engagement=engagement,
            previous_status=previous_status,
            message=message,
        )
        self._event_bus.publish(
            EngagementExhausted(
                engagement_id=engagement.id,
                incident_id=engagement.incident_id,
                message=message,
            )
        )

    def _set_incident_status(
        self,
        incident_id: str,
        *,
        new_status: IncidentStatus,
        message: str,
    ) -> None:
        incident = self._incident_repository.get(incident_id)
        if incident is None or incident.status is new_status:
            return
        previous_status = incident.status
        now = self._now()
        incident.status = new_status
        incident.updated_at = now
        if new_status is IncidentStatus.ACKNOWLEDGED:
            incident.acknowledged_at = now
        if new_status is IncidentStatus.RESOLVED:
            incident.resolved_at = now
        if new_status is IncidentStatus.CLOSED:
            incident.closed_at = now
        self._incident_repository.save(incident)
        self._incident_repository.add_timeline_entry(
            incident_id=incident.id,
            event_type="status_changed",
            message=message,
            payload={"previous_status": previous_status.value, "new_status": new_status.value},
        )
        self._event_bus.publish(
            IncidentStatusChanged(
                incident_id=incident.id,
                component_id=incident.component_id,
                component_kind=incident.component_kind,
                previous_status=previous_status,
                new_status=new_status,
                message=message,
            )
        )

    def _publish_status_change(
        self,
        *,
        engagement: IncidentEngagement,
        previous_status: EngagementStatus | None,
        message: str,
    ) -> None:
        self._event_bus.publish(
            EngagementStatusChanged(
                engagement_id=engagement.id,
                incident_id=engagement.incident_id,
                previous_status=previous_status,
                new_status=engagement.status,
                message=message,
            )
        )

    def _require_engagement(self, engagement_id: str) -> IncidentEngagement:
        engagement = self._engagement_repository.get(engagement_id)
        if engagement is None:
            raise LookupError(f"Engagement '{engagement_id}' was not found.")
        return engagement

    def _require_incident(self, incident_id: str) -> IncidentRecord:
        incident = self._incident_repository.get(incident_id)
        if incident is None:
            raise LookupError(f"Incident '{incident_id}' was not found.")
        return incident

    def _require_policy(self, engagement: IncidentEngagement):
        if not engagement.policy_id:
            raise LookupError(f"Engagement '{engagement.id}' has no policy.")
        policy = self._escalation_policy_service.get_policy(engagement.policy_id)
        if policy is None:
            raise LookupError(f"Escalation policy '{engagement.policy_id}' was not found.")
        return policy

    def _require_step(self, engagement: IncidentEngagement):
        if not engagement.policy_id:
            raise LookupError(f"Engagement '{engagement.id}' has no policy.")
        step = self._escalation_policy_service.step_at(
            engagement.policy_id,
            engagement.current_step_index,
        )
        if step is None:
            raise LookupError(
                f"Escalation step {engagement.current_step_index} was not found for policy '{engagement.policy_id}'."
            )
        return step

    @staticmethod
    def _notification_event_class_for(
        purpose: EngagementDeliveryPurpose,
        step_index: int,
    ) -> NotificationEventClass:
        if purpose is EngagementDeliveryPurpose.HANDOFF:
            return NotificationEventClass.ENGAGEMENT_HANDOFF
        if purpose in {EngagementDeliveryPurpose.REMINDER, EngagementDeliveryPurpose.REPAGE}:
            return NotificationEventClass.ENGAGEMENT_REMINDER
        if step_index > 0:
            return NotificationEventClass.ENGAGEMENT_ESCALATED
        return NotificationEventClass.ENGAGEMENT_PAGED

    @staticmethod
    def _title_for_page(incident: IncidentRecord, purpose: EngagementDeliveryPurpose) -> str:
        if purpose is EngagementDeliveryPurpose.HANDOFF:
            return f"Handoff: {incident.title}"
        if purpose is EngagementDeliveryPurpose.REMINDER:
            return f"Reminder: {incident.title}"
        if purpose is EngagementDeliveryPurpose.REPAGE:
            return f"Re-page: {incident.title}"
        return f"Page: {incident.title}"

    def _now(self) -> datetime:
        return self._now_factory()
