from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cockpit.application.services.operations_diagnostics_service import OperationsDiagnosticsService
from cockpit.domain.models.datasource import DataSourceProfile
from cockpit.domain.models.policy import GuardDecision
from cockpit.infrastructure.db.database_adapter import DatabaseAdapter
from cockpit.infrastructure.docker.docker_adapter import DockerContainerDiagnosticsSnapshot
from cockpit.infrastructure.http.http_adapter import HttpAdapter
from cockpit.infrastructure.persistence.ops_repositories import (
    ComponentHealthRepository,
    GuardDecisionRepository,
    IncidentRepository,
    OperationDiagnosticsRepository,
)
from cockpit.infrastructure.persistence.sqlite_store import SQLiteStore
from cockpit.shared.enums import (
    ComponentKind,
    GuardActionKind,
    GuardDecisionOutcome,
    OperationFamily,
    SessionTargetKind,
    TargetRiskLevel,
)


class _FakeDockerAdapter:
    def collect_diagnostics(self):
        return [
            DockerContainerDiagnosticsSnapshot(
                container_id="abc123",
                name="web",
                image="nginx:latest",
                state="running",
                status="Up 1 minute",
                ports="80/tcp",
                health="healthy",
                restart_policy="always",
                exit_code=0,
                restart_count=1,
                recent_logs=["ready"],
            )
        ]


class _FakeDataSourceService:
    def list_profiles(self):
        return [
            DataSourceProfile(
                id="analytics",
                name="Analytics",
                backend="postgres",
                target_kind=SessionTargetKind.SSH,
                target_ref="ops@example.com",
                risk_level="stage",
                capabilities=["can_query", "can_mutate", "can_explain"],
            )
        ]


class _FakeTunnelManager:
    def snapshot_tunnels(self):
        return [{"profile_id": "analytics", "alive": True}]


class OperationsDiagnosticsServiceTests(unittest.TestCase):
    def test_aggregates_docker_db_and_curl_payloads(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            guard_repo = GuardDecisionRepository(store)
            ops_repo = OperationDiagnosticsRepository(store)
            guard_repo.record(
                GuardDecision(
                    command_id="cmd-1",
                    action_kind=GuardActionKind.DB_MUTATION,
                    component_kind=ComponentKind.DATASOURCE,
                    target_risk=TargetRiskLevel.STAGE,
                    outcome=GuardDecisionOutcome.REQUIRE_CONFIRMATION,
                    explanation="confirmation required",
                    requires_confirmation=True,
                    metadata={"subject_ref": "analytics"},
                )
            )
            ops_repo.record(
                operation_family=OperationFamily.DB,
                component_id="datasource:analytics",
                subject_ref="analytics",
                success=False,
                severity="high",
                summary="query failed",
                payload={"message": "syntax error"},
            )
            ops_repo.record(
                operation_family=OperationFamily.CURL,
                component_id="http:example",
                subject_ref="https://example.com/api",
                success=False,
                severity="high",
                summary="500 error",
                payload={"method": "POST", "risk_level": "prod", "placeholder_names": ["TOKEN"]},
            )
            service = OperationsDiagnosticsService(
                docker_adapter=_FakeDockerAdapter(),
                database_adapter=DatabaseAdapter(),
                http_adapter=HttpAdapter(),
                datasource_service=_FakeDataSourceService(),
                tunnel_manager=_FakeTunnelManager(),
                component_health_repository=ComponentHealthRepository(store),
                incident_repository=IncidentRepository(store),
                guard_decision_repository=guard_repo,
                operation_diagnostics_repository=ops_repo,
            )

            overview = service.overview()

            self.assertEqual(len(overview["docker"]), 1)
            self.assertEqual(len(overview["db"]), 1)
            self.assertEqual(len(overview["curl"]), 1)
            self.assertIn("notification", overview)
            self.assertEqual(overview["db"][0]["recent_failure_count"], 1)
            self.assertEqual(overview["curl"][0]["failure_streak"], 1)


if __name__ == "__main__":
    unittest.main()
