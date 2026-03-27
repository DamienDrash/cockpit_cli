from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cockpit.ops.models.escalation import (
    EngagementDeliveryLink,
    EscalationPolicy,
    EscalationStep,
    IncidentEngagement,
)
from cockpit.ops.models.health import IncidentRecord
from cockpit.notifications.models import NotificationRecord
from cockpit.ops.models.oncall import (
    OperatorPerson,
    OperatorTeam,
    OwnershipBinding,
    TeamMembership,
)
from cockpit.ops.repositories import (
    EngagementDeliveryLinkRepository,
    EngagementTimelineRepository,
    EscalationPolicyRepository,
    EscalationStepRepository,
    IncidentEngagementRepository,
    IncidentRepository,
    NotificationRepository,
    OperatorPersonRepository,
    OperatorTeamRepository,
    OwnershipBindingRepository,
    TeamMembershipRepository,
)
from cockpit.core.persistence.sqlite_store import SQLiteStore
from cockpit.core.enums import (
    ComponentKind,
    EngagementDeliveryPurpose,
    EngagementStatus,
    EscalationTargetKind,
    IncidentSeverity,
    IncidentStatus,
    NotificationEventClass,
    NotificationStatus,
    TargetRiskLevel,
    TeamMembershipRole,
)


class Stage3OpsRepositoriesTests(unittest.TestCase):
    def test_round_trips_oncall_and_engagement_records(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            OperatorPersonRepository(store).save(
                OperatorPerson(
                    id="opr-1",
                    display_name="Alice Example",
                    handle="alice",
                )
            )
            OperatorTeamRepository(store).save(
                OperatorTeam(
                    id="team-1",
                    name="Platform Ops",
                    default_escalation_policy_id="epc-1",
                )
            )
            TeamMembershipRepository(store).save(
                TeamMembership(
                    id="mem-1",
                    team_id="team-1",
                    person_id="opr-1",
                    role=TeamMembershipRole.LEAD,
                )
            )
            OwnershipBindingRepository(store).save(
                OwnershipBinding(
                    id="own-1",
                    name="Docker Web",
                    team_id="team-1",
                    component_kind=ComponentKind.DOCKER_RUNTIME,
                    component_id="docker:web",
                    escalation_policy_id="epc-1",
                )
            )
            EscalationPolicyRepository(store).save(
                EscalationPolicy(
                    id="epc-1",
                    name="Default escalation",
                )
            )
            EscalationStepRepository(store).save(
                EscalationStep(
                    id="est-1",
                    policy_id="epc-1",
                    step_index=0,
                    target_kind=EscalationTargetKind.TEAM,
                    target_ref="team-1",
                )
            )
            IncidentRepository(store).save(
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
            engagement_repo = IncidentEngagementRepository(store)
            timeline_repo = EngagementTimelineRepository(store)
            link_repo = EngagementDeliveryLinkRepository(store)
            NotificationRepository(store).save(
                NotificationRecord(
                    id="ntf-1",
                    event_class=NotificationEventClass.INCIDENT_OPENED,
                    severity=IncidentSeverity.HIGH,
                    risk_level=TargetRiskLevel.PROD,
                    title="Web unhealthy",
                    summary="Container restart loop detected",
                    status=NotificationStatus.QUEUED,
                    dedupe_key="incident:inc-1",
                    incident_id="inc-1",
                    component_id="docker:web",
                    component_kind=ComponentKind.DOCKER_RUNTIME,
                    incident_status=IncidentStatus.OPEN,
                    created_at=datetime(2026, 3, 24, 10, 0, tzinfo=UTC),
                )
            )
            engagement_repo.save(
                IncidentEngagement(
                    id="eng-1",
                    incident_id="inc-1",
                    incident_component_id="docker:web",
                    team_id="team-1",
                    policy_id="epc-1",
                    status=EngagementStatus.ACTIVE,
                    current_step_index=0,
                    current_target_kind=EscalationTargetKind.TEAM,
                    current_target_ref="team-1",
                    next_action_at=datetime(2026, 3, 24, 10, 5, tzinfo=UTC),
                    ack_deadline_at=datetime(2026, 3, 24, 10, 15, tzinfo=UTC),
                    created_at=datetime(2026, 3, 24, 10, 0, tzinfo=UTC),
                    updated_at=datetime(2026, 3, 24, 10, 0, tzinfo=UTC),
                )
            )
            timeline_repo.add_entry(
                engagement_id="eng-1",
                incident_id="inc-1",
                event_type="paged",
                message="Initial page sent.",
            )
            link_repo.save(
                EngagementDeliveryLink(
                    id=None,
                    engagement_id="eng-1",
                    notification_id="ntf-1",
                    purpose=EngagementDeliveryPurpose.PAGE,
                    step_index=0,
                )
            )

            self.assertEqual(
                OperatorPersonRepository(store).get("opr-1").handle, "alice"
            )
            self.assertEqual(len(OperatorTeamRepository(store).list_all()), 1)
            self.assertEqual(len(TeamMembershipRepository(store).list_all()), 1)
            self.assertEqual(
                OwnershipBindingRepository(store).get("own-1").component_id,
                "docker:web",
            )
            self.assertEqual(
                len(EscalationStepRepository(store).list_for_policy("epc-1")), 1
            )
            self.assertEqual(
                engagement_repo.find_active_for_incident("inc-1").id, "eng-1"
            )
            due = engagement_repo.list_due_actions(
                datetime(2026, 3, 24, 10, 5, tzinfo=UTC)
            )
            self.assertEqual([item.id for item in due], ["eng-1"])
            self.assertEqual(len(timeline_repo.list_for_engagement("eng-1")), 1)
            self.assertEqual(len(link_repo.list_for_engagement("eng-1")), 1)


if __name__ == "__main__":
    unittest.main()
