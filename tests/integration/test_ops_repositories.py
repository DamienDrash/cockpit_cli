from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cockpit.domain.models.health import ComponentHealthState, IncidentRecord, RecoveryAttempt
from cockpit.domain.models.notifications import (
    NotificationChannel,
    NotificationDeliveryAttempt,
    NotificationRecord,
    NotificationRule,
    NotificationSuppressionRule,
)
from cockpit.domain.models.policy import GuardDecision
from cockpit.domain.models.watch import ComponentWatchConfig, ComponentWatchState
from cockpit.infrastructure.persistence.ops_repositories import (
    ComponentHealthRepository,
    ComponentWatchRepository,
    GuardDecisionRepository,
    IncidentRepository,
    NotificationChannelRepository,
    NotificationDeliveryRepository,
    NotificationRepository,
    NotificationRuleRepository,
    NotificationSuppressionRepository,
    OperationDiagnosticsRepository,
    RecoveryAttemptRepository,
)
from cockpit.infrastructure.persistence.sqlite_store import SQLiteStore
from cockpit.shared.enums import (
    ComponentKind,
    GuardActionKind,
    GuardDecisionOutcome,
    HealthStatus,
    IncidentSeverity,
    IncidentStatus,
    NotificationChannelKind,
    NotificationDeliveryStatus,
    NotificationEventClass,
    NotificationStatus,
    OperationFamily,
    RecoveryAttemptStatus,
    SessionTargetKind,
    TargetRiskLevel,
    WatchProbeOutcome,
    WatchSubjectKind,
)


class OpsRepositoriesTests(unittest.TestCase):
    def test_round_trips_health_incident_recovery_and_guard_records(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            health_repo = ComponentHealthRepository(store)
            incident_repo = IncidentRepository(store)
            recovery_repo = RecoveryAttemptRepository(store)
            guard_repo = GuardDecisionRepository(store)
            ops_repo = OperationDiagnosticsRepository(store)
            channel_repo = NotificationChannelRepository(store)
            rule_repo = NotificationRuleRepository(store)
            suppression_repo = NotificationSuppressionRepository(store)
            notification_repo = NotificationRepository(store)
            delivery_repo = NotificationDeliveryRepository(store)
            watch_repo = ComponentWatchRepository(store)

            state = ComponentHealthState(
                component_id="pty:work-panel",
                component_kind=ComponentKind.PTY_SESSION,
                display_name="PTY work-panel",
                status=HealthStatus.RECOVERING,
                target_kind=SessionTargetKind.LOCAL,
                consecutive_failures=2,
                payload={"cwd": "/tmp/project"},
            )
            health_repo.save(state)
            loaded_state = health_repo.get("pty:work-panel")
            self.assertIsNotNone(loaded_state)
            assert loaded_state is not None
            self.assertEqual(loaded_state.status, HealthStatus.RECOVERING)

            incident = IncidentRecord(
                id="inc-1",
                component_id="pty:work-panel",
                component_kind=ComponentKind.PTY_SESSION,
                severity=IncidentSeverity.HIGH,
                status=IncidentStatus.OPEN,
                title="PTY unhealthy",
                summary="terminal exited",
            )
            incident_repo.save(incident)
            incident_repo.add_timeline_entry(
                incident_id="inc-1",
                event_type="opened",
                message="terminal exited",
            )
            self.assertEqual(len(incident_repo.list_timeline("inc-1")), 1)

            attempt = RecoveryAttempt(
                id="rcv-1",
                incident_id="inc-1",
                component_id="pty:work-panel",
                attempt_number=1,
                status=RecoveryAttemptStatus.SCHEDULED,
                trigger="automatic",
                action="recover:pty_session",
            )
            recovery_repo.save(attempt)
            self.assertEqual(len(recovery_repo.list_for_incident("inc-1")), 1)

            decision = GuardDecision(
                command_id="cmd-1",
                action_kind=GuardActionKind.DB_MUTATION,
                component_kind=ComponentKind.DATASOURCE,
                target_risk=TargetRiskLevel.STAGE,
                outcome=GuardDecisionOutcome.REQUIRE_CONFIRMATION,
                explanation="confirmation required",
                requires_confirmation=True,
            )
            guard_repo.record(decision)
            self.assertEqual(len(guard_repo.list_recent()), 1)

            ops_repo.record(
                operation_family=OperationFamily.DB,
                component_id="datasource:analytics",
                subject_ref="analytics",
                success=False,
                severity="high",
                summary="query failed",
                payload={"message": "syntax error"},
            )
            recent = ops_repo.list_recent(family=OperationFamily.DB)
            self.assertEqual(len(recent), 1)
            self.assertEqual(recent[0].summary, "query failed")

            channel = NotificationChannel(
                id="nch-1",
                name="Internal",
                kind=NotificationChannelKind.INTERNAL,
                risk_level=TargetRiskLevel.DEV,
            )
            channel_repo.save(channel)
            self.assertEqual(channel_repo.get("nch-1").name, "Internal")

            rule = NotificationRule(
                id="nrl-1",
                name="Default rule",
                event_classes=(NotificationEventClass.INCIDENT_OPENED,),
                channel_ids=("nch-1",),
            )
            rule_repo.save(rule)
            self.assertEqual(rule_repo.get("nrl-1").channel_ids, ("nch-1",))

            suppression = NotificationSuppressionRule(
                id="sup-1",
                name="Maintenance",
                reason="mute",
                event_classes=(NotificationEventClass.COMPONENT_DEGRADED,),
            )
            suppression_repo.save(suppression)
            self.assertEqual(len(suppression_repo.list_all()), 1)

            notification = NotificationRecord(
                id="ntf-1",
                event_class=NotificationEventClass.INCIDENT_OPENED,
                severity=IncidentSeverity.HIGH,
                risk_level=TargetRiskLevel.STAGE,
                title="Tunnel unhealthy",
                summary="ssh tunnel exited",
                status=NotificationStatus.QUEUED,
                dedupe_key="ssh-tunnel:pg-main:incident_opened",
                component_id="ssh-tunnel:pg-main",
                component_kind=ComponentKind.SSH_TUNNEL,
            )
            notification_repo.save(notification)
            self.assertEqual(notification_repo.get("ntf-1").title, "Tunnel unhealthy")

            delivery = NotificationDeliveryAttempt(
                id="ndl-1",
                notification_id="ntf-1",
                channel_id="nch-1",
                attempt_number=1,
                status=NotificationDeliveryStatus.SCHEDULED,
            )
            delivery_repo.save(delivery)
            self.assertEqual(len(delivery_repo.list_for_notification("ntf-1")), 1)

            watch_config = ComponentWatchConfig(
                id="wch-1",
                name="Analytics watch",
                component_id="watch:datasource:analytics",
                component_kind=ComponentKind.DATASOURCE_WATCH,
                subject_kind=WatchSubjectKind.DATASOURCE,
                subject_ref="analytics",
            )
            watch_repo.save_config(watch_config)
            watch_state = ComponentWatchState(
                component_id="watch:datasource:analytics",
                watch_id="wch-1",
                component_kind=ComponentKind.DATASOURCE_WATCH,
                subject_kind=WatchSubjectKind.DATASOURCE,
                subject_ref="analytics",
                last_outcome=WatchProbeOutcome.FAILURE,
                last_status="unreachable",
            )
            watch_repo.save_state(watch_state)
            self.assertEqual(watch_repo.get_config("wch-1").subject_ref, "analytics")
            self.assertEqual(watch_repo.get_state("watch:datasource:analytics").last_status, "unreachable")


if __name__ == "__main__":
    unittest.main()
