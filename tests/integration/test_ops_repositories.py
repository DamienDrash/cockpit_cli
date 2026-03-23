from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cockpit.domain.models.health import ComponentHealthState, IncidentRecord, RecoveryAttempt
from cockpit.domain.models.policy import GuardDecision
from cockpit.infrastructure.persistence.ops_repositories import (
    ComponentHealthRepository,
    GuardDecisionRepository,
    IncidentRepository,
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
    OperationFamily,
    RecoveryAttemptStatus,
    SessionTargetKind,
    TargetRiskLevel,
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


if __name__ == "__main__":
    unittest.main()
