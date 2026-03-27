"""Watchdog sweeps for self-healing runtime supervision."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from time import sleep

from cockpit.core.dispatch.event_bus import EventBus
from cockpit.ops.services.component_watch_service import ComponentWatchService
from cockpit.plugins.services.plugin_service import PluginService
from cockpit.ops.services.self_healing_service import SelfHealingService
from cockpit.ops.events.health import (
    ComponentWatchObserved,
    TaskHeartbeatMissed,
    TaskExitedUnexpectedly,
    TunnelFailureDetected,
)
from cockpit.datasources.adapters.tunnel_manager import SSHTunnelManager
from cockpit.runtime.task_supervisor import SupervisedTaskContext, TaskSupervisor
from cockpit.core.enums import ComponentKind, WatchProbeOutcome


@dataclass(slots=True)
class RuntimeHealthMonitor:
    """Poll task and tunnel runtime state and feed self-healing orchestration."""

    event_bus: EventBus
    task_supervisor: TaskSupervisor
    tunnel_manager: SSHTunnelManager
    self_healing_service: SelfHealingService
    plugin_service: PluginService | None = None
    component_watch_service: ComponentWatchService | None = None
    notification_service: object | None = None
    interval_seconds: float = 2.0
    task_name: str = "runtime-health-monitor"
    _reported_stale_tasks: set[str] = field(default_factory=set)
    _reported_dead_tasks: set[str] = field(default_factory=set)
    _reported_dead_tunnels: set[str] = field(default_factory=set)
    _reported_failed_plugin_hosts: set[str] = field(default_factory=set)
    _lock: Lock = field(default_factory=Lock)

    def start(self) -> None:
        self.task_supervisor.spawn_supervised(
            self.task_name,
            self._run,
            heartbeat_timeout_seconds=max(3.0, self.interval_seconds * 3),
            restartable=True,
            metadata={
                "component_id": f"task:{self.task_name}",
                "component_kind": ComponentKind.BACKGROUND_TASK.value,
                "display_name": "Runtime Health Monitor",
            },
        )

    def stop(self) -> None:
        self.task_supervisor.stop(self.task_name, timeout=1.0)

    def _run(self, context: SupervisedTaskContext) -> None:
        while not context.stop_event.is_set():
            context.heartbeat("sweep")
            self._sweep_tasks()
            self._sweep_tunnels()
            self._sweep_plugin_hosts()
            self._sweep_component_watches()
            self.self_healing_service.run_due_recoveries()
            self._sweep_notification_deliveries()
            sleep(self.interval_seconds)

    def _sweep_tasks(self) -> None:
        snapshots = self.task_supervisor.list_snapshots()
        with self._lock:
            current_names = {snapshot.name for snapshot in snapshots}
            self._reported_stale_tasks.intersection_update(current_names)
            self._reported_dead_tasks.intersection_update(current_names)
        for snapshot in snapshots:
            if snapshot.name == self.task_name:
                continue
            if not snapshot.alive:
                with self._lock:
                    if snapshot.name in self._reported_dead_tasks:
                        continue
                    self._reported_dead_tasks.add(snapshot.name)
                self.event_bus.publish(
                    TaskExitedUnexpectedly(
                        task_name=snapshot.name,
                        restartable=snapshot.restartable,
                        error_message=snapshot.last_error,
                        metadata=dict(snapshot.metadata),
                    )
                )
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
                self._reported_dead_tasks.discard(snapshot.name)

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

    def _sweep_plugin_hosts(self) -> None:
        if self.plugin_service is None:
            return
        snapshots = self.plugin_service.host_snapshots()
        current_ids = {
            str(snapshot.get("plugin_id", ""))
            for snapshot in snapshots
            if isinstance(snapshot.get("plugin_id"), str)
        }
        with self._lock:
            self._reported_failed_plugin_hosts.intersection_update(current_ids)
        for snapshot in snapshots:
            plugin_id = str(snapshot.get("plugin_id", "")).strip()
            if not plugin_id:
                continue
            alive = bool(snapshot.get("alive", False))
            if alive:
                self.event_bus.publish(
                    ComponentWatchObserved(
                        component_id=str(
                            snapshot.get("component_id", f"plugin-host:{plugin_id}")
                        ),
                        component_kind=ComponentKind.PLUGIN_HOST,
                        outcome=WatchProbeOutcome.SUCCESS,
                        status="running",
                        summary="plugin host is running",
                        metadata={
                            "plugin_id": plugin_id,
                            "display_name": snapshot.get("display_name", plugin_id),
                        },
                    )
                )
                with self._lock:
                    self._reported_failed_plugin_hosts.discard(plugin_id)
                continue
            with self._lock:
                if plugin_id in self._reported_failed_plugin_hosts:
                    continue
                self._reported_failed_plugin_hosts.add(plugin_id)
            self.event_bus.publish(
                ComponentWatchObserved(
                    component_id=str(
                        snapshot.get("component_id", f"plugin-host:{plugin_id}")
                    ),
                    component_kind=ComponentKind.PLUGIN_HOST,
                    outcome=WatchProbeOutcome.FAILURE,
                    status=str(snapshot.get("status", "host_failed")),
                    summary=str(
                        snapshot.get("last_error")
                        or snapshot.get("status")
                        or "plugin host is not running"
                    ),
                    metadata={
                        "plugin_id": plugin_id,
                        "display_name": snapshot.get("display_name", plugin_id),
                    },
                )
            )

    def _sweep_component_watches(self) -> None:
        if self.component_watch_service is None:
            return
        self.component_watch_service.probe_due_watches()

    def _sweep_notification_deliveries(self) -> None:
        if self.notification_service is None:
            return
        run_due_deliveries = getattr(
            self.notification_service, "run_due_deliveries", None
        )
        if callable(run_due_deliveries):
            run_due_deliveries()
