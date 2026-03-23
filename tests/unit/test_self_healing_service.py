from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.application.services.recovery_policy_service import RecoveryPolicyService
from cockpit.application.services.self_healing_service import SelfHealingService
from cockpit.domain.events.health_events import TaskHeartbeatMissed, TunnelFailureDetected
from cockpit.domain.events.runtime_events import PTYStarted, PTYStartupFailed, TerminalExited
from cockpit.infrastructure.persistence.ops_repositories import (
    ComponentHealthRepository,
    IncidentRepository,
    RecoveryAttemptRepository,
)
from cockpit.infrastructure.persistence.sqlite_store import SQLiteStore
from cockpit.runtime.task_supervisor import TaskSupervisor
from cockpit.shared.enums import ComponentKind, HealthStatus, SessionTargetKind


class _FakePTYManager:
    def __init__(self) -> None:
        self.calls = []
        self.return_session = object()

    def restart_session(self, panel_id, cwd, *, command=None, target_kind, target_ref):
        self.calls.append((panel_id, cwd, tuple(command or ()), target_kind, target_ref))
        return self.return_session


class _FakeTunnelManager:
    def __init__(self) -> None:
        self.calls = []

    def reconnect_tunnel(self, profile_id):
        self.calls.append(profile_id)
        class Tunnel:
            profile_id = profile_id
            target_ref = "ops@example.com"
            remote_host = "db.internal"
            remote_port = 5432
            reconnect_count = 1
        return Tunnel()


class _FakeTaskSupervisor(TaskSupervisor):
    def __init__(self) -> None:
        super().__init__()
        self.restarted = []

    def restart(self, name: str):
        self.restarted.append(name)
        return super().spawn_supervised(
            name,
            lambda context: context.heartbeat("restarted"),
            heartbeat_timeout_seconds=1.0,
            restartable=True,
            restart_count=1,
        )


class SelfHealingServiceTests(unittest.TestCase):
    def test_pty_failure_schedules_recovery_and_resolves_on_start(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            bus = EventBus()
            pty_manager = _FakePTYManager()
            service = SelfHealingService(
                event_bus=bus,
                recovery_policy_service=RecoveryPolicyService(),
                component_health_repository=ComponentHealthRepository(store),
                incident_repository=IncidentRepository(store),
                recovery_attempt_repository=RecoveryAttemptRepository(store),
                pty_manager=pty_manager,
                tunnel_manager=_FakeTunnelManager(),
                task_supervisor=_FakeTaskSupervisor(),
            )

            bus.publish(
                PTYStartupFailed(
                    panel_id="work-panel",
                    cwd="/tmp/project",
                    reason="shell exited immediately",
                    command=("/bin/sh", "-lc", "exit 1"),
                    target_kind=SessionTargetKind.LOCAL,
                )
            )

            state = service.list_health_states()[0]
            self.assertEqual(state.status, HealthStatus.RECOVERING)
            service.retry_component("pty:work-panel")
            self.assertEqual(len(pty_manager.calls), 1)

            bus.publish(
                PTYStarted(
                    panel_id="work-panel",
                    cwd="/tmp/project",
                    command=("/bin/sh", "-lc", "sleep 30"),
                    target_kind=SessionTargetKind.LOCAL,
                )
            )
            updated = service.list_health_states()[0]
            self.assertEqual(updated.status, HealthStatus.HEALTHY)

    def test_tunnel_failure_can_quarantine_after_repeated_failures(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            bus = EventBus()
            service = SelfHealingService(
                event_bus=bus,
                recovery_policy_service=RecoveryPolicyService(),
                component_health_repository=ComponentHealthRepository(store),
                incident_repository=IncidentRepository(store),
                recovery_attempt_repository=RecoveryAttemptRepository(store),
                pty_manager=_FakePTYManager(),
                tunnel_manager=_FakeTunnelManager(),
                task_supervisor=_FakeTaskSupervisor(),
            )

            event = TunnelFailureDetected(
                profile_id="pg-main",
                target_ref="ops@example.com",
                remote_host="db.internal",
                remote_port=5432,
                reconnect_count=0,
                reason="host key verification failed",
            )
            bus.publish(event)
            state = service.list_health_states()[0]
            self.assertEqual(state.status, HealthStatus.QUARANTINED)

    def test_task_heartbeat_miss_schedules_recovery(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            bus = EventBus()
            task_supervisor = _FakeTaskSupervisor()
            service = SelfHealingService(
                event_bus=bus,
                recovery_policy_service=RecoveryPolicyService(),
                component_health_repository=ComponentHealthRepository(store),
                incident_repository=IncidentRepository(store),
                recovery_attempt_repository=RecoveryAttemptRepository(store),
                pty_manager=_FakePTYManager(),
                tunnel_manager=_FakeTunnelManager(),
                task_supervisor=task_supervisor,
            )

            bus.publish(
                TaskHeartbeatMissed(
                    task_name="watcher",
                    heartbeat_timeout_seconds=5.0,
                    age_seconds=8.0,
                    restartable=True,
                    metadata={},
                )
            )
            service.retry_component("task:watcher")
            self.assertIn("watcher", task_supervisor.restarted)


if __name__ == "__main__":
    unittest.main()
