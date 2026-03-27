from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cockpit.core.dispatch.event_bus import EventBus
from cockpit.ops.services.component_watch_service import ComponentWatchService
from cockpit.datasources.models.datasource import DataSourceOperationResult
from cockpit.infrastructure.docker.docker_adapter import (
    DockerContainerDiagnosticsSnapshot,
)
from cockpit.ops.repositories import (
    ComponentWatchRepository,
    OperationDiagnosticsRepository,
)
from cockpit.core.persistence.sqlite_store import SQLiteStore
from cockpit.core.enums import SessionTargetKind, WatchProbeOutcome


class _FakeDatasourceService:
    def __init__(self, *, success: bool) -> None:
        self._success = success

    def inspect_profile(self, profile_id: str) -> DataSourceOperationResult:
        return DataSourceOperationResult(
            success=self._success,
            profile_id=profile_id,
            backend="postgres",
            operation="inspect",
            message="reachable" if self._success else "unreachable",
        )


class _FakeDockerAdapter:
    def __init__(self, *, healthy: bool) -> None:
        self._healthy = healthy

    def collect_diagnostics(
        self, *, target_kind=SessionTargetKind.LOCAL, target_ref=None
    ):
        del target_kind, target_ref
        return [
            DockerContainerDiagnosticsSnapshot(
                container_id="abc123",
                name="web",
                image="nginx:latest",
                state="running" if self._healthy else "exited",
                status="Up 1 minute" if self._healthy else "Exited (1)",
                ports="80/tcp",
                health="healthy" if self._healthy else "unhealthy",
                restart_policy="always",
                exit_code=0 if self._healthy else 1,
                restart_count=1,
                recent_logs=["ready"] if self._healthy else ["crashed"],
            )
        ]


class ComponentWatchServiceTests(unittest.TestCase):
    def test_datasource_watch_probe_records_success(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            service = ComponentWatchService(
                event_bus=EventBus(),
                repository=ComponentWatchRepository(store),
                datasource_service=_FakeDatasourceService(success=True),
                docker_adapter=_FakeDockerAdapter(healthy=True),
                operation_diagnostics_repository=OperationDiagnosticsRepository(store),
            )
            config = service.new_datasource_watch(profile_id="analytics")
            service.save_config(config)

            state = service.probe_watch(config.id)

            self.assertEqual(state.component_id, "watch:datasource:analytics")
            self.assertEqual(state.last_outcome, WatchProbeOutcome.SUCCESS)
            self.assertEqual(state.last_status, "reachable")

    def test_docker_watch_probe_records_failure(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            service = ComponentWatchService(
                event_bus=EventBus(),
                repository=ComponentWatchRepository(store),
                datasource_service=_FakeDatasourceService(success=True),
                docker_adapter=_FakeDockerAdapter(healthy=False),
                operation_diagnostics_repository=OperationDiagnosticsRepository(store),
            )
            config = service.new_docker_watch(container_ref="web")
            service.save_config(config)

            state = service.probe_watch(config.id)

            self.assertEqual(state.component_id, "watch:docker:web")
            self.assertEqual(state.last_outcome, WatchProbeOutcome.FAILURE)
            self.assertEqual(state.last_status, "unhealthy")


if __name__ == "__main__":
    unittest.main()
