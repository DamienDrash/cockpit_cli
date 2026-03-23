"""Watchdog sweeps for self-healing runtime supervision."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from time import sleep

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.application.services.self_healing_service import SelfHealingService
from cockpit.domain.events.health_events import TaskHeartbeatMissed, TunnelFailureDetected
from cockpit.infrastructure.ssh.tunnel_manager import SSHTunnelManager
from cockpit.runtime.task_supervisor import SupervisedTaskContext, TaskSupervisor


@dataclass(slots=True)
class RuntimeHealthMonitor:
    """Poll task and tunnel runtime state and feed self-healing orchestration."""

    event_bus: EventBus
    task_supervisor: TaskSupervisor
    tunnel_manager: SSHTunnelManager
    self_healing_service: SelfHealingService
    interval_seconds: float = 2.0
    task_name: str = "runtime-health-monitor"
    _reported_stale_tasks: set[str] = field(default_factory=set)
    _reported_dead_tunnels: set[str] = field(default_factory=set)
    _lock: Lock = field(default_factory=Lock)

    def start(self) -> None:
        self.task_supervisor.spawn_supervised(
            self.task_name,
            self._run,
            heartbeat_timeout_seconds=max(3.0, self.interval_seconds * 3),
            restartable=True,
            metadata={"component_kind": "background_monitor"},
        )

    def stop(self) -> None:
        self.task_supervisor.stop(self.task_name, timeout=1.0)

    def _run(self, context: SupervisedTaskContext) -> None:
        while not context.stop_event.is_set():
            context.heartbeat("sweep")
            self._sweep_tasks()
            self._sweep_tunnels()
            self.self_healing_service.run_due_recoveries()
            sleep(self.interval_seconds)

    def _sweep_tasks(self) -> None:
        snapshots = self.task_supervisor.list_snapshots()
        with self._lock:
            current_names = {snapshot.name for snapshot in snapshots}
            self._reported_stale_tasks.intersection_update(current_names)
        for snapshot in snapshots:
            if snapshot.name == self.task_name:
                continue
            if snapshot.stale:
                with self._lock:
                    if snapshot.name in self._reported_stale_tasks:
                        continue
                    self._reported_stale_tasks.add(snapshot.name)
                self.event_bus.publish(
                    TaskHeartbeatMissed(
                        task_name=snapshot.name,
                        heartbeat_timeout_seconds=snapshot.heartbeat_timeout_seconds,
                        age_seconds=snapshot.age_seconds,
                        restartable=snapshot.restartable,
                        metadata=dict(snapshot.metadata),
                    )
                )
                continue
            self.self_healing_service.observe_task_snapshot(snapshot)
            with self._lock:
                self._reported_stale_tasks.discard(snapshot.name)

    def _sweep_tunnels(self) -> None:
        snapshots = self.tunnel_manager.snapshot_tunnels()
        current_ids = {
            str(snapshot.get("profile_id", ""))
            for snapshot in snapshots
            if isinstance(snapshot.get("profile_id"), str)
        }
        with self._lock:
            self._reported_dead_tunnels.intersection_update(current_ids)
        for snapshot in snapshots:
            profile_id = str(snapshot.get("profile_id", "")).strip()
            if not profile_id:
                continue
            alive = bool(snapshot.get("alive", False))
            if alive:
                self.self_healing_service.observe_tunnel_snapshot(snapshot)
                with self._lock:
                    self._reported_dead_tunnels.discard(profile_id)
                continue
            with self._lock:
                if profile_id in self._reported_dead_tunnels:
                    continue
                self._reported_dead_tunnels.add(profile_id)
            self.event_bus.publish(
                TunnelFailureDetected(
                    profile_id=profile_id,
                    target_ref=str(snapshot.get("target_ref", "")),
                    remote_host=str(snapshot.get("remote_host", "")),
                    remote_port=int(snapshot.get("remote_port", 0) or 0),
                    reconnect_count=int(snapshot.get("reconnect_count", 0) or 0),
                    reason=str(snapshot.get("last_failure", "tunnel process exited")),
                    metadata={"local_port": snapshot.get("local_port")},
                )
            )
