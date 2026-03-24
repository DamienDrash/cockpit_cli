from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.application.services.escalation_policy_service import EscalationPolicyService
from cockpit.application.services.escalation_service import EscalationService
from cockpit.application.services.oncall_resolution_service import ResolvedEscalationRecipient
from cockpit.domain.events.health_events import IncidentOpened
from cockpit.domain.models.escalation import EscalationPolicy, EscalationStep
from cockpit.domain.models.health import IncidentRecord
from cockpit.domain.models.notifications import NotificationRecord
from cockpit.domain.models.oncall import OperatorTeam, OwnershipResolution
from cockpit.infrastructure.persistence.ops_repositories import (
    EngagementDeliveryLinkRepository,
    EngagementTimelineRepository,
    EscalationPolicyRepository,
    EscalationStepRepository,
    IncidentEngagementRepository,
    IncidentRepository,
    NotificationRepository,
    OperatorTeamRepository,
)
from cockpit.infrastructure.persistence.sqlite_store import SQLiteStore
from cockpit.shared.enums import (
    ComponentKind,
    EngagementStatus,
    EscalationTargetKind,
    IncidentSeverity,
    IncidentStatus,
    NotificationStatus,
    ResolutionOutcome,
    TargetRiskLevel,
)
from cockpit.shared.utils import utc_now


class _FakeNotificationService:
    def __init__(self, repository: NotificationRepository) -> None:
        self._repository = repository
        self.sent = []

    def send(self, candidate):
        self.sent.append(candidate)
        record = NotificationRecord(
            id=f"ntf-{len(self.sent)}",
            event_class=candidate.event_class,
            severity=candidate.severity,
            risk_level=candidate.risk_level,
            title=candidate.title,
            summary=candidate.summary,
            status=NotificationStatus.QUEUED,
            dedupe_key=candidate.dedupe_key,
            incident_id=candidate.incident_id,
            component_id=candidate.component_id,
            component_kind=candidate.component_kind,
            incident_status=candidate.incident_status,
            payload=dict(candidate.payload),
            created_at=utc_now(),
        )
        self._repository.save(record)
        return record


class _FakeOperationsDiagnosticsService:
    def __init__(self) -> None:
        self.records = []

    def record_operation(self, **payload) -> None:
        self.records.append(dict(payload))


class _FakeOnCallResolutionService:
    def __init__(self, *, ownership: OwnershipResolution, recipients: dict[tuple[EscalationTargetKind, str], ResolvedEscalationRecipient]) -> None:
        self._ownership = ownership
        self._recipients = dict(recipients)

    def resolve_ownership(self, **kwargs):
        del kwargs
        return self._ownership

    def resolve_recipient(self, *, target_kind, target_ref, effective_at):
        del effective_at
        return self._recipients[(target_kind, target_ref)]


def _build_policy_service(store: SQLiteStore) -> EscalationPolicyService:
    return EscalationPolicyService(
        policy_repository=EscalationPolicyRepository(store),
        step_repository=EscalationStepRepository(store),
    )


class EscalationServiceTests(unittest.TestCase):
    def test_creates_active_engagement_when_incident_opens(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            event_bus = EventBus()
            incident_repo = IncidentRepository(store)
            engagement_repo = IncidentEngagementRepository(store)
            timeline_repo = EngagementTimelineRepository(store)
            delivery_link_repo = EngagementDeliveryLinkRepository(store)
            notification_repo = NotificationRepository(store)
            policy_service = _build_policy_service(store)
            OperatorTeamRepository(store).save(OperatorTeam(id="team-1", name="Platform Ops"))
            policy_service.save_policy(
                EscalationPolicy(id="epc-1", name="Default"),
                steps=(
                    EscalationStep(
                        id="est-1",
                        policy_id="epc-1",
                        step_index=0,
                        target_kind=EscalationTargetKind.TEAM,
                        target_ref="team-1",
                    ),
                ),
            )
            incident_repo.save(
                IncidentRecord(
                    id="inc-1",
                    component_id="docker:web",
                    component_kind=ComponentKind.DOCKER_RUNTIME,
                    severity=IncidentSeverity.HIGH,
                    status=IncidentStatus.OPEN,
                    title="Web unhealthy",
                    summary="Container restart loop detected",
                )
            )
            notification_service = _FakeNotificationService(notification_repo)
            service = EscalationService(
                event_bus=event_bus,
                incident_repository=incident_repo,
                engagement_repository=engagement_repo,
                timeline_repository=timeline_repo,
                delivery_link_repository=delivery_link_repo,
                oncall_resolution_service=_FakeOnCallResolutionService(
                    ownership=OwnershipResolution(
                        outcome=ResolutionOutcome.RESOLVED,
                        team_id="team-1",
                        escalation_policy_id="epc-1",
                        binding_id="own-1",
                        explanation="resolved",
                    ),
                    recipients={
                        (
                            EscalationTargetKind.TEAM,
                            "team-1",
                        ): ResolvedEscalationRecipient(
                            outcome=ResolutionOutcome.RESOLVED,
                            target_kind=EscalationTargetKind.TEAM,
                            target_ref="team-1",
                            person_id="opr-1",
                            channel_ids=("slack-alice",),
                            explanation="resolved",
                        )
                    },
                ),
                escalation_policy_service=policy_service,
                notification_service=notification_service,
                operations_diagnostics_service=_FakeOperationsDiagnosticsService(),
                now_factory=lambda: datetime(2026, 3, 24, 10, 0, tzinfo=UTC),
            )

            event_bus.publish(
                IncidentOpened(
                    incident_id="inc-1",
                    component_id="docker:web",
                    component_kind=ComponentKind.DOCKER_RUNTIME,
                    severity=IncidentSeverity.HIGH,
                    title="Web unhealthy",
                )
            )

            engagement = engagement_repo.get_active_for_incident("inc-1")
            self.assertIsNotNone(engagement)
            assert engagement is not None
            self.assertEqual(engagement.status, EngagementStatus.ACTIVE)
            self.assertEqual(engagement.current_step_index, 0)
            self.assertEqual(len(notification_service.sent), 1)

    def test_escalates_to_next_step_when_ack_deadline_expires(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            event_bus = EventBus()
            incident_repo = IncidentRepository(store)
            engagement_repo = IncidentEngagementRepository(store)
            timeline_repo = EngagementTimelineRepository(store)
            delivery_link_repo = EngagementDeliveryLinkRepository(store)
            notification_repo = NotificationRepository(store)
            policy_service = _build_policy_service(store)
            OperatorTeamRepository(store).save(OperatorTeam(id="team-1", name="Platform Ops"))
            policy_service.save_policy(
                EscalationPolicy(
                    id="epc-1",
                    name="Default",
                    default_ack_timeout_seconds=60,
                    default_repeat_page_seconds=30,
                ),
                steps=(
                    EscalationStep(
                        id="est-1",
                        policy_id="epc-1",
                        step_index=0,
                        target_kind=EscalationTargetKind.TEAM,
                        target_ref="team-1",
                    ),
                    EscalationStep(
                        id="est-2",
                        policy_id="epc-1",
                        step_index=1,
                        target_kind=EscalationTargetKind.PERSON,
                        target_ref="opr-2",
                    ),
                ),
            )
            incident_repo.save(
                IncidentRecord(
                    id="inc-1",
                    component_id="ssh-tunnel:pg-main",
                    component_kind=ComponentKind.SSH_TUNNEL,
                    severity=IncidentSeverity.CRITICAL,
                    status=IncidentStatus.OPEN,
                    title="Tunnel down",
                    summary="SSH tunnel exited",
                )
            )
            notification_service = _FakeNotificationService(notification_repo)
            service = EscalationService(
                event_bus=event_bus,
                incident_repository=incident_repo,
                engagement_repository=engagement_repo,
                timeline_repository=timeline_repo,
                delivery_link_repository=delivery_link_repo,
                oncall_resolution_service=_FakeOnCallResolutionService(
                    ownership=OwnershipResolution(
                        outcome=ResolutionOutcome.RESOLVED,
                        team_id="team-1",
                        escalation_policy_id="epc-1",
                        binding_id="own-1",
                        explanation="resolved",
                    ),
                    recipients={
                        (
                            EscalationTargetKind.TEAM,
                            "team-1",
                        ): ResolvedEscalationRecipient(
                            outcome=ResolutionOutcome.RESOLVED,
                            target_kind=EscalationTargetKind.TEAM,
                            target_ref="team-1",
                            person_id="opr-1",
                            channel_ids=("slack-team",),
                            explanation="resolved",
                        ),
                        (
                            EscalationTargetKind.PERSON,
                            "opr-2",
                        ): ResolvedEscalationRecipient(
                            outcome=ResolutionOutcome.RESOLVED,
                            target_kind=EscalationTargetKind.PERSON,
                            target_ref="opr-2",
                            person_id="opr-2",
                            channel_ids=("slack-bob",),
                            explanation="resolved",
                        ),
                    },
                ),
                escalation_policy_service=policy_service,
                notification_service=notification_service,
                operations_diagnostics_service=_FakeOperationsDiagnosticsService(),
                now_factory=lambda: datetime(2026, 3, 24, 10, 0, tzinfo=UTC),
            )

            event_bus.publish(
                IncidentOpened(
                    incident_id="inc-1",
                    component_id="ssh-tunnel:pg-main",
                    component_kind=ComponentKind.SSH_TUNNEL,
                    severity=IncidentSeverity.CRITICAL,
                    title="Tunnel down",
                )
            )
            service.run_due_actions(
                effective_now=datetime(2026, 3, 24, 10, 1, 1, tzinfo=UTC)
            )

            engagement = engagement_repo.get_active_for_incident("inc-1")
            self.assertIsNotNone(engagement)
            assert engagement is not None
            self.assertEqual(engagement.current_step_index, 1)
            self.assertEqual(engagement.current_target_ref, "opr-2")
            self.assertEqual(len(notification_service.sent), 2)

    def test_blocks_engagement_when_initial_recipient_cannot_be_resolved(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            event_bus = EventBus()
            incident_repo = IncidentRepository(store)
            engagement_repo = IncidentEngagementRepository(store)
            timeline_repo = EngagementTimelineRepository(store)
            delivery_link_repo = EngagementDeliveryLinkRepository(store)
            notification_repo = NotificationRepository(store)
            policy_service = _build_policy_service(store)
            OperatorTeamRepository(store).save(OperatorTeam(id="team-1", name="Platform Ops"))
            policy_service.save_policy(
                EscalationPolicy(id="epc-1", name="Default"),
                steps=(
                    EscalationStep(
                        id="est-1",
                        policy_id="epc-1",
                        step_index=0,
                        target_kind=EscalationTargetKind.TEAM,
                        target_ref="team-1",
                    ),
                ),
            )
            incident_repo.save(
                IncidentRecord(
                    id="inc-1",
                    component_id="datasource:analytics",
                    component_kind=ComponentKind.DATASOURCE,
                    severity=IncidentSeverity.HIGH,
                    status=IncidentStatus.OPEN,
                    title="Datasource unhealthy",
                    summary="Cannot connect",
                )
            )
            notification_service = _FakeNotificationService(notification_repo)
            service = EscalationService(
                event_bus=event_bus,
                incident_repository=incident_repo,
                engagement_repository=engagement_repo,
                timeline_repository=timeline_repo,
                delivery_link_repository=delivery_link_repo,
                oncall_resolution_service=_FakeOnCallResolutionService(
                    ownership=OwnershipResolution(
                        outcome=ResolutionOutcome.RESOLVED,
                        team_id="team-1",
                        escalation_policy_id="epc-1",
                        binding_id="own-1",
                        explanation="resolved",
                    ),
                    recipients={
                        (
                            EscalationTargetKind.TEAM,
                            "team-1",
                        ): ResolvedEscalationRecipient(
                            outcome=ResolutionOutcome.BLOCKED,
                            target_kind=EscalationTargetKind.TEAM,
                            target_ref="team-1",
                            person_id=None,
                            channel_ids=(),
                            explanation="No active on-call operator.",
                        )
                    },
                ),
                escalation_policy_service=policy_service,
                notification_service=notification_service,
                operations_diagnostics_service=_FakeOperationsDiagnosticsService(),
                now_factory=lambda: datetime(2026, 3, 24, 10, 0, tzinfo=UTC),
            )

            event_bus.publish(
                IncidentOpened(
                    incident_id="inc-1",
                    component_id="datasource:analytics",
                    component_kind=ComponentKind.DATASOURCE,
                    severity=IncidentSeverity.HIGH,
                    title="Datasource unhealthy",
                )
            )

            engagement = engagement_repo.get_active_for_incident("inc-1")
            self.assertIsNotNone(engagement)
            assert engagement is not None
            self.assertEqual(engagement.status, EngagementStatus.BLOCKED)
            self.assertEqual(len(notification_service.sent), 0)


if __name__ == "__main__":
    unittest.main()
