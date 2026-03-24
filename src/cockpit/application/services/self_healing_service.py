"""Central recovery orchestration and incident lifecycle management."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.application.services.recovery_policy_service import (
    RecoveryEvaluation,
    RecoveryPolicyService,
)
from cockpit.domain.events.health_events import (
    ComponentHealthChanged,
    ComponentQuarantineCleared,
    ComponentQuarantined,
    ComponentWatchObserved,
    IncidentOpened,
    IncidentStatusChanged,
    RecoveryAttemptRecorded,
    TaskExitedUnexpectedly,
    TaskHeartbeatMissed,
    TunnelFailureDetected,
)
from cockpit.domain.events.runtime_events import PTYStarted, PTYStartupFailed, TerminalExited
from cockpit.domain.models.health import (
    ComponentHealthState,
    ComponentRef,
    IncidentRecord,
    IncidentTimelineEntry,
    RecoveryAttempt,
)
from cockpit.infrastructure.persistence.ops_repositories import (
    ComponentHealthRepository,
    IncidentRepository,
    RecoveryAttemptRepository,
)
from cockpit.infrastructure.ssh.tunnel_manager import SSHTunnelManager
from cockpit.runtime.pty_manager import PTYManager
from cockpit.runtime.task_supervisor import TaskSnapshot, TaskSupervisor
from cockpit.shared.enums import (
    ComponentKind,
    HealthStatus,
    IncidentSeverity,
    IncidentStatus,
    RecoveryAttemptStatus,
    SessionTargetKind,
)
from cockpit.shared.utils import make_id, utc_now


@dataclass(slots=True, frozen=True)
class HealthSummary:
    """Aggregated health counters for admin diagnostics."""

    healthy: int
    degraded: int
    recovering: int
    failed: int
    quarantined: int

    def to_dict(self) -> dict[str, int]:
        return {
            "healthy": self.healthy,
            "degraded": self.degraded,
            "recovering": self.recovering,
            "failed": self.failed,
            "quarantined": self.quarantined,
        }


class SelfHealingService:
    """Drive deterministic recovery, cooldown, and quarantine transitions."""

    _SEVERITY_ORDER = {
        IncidentSeverity.INFO: 0,
        IncidentSeverity.WARNING: 1,
        IncidentSeverity.HIGH: 2,
        IncidentSeverity.CRITICAL: 3,
    }

    def __init__(
        self,
        *,
        event_bus: EventBus,
        recovery_policy_service: RecoveryPolicyService,
        component_health_repository: ComponentHealthRepository,
        incident_repository: IncidentRepository,
        recovery_attempt_repository: RecoveryAttemptRepository,
        pty_manager: PTYManager,
        tunnel_manager: SSHTunnelManager,
        task_supervisor: TaskSupervisor,
        plugin_service: object | None = None,
        component_watch_service: object | None = None,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._recovery_policy_service = recovery_policy_service
        self._component_health_repository = component_health_repository
        self._incident_repository = incident_repository
        self._recovery_attempt_repository = recovery_attempt_repository
        self._pty_manager = pty_manager
        self._tunnel_manager = tunnel_manager
        self._task_supervisor = task_supervisor
        self._plugin_service = plugin_service
        self._component_watch_service = component_watch_service
        self._now_factory = now_factory or utc_now

        self._event_bus.subscribe(PTYStarted, self._on_pty_started)
        self._event_bus.subscribe(PTYStartupFailed, self._on_pty_startup_failed)
        self._event_bus.subscribe(TerminalExited, self._on_terminal_exited)
        self._event_bus.subscribe(TaskHeartbeatMissed, self._on_task_heartbeat_missed)
        self._event_bus.subscribe(TaskExitedUnexpectedly, self._on_task_exited_unexpectedly)
        self._event_bus.subscribe(TunnelFailureDetected, self._on_tunnel_failure_detected)
        self._event_bus.subscribe(ComponentWatchObserved, self._on_component_watch_observed)

    def list_health_states(self) -> list[ComponentHealthState]:
        return self._component_health_repository.list_all()

    def list_quarantined(self) -> list[ComponentHealthState]:
        return self._component_health_repository.list_quarantined()

    def health_summary(self) -> HealthSummary:
        states = self._component_health_repository.list_all()
        counts = {
            HealthStatus.HEALTHY: 0,
            HealthStatus.DEGRADED: 0,
            HealthStatus.RECOVERING: 0,
            HealthStatus.FAILED: 0,
            HealthStatus.QUARANTINED: 0,
        }
        for state in states:
            counts[state.status] += 1
        return HealthSummary(
            healthy=counts[HealthStatus.HEALTHY],
            degraded=counts[HealthStatus.DEGRADED],
            recovering=counts[HealthStatus.RECOVERING],
            failed=counts[HealthStatus.FAILED],
            quarantined=counts[HealthStatus.QUARANTINED],
        )

    def reset_quarantine(self, component_id: str, *, reason: str = "manual reset") -> None:
        state = self._require_state(component_id)
        previous_status = state.status
        state.quarantined = False
        state.quarantine_reason = None
        state.cooldown_until = None
        state.next_recovery_at = None
        state.exhaustion_count = 0
        state.status = HealthStatus.DEGRADED
        state.updated_at = self._now()
        self._component_health_repository.save(state)
        self._component_health_repository.record_transition(
            component_id=state.component_id,
            component_kind=state.component_kind,
            previous_status=previous_status,
            new_status=state.status,
            reason=reason,
        )
        self._event_bus.publish(
            ComponentQuarantineCleared(
                component_id=state.component_id,
                component_kind=state.component_kind,
                reason=reason,
            )
        )

    def retry_component(self, component_id: str) -> bool:
        state = self._component_health_repository.get(component_id)
        if state is None:
            return False
        state.next_recovery_at = self._now()
        state.cooldown_until = None
        if state.status is not HealthStatus.QUARANTINED:
            state.status = HealthStatus.RECOVERING
        self._component_health_repository.save(state)
        self.run_due_recoveries()
        return True

    def observe_task_snapshot(self, snapshot: TaskSnapshot) -> None:
        component_ref = self._task_component_ref(snapshot)
        state = self._component_health_repository.get(component_ref.component_id)
        if snapshot.stale or not snapshot.alive:
            return
        state = state or ComponentHealthState(
            component_id=component_ref.component_id,
            component_kind=component_ref.kind,
            display_name=component_ref.display_name,
            status=HealthStatus.HEALTHY,
            target_kind=self._task_target_kind(snapshot),
        )
        self._mark_component_healthy(
            state=state,
            heartbeat_at=snapshot.last_heartbeat_at or snapshot.started_at,
            payload={
                "task_name": snapshot.name,
                "restartable": snapshot.restartable,
                "restart_count": snapshot.restart_count,
                "metadata": snapshot.metadata,
                "component_kind": component_ref.kind.value,
                "component_id": component_ref.component_id,
            },
        )

    def observe_tunnel_snapshot(self, snapshot: dict[str, object]) -> None:
        profile_id = str(snapshot.get("profile_id", "")).strip()
        if not profile_id or not bool(snapshot.get("alive", False)):
            return
        component_ref = ComponentRef(
            component_id=f"ssh-tunnel:{profile_id}",
            kind=ComponentKind.SSH_TUNNEL,
            display_name=f"SSH tunnel {profile_id}",
        )
        state = self._component_health_repository.get(component_ref.component_id)
        state = state or ComponentHealthState(
            component_id=component_ref.component_id,
            component_kind=component_ref.kind,
            display_name=component_ref.display_name,
            status=HealthStatus.HEALTHY,
            target_kind=SessionTargetKind.SSH,
            target_ref=str(snapshot.get("target_ref", "")) or None,
        )
        self._mark_component_healthy(
            state=state,
            heartbeat_at=self._now(),
            payload={
                "profile_id": profile_id,
                "target_ref": snapshot.get("target_ref"),
                "remote_host": snapshot.get("remote_host"),
                "remote_port": snapshot.get("remote_port"),
                "reconnect_count": snapshot.get("reconnect_count", 0),
            },
        )

    def run_due_recoveries(self) -> None:
        now = self._now()
        for state in self._component_health_repository.list_due_recoveries(now):
            attempt = self._recovery_attempt_repository.latest_pending_for_component(
                state.component_id
            )
            if attempt is None:
                continue
            attempt.status = RecoveryAttemptStatus.RUNNING
            attempt.started_at = now
            self._recovery_attempt_repository.save(attempt)
            self._event_bus.publish(
                RecoveryAttemptRecorded(
                    attempt_id=attempt.id,
                    incident_id=attempt.incident_id,
                    component_id=state.component_id,
                    component_kind=state.component_kind,
                    status=attempt.status,
                    action=attempt.action,
                    attempt_number=attempt.attempt_number,
                )
            )
            if state.component_kind is ComponentKind.PTY_SESSION:
                self._run_pty_recovery(state, attempt)
                continue
            if state.component_kind is ComponentKind.SSH_TUNNEL:
                self._run_tunnel_recovery(state, attempt)
                continue
            if state.component_kind is ComponentKind.BACKGROUND_TASK:
                self._run_task_recovery(state, attempt)
                continue
            if state.component_kind is ComponentKind.WEB_ADMIN:
                self._run_task_recovery(state, attempt)
                continue
            if state.component_kind is ComponentKind.PLUGIN_HOST:
                self._run_plugin_host_recovery(state, attempt)
                continue
            if state.component_kind in {
                ComponentKind.DATASOURCE_WATCH,
                ComponentKind.DOCKER_CONTAINER_WATCH,
            }:
                self._run_watch_recovery(state, attempt)

    def _run_pty_recovery(self, state: ComponentHealthState, attempt: RecoveryAttempt) -> None:
        payload = self._runtime_payload(state)
        panel_id = str(payload.get("panel_id", "")).strip() or state.component_id.removeprefix("pty:")
        cwd = str(payload.get("cwd", "")).strip()
        raw_command = payload.get("command", [])
        command = (
            [str(item) for item in raw_command if isinstance(item, str)]
            if isinstance(raw_command, list)
            else None
        )
        target_ref = payload.get("target_ref")
        target_kind_raw = payload.get("target_kind", SessionTargetKind.LOCAL.value)
        target_kind = (
            target_kind_raw
            if isinstance(target_kind_raw, SessionTargetKind)
            else SessionTargetKind(str(target_kind_raw))
        )
        session = self._pty_manager.restart_session(
            panel_id,
            cwd,
            command=command,
            target_kind=target_kind,
            target_ref=target_ref if isinstance(target_ref, str) else None,
        )
        if session is not None:
            attempt.status = RecoveryAttemptStatus.SUCCEEDED
            attempt.finished_at = self._now()
            self._recovery_attempt_repository.save(attempt)
            self._event_bus.publish(
                RecoveryAttemptRecorded(
                    attempt_id=attempt.id,
                    incident_id=attempt.incident_id,
                    component_id=state.component_id,
                    component_kind=state.component_kind,
                    status=attempt.status,
                    action=attempt.action,
                    attempt_number=attempt.attempt_number,
                )
            )

    def _run_tunnel_recovery(self, state: ComponentHealthState, attempt: RecoveryAttempt) -> None:
        payload = self._runtime_payload(state)
        profile_id = (
            str(payload.get("profile_id", "")).strip()
            or state.component_id.removeprefix("ssh-tunnel:")
        )
        try:
            tunnel = self._tunnel_manager.reconnect_tunnel(profile_id)
        except Exception as exc:
            attempt.status = RecoveryAttemptStatus.FAILED
            attempt.finished_at = self._now()
            attempt.error_message = str(exc)
            self._recovery_attempt_repository.save(attempt)
            self._handle_failure(
                component_ref=ComponentRef(
                    component_id=state.component_id,
                    kind=ComponentKind.SSH_TUNNEL,
                    display_name=state.display_name,
                ),
                reason=str(exc),
                severity=IncidentSeverity.HIGH,
                target_kind=SessionTargetKind.SSH,
                target_ref=state.target_ref,
                workspace_id=state.workspace_id,
                session_id=state.session_id,
                payload=dict(state.payload),
                pending_attempt_already_failed=True,
            )
            return
        attempt.status = RecoveryAttemptStatus.SUCCEEDED
        attempt.finished_at = self._now()
        self._recovery_attempt_repository.save(attempt)
        self.observe_tunnel_snapshot(
            {
                "profile_id": tunnel.profile_id,
                "target_ref": tunnel.target_ref,
                "remote_host": tunnel.remote_host,
                "remote_port": tunnel.remote_port,
                "reconnect_count": tunnel.reconnect_count,
                "alive": True,
            }
        )

    def _run_task_recovery(self, state: ComponentHealthState, attempt: RecoveryAttempt) -> None:
        payload = self._runtime_payload(state)
        task_name = (
            str(payload.get("task_name", "")).strip()
            or state.component_id.removeprefix("task:")
        )
        try:
            task = self._task_supervisor.restart(task_name)
        except Exception as exc:
            attempt.status = RecoveryAttemptStatus.FAILED
            attempt.finished_at = self._now()
            attempt.error_message = str(exc)
            self._recovery_attempt_repository.save(attempt)
            self._handle_failure(
                component_ref=ComponentRef(
                    component_id=state.component_id,
                    kind=state.component_kind,
                    display_name=state.display_name,
                ),
                reason=str(exc),
                severity=(
                    IncidentSeverity.HIGH
                    if state.component_kind is ComponentKind.WEB_ADMIN
                    else IncidentSeverity.WARNING
                ),
                target_kind=SessionTargetKind.LOCAL,
                target_ref=None,
                workspace_id=state.workspace_id,
                session_id=state.session_id,
                payload=dict(state.payload),
                pending_attempt_already_failed=True,
            )
            return
        attempt.status = RecoveryAttemptStatus.SUCCEEDED
        attempt.finished_at = self._now()
        self._recovery_attempt_repository.save(attempt)
        snapshot = self._task_supervisor.get_snapshot(task.name)
        if snapshot is not None:
            self.observe_task_snapshot(snapshot)

    def _run_plugin_host_recovery(self, state: ComponentHealthState, attempt: RecoveryAttempt) -> None:
        payload = self._runtime_payload(state)
        plugin_id = str(payload.get("plugin_id", "")).strip()
        restart_host = getattr(self._plugin_service, "restart_host", None)
        if not plugin_id or not callable(restart_host):
            attempt.status = RecoveryAttemptStatus.FAILED
            attempt.finished_at = self._now()
            attempt.error_message = "Plugin host recovery is unavailable."
            self._recovery_attempt_repository.save(attempt)
            return
        try:
            restart_host(plugin_id)
        except Exception as exc:
            attempt.status = RecoveryAttemptStatus.FAILED
            attempt.finished_at = self._now()
            attempt.error_message = str(exc)
            self._recovery_attempt_repository.save(attempt)
            self._handle_failure(
                component_ref=ComponentRef(
                    component_id=state.component_id,
                    kind=ComponentKind.PLUGIN_HOST,
                    display_name=state.display_name,
                ),
                reason=str(exc),
                severity=IncidentSeverity.HIGH,
                target_kind=SessionTargetKind.LOCAL,
                target_ref=None,
                workspace_id=state.workspace_id,
                session_id=state.session_id,
                payload=dict(state.payload),
                pending_attempt_already_failed=True,
            )
            return
        attempt.status = RecoveryAttemptStatus.SUCCEEDED
        attempt.finished_at = self._now()
        self._recovery_attempt_repository.save(attempt)
        self._mark_component_healthy(
            state=state,
            heartbeat_at=self._now(),
            payload=dict(payload),
        )

    def _run_watch_recovery(self, state: ComponentHealthState, attempt: RecoveryAttempt) -> None:
        probe_watch = getattr(self._component_watch_service, "probe_watch_for_component", None)
        if not callable(probe_watch):
            attempt.status = RecoveryAttemptStatus.FAILED
            attempt.finished_at = self._now()
            attempt.error_message = "Watch recovery is unavailable."
            self._recovery_attempt_repository.save(attempt)
            return
        try:
            probe_watch(state.component_id)
        except Exception as exc:
            attempt.status = RecoveryAttemptStatus.FAILED
            attempt.finished_at = self._now()
            attempt.error_message = str(exc)
            self._recovery_attempt_repository.save(attempt)
            return
        attempt.status = RecoveryAttemptStatus.SUCCEEDED
        attempt.finished_at = self._now()
        self._recovery_attempt_repository.save(attempt)

    def _on_pty_started(self, event: PTYStarted) -> None:
        component_id = f"pty:{event.panel_id}"
        state = self._component_health_repository.get(component_id) or ComponentHealthState(
            component_id=component_id,
            component_kind=ComponentKind.PTY_SESSION,
            display_name=f"PTY {event.panel_id}",
            status=HealthStatus.HEALTHY,
            target_kind=event.target_kind,
            target_ref=event.target_ref,
        )
        self._mark_component_healthy(
            state=state,
            heartbeat_at=self._now(),
            payload={
                "panel_id": event.panel_id,
                "cwd": event.cwd,
                "command": list(event.command),
                "target_kind": event.target_kind.value,
                "target_ref": event.target_ref,
                "pid": event.pid,
            },
        )

    def _on_pty_startup_failed(self, event: PTYStartupFailed) -> None:
        component_ref = ComponentRef(
            component_id=f"pty:{event.panel_id}",
            kind=ComponentKind.PTY_SESSION,
            display_name=f"PTY {event.panel_id}",
        )
        self._handle_failure(
            component_ref=component_ref,
            reason=event.reason,
            severity=IncidentSeverity.HIGH,
            target_kind=event.target_kind,
            target_ref=event.target_ref,
            payload={
                "panel_id": event.panel_id,
                "cwd": event.cwd,
                "command": list(event.command),
                "target_kind": event.target_kind.value,
                "target_ref": event.target_ref,
            },
        )

    def _on_terminal_exited(self, event: TerminalExited) -> None:
        if event.expected:
            component_id = f"pty:{event.panel_id}"
            state = self._component_health_repository.get(component_id)
            if state is not None:
                state.status = HealthStatus.DEGRADED
                state.next_recovery_at = None
                state.updated_at = self._now()
                self._component_health_repository.save(state)
            return
        self._handle_failure(
            component_ref=ComponentRef(
                component_id=f"pty:{event.panel_id}",
                kind=ComponentKind.PTY_SESSION,
                display_name=f"PTY {event.panel_id}",
            ),
            reason=f"terminal exited with code {event.exit_code}",
            severity=IncidentSeverity.WARNING,
            target_kind=event.target_kind,
            target_ref=event.target_ref,
            payload={
                "panel_id": event.panel_id,
                "cwd": event.cwd,
                "command": list(event.command),
                "target_kind": event.target_kind.value,
                "target_ref": event.target_ref,
                "exit_code": event.exit_code,
            },
        )

    def _on_task_heartbeat_missed(self, event: TaskHeartbeatMissed) -> None:
        component_id = str(event.metadata.get("component_id", f"task:{event.task_name}"))
        component_kind = self._component_kind_from_metadata(
            event.metadata.get("component_kind"),
            default=ComponentKind.BACKGROUND_TASK,
        )
        display_name = str(event.metadata.get("display_name", event.task_name))
        self._handle_failure(
            component_ref=ComponentRef(
                component_id=component_id,
                kind=component_kind,
                display_name=display_name,
            ),
            reason=f"heartbeat stale after {event.age_seconds:.1f}s",
            severity=IncidentSeverity.WARNING,
            target_kind=self._target_kind_from_metadata(event.metadata.get("target_kind")),
            target_ref=(
                str(event.metadata.get("target_ref"))
                if isinstance(event.metadata.get("target_ref"), str)
                else None
            ),
            payload={
                "task_name": event.task_name,
                "heartbeat_timeout_seconds": event.heartbeat_timeout_seconds,
                "age_seconds": event.age_seconds,
                "restartable": event.restartable,
                "metadata": dict(event.metadata),
                "component_kind": component_kind.value,
                "component_id": component_id,
            },
        )

    def _on_task_exited_unexpectedly(self, event: TaskExitedUnexpectedly) -> None:
        component_id = str(event.metadata.get("component_id", f"task:{event.task_name}"))
        component_kind = self._component_kind_from_metadata(
            event.metadata.get("component_kind"),
            default=ComponentKind.BACKGROUND_TASK,
        )
        display_name = str(event.metadata.get("display_name", event.task_name))
        self._handle_failure(
            component_ref=ComponentRef(
                component_id=component_id,
                kind=component_kind,
                display_name=display_name,
            ),
            reason=event.error_message or f"task '{event.task_name}' exited unexpectedly",
            severity=IncidentSeverity.HIGH,
            target_kind=SessionTargetKind.LOCAL,
            target_ref=None,
            payload={
                "task_name": event.task_name,
                "restartable": event.restartable,
                "metadata": dict(event.metadata),
                "component_kind": component_kind.value,
                "component_id": component_id,
            },
        )

    def _on_tunnel_failure_detected(self, event: TunnelFailureDetected) -> None:
        self._handle_failure(
            component_ref=ComponentRef(
                component_id=f"ssh-tunnel:{event.profile_id}",
                kind=ComponentKind.SSH_TUNNEL,
                display_name=f"SSH tunnel {event.profile_id}",
            ),
            reason=event.reason,
            severity=IncidentSeverity.HIGH,
            target_kind=SessionTargetKind.SSH,
            target_ref=event.target_ref,
            payload={
                "profile_id": event.profile_id,
                "target_ref": event.target_ref,
                "remote_host": event.remote_host,
                "remote_port": event.remote_port,
                "reconnect_count": event.reconnect_count,
                "metadata": dict(event.metadata),
            },
        )

    def _on_component_watch_observed(self, event: ComponentWatchObserved) -> None:
        target_kind = self._target_kind_from_metadata(event.metadata.get("target_kind"))
        payload = dict(event.metadata)
        payload["summary"] = event.summary
        if event.outcome.value == "success":
            state = self._component_health_repository.get(event.component_id) or ComponentHealthState(
                component_id=event.component_id,
                component_kind=event.component_kind,
                display_name=str(payload.get("display_name", event.component_id)),
                status=HealthStatus.HEALTHY,
                target_kind=target_kind,
                target_ref=event.target_ref,
            )
            self._mark_component_healthy(
                state=state,
                heartbeat_at=self._now(),
                payload=payload,
            )
            return
        severity = (
            IncidentSeverity.CRITICAL
            if event.component_kind is ComponentKind.PLUGIN_HOST
            else IncidentSeverity.HIGH
        )
        self._handle_failure(
            component_ref=ComponentRef(
                component_id=event.component_id,
                kind=event.component_kind,
                display_name=str(payload.get("display_name", event.component_id)),
            ),
            reason=event.summary,
            severity=severity,
            target_kind=target_kind,
            target_ref=event.target_ref,
            payload=payload,
        )

    def _handle_failure(
        self,
        *,
        component_ref: ComponentRef,
        reason: str,
        severity: IncidentSeverity,
        target_kind: SessionTargetKind,
        target_ref: str | None,
        payload: dict[str, object],
        workspace_id: str | None = None,
        session_id: str | None = None,
        pending_attempt_already_failed: bool = False,
    ) -> None:
        now = self._now()
        state = self._component_health_repository.get(component_ref.component_id)
        if state is None:
            state = ComponentHealthState(
                component_id=component_ref.component_id,
                component_kind=component_ref.kind,
                display_name=component_ref.display_name,
                status=HealthStatus.FAILED,
                workspace_id=workspace_id,
                session_id=session_id,
                target_kind=target_kind,
                target_ref=target_ref,
                payload=dict(payload),
            )
        state.payload.update(payload)
        state.workspace_id = workspace_id or state.workspace_id
        state.session_id = session_id or state.session_id
        state.target_kind = target_kind
        state.target_ref = target_ref
        state.last_failure_at = now
        state.updated_at = now
        pending_attempt = self._recovery_attempt_repository.latest_pending_for_component(
            component_ref.component_id
        )
        if pending_attempt is not None and not pending_attempt_already_failed:
            pending_attempt.status = RecoveryAttemptStatus.FAILED
            pending_attempt.finished_at = now
            pending_attempt.error_message = reason
            self._recovery_attempt_repository.save(pending_attempt)
            self._event_bus.publish(
                RecoveryAttemptRecorded(
                    attempt_id=pending_attempt.id,
                    incident_id=pending_attempt.incident_id,
                    component_id=component_ref.component_id,
                    component_kind=component_ref.kind,
                    status=pending_attempt.status,
                    action=pending_attempt.action,
                    attempt_number=pending_attempt.attempt_number,
                )
            )
        policy = self._recovery_policy_service.policy_for(component_ref.kind)
        recent_attempts = self._recovery_attempt_repository.recent_for_component(
            component_ref.component_id,
            within_seconds=policy.retry_window_seconds,
            now=now,
        )
        evaluation = self._recovery_policy_service.evaluate_failure(
            component_kind=component_ref.kind,
            state=state,
            recent_attempts=recent_attempts,
            reason=reason,
            now=now,
        )
        incident = self._ensure_incident(
            component_ref=component_ref,
            severity=severity,
            reason=reason,
            state=state,
        )
        previous_status = state.status
        state.consecutive_failures += 1
        state.next_recovery_at = None
        state.cooldown_until = None

        if evaluation.should_schedule_attempt:
            state.status = HealthStatus.RECOVERING
            state.next_recovery_at = now + timedelta(seconds=evaluation.backoff_seconds)
            state.last_incident_id = incident.id
            self._component_health_repository.save(state)
            self._record_transition(state, previous_status, evaluation.explanation)
            self._set_incident_status(
                incident,
                IncidentStatus.RECOVERING,
                evaluation.explanation,
            )
            attempt = RecoveryAttempt(
                id=make_id("rcv"),
                incident_id=incident.id,
                component_id=component_ref.component_id,
                attempt_number=evaluation.attempt_number,
                status=RecoveryAttemptStatus.SCHEDULED,
                trigger="automatic",
                action=f"recover:{component_ref.kind.value}",
                backoff_ms=evaluation.backoff_seconds * 1000,
                scheduled_for=state.next_recovery_at,
                payload={"reason": reason},
            )
            self._recovery_attempt_repository.save(attempt)
            self._incident_repository.add_timeline_entry(
                incident_id=incident.id,
                event_type="recovery_scheduled",
                message=evaluation.explanation,
                payload={"attempt_id": attempt.id, "backoff_ms": attempt.backoff_ms},
            )
            self._event_bus.publish(
                RecoveryAttemptRecorded(
                    attempt_id=attempt.id,
                    incident_id=incident.id,
                    component_id=component_ref.component_id,
                    component_kind=component_ref.kind,
                    status=attempt.status,
                    action=attempt.action,
                    attempt_number=attempt.attempt_number,
                )
            )
            return

        if evaluation.should_enter_cooldown:
            state.status = HealthStatus.FAILED
            state.cooldown_until = evaluation.cooldown_until
            state.exhaustion_count += 1
            state.last_incident_id = incident.id
            self._component_health_repository.save(state)
            self._record_transition(state, previous_status, evaluation.explanation)
            self._set_incident_status(incident, IncidentStatus.OPEN, evaluation.explanation)
            self._incident_repository.add_timeline_entry(
                incident_id=incident.id,
                event_type="cooldown_entered",
                message=evaluation.explanation,
                payload={
                    "cooldown_until": evaluation.cooldown_until.isoformat()
                    if evaluation.cooldown_until
                    else None
                },
            )
            return

        if evaluation.should_quarantine:
            state.status = HealthStatus.QUARANTINED
            state.quarantined = True
            state.quarantine_reason = evaluation.explanation
            state.cooldown_until = evaluation.cooldown_until
            state.last_incident_id = incident.id
            self._component_health_repository.save(state)
            self._record_transition(state, previous_status, evaluation.explanation)
            self._set_incident_status(
                incident,
                IncidentStatus.QUARANTINED,
                evaluation.explanation,
            )
            self._incident_repository.add_timeline_entry(
                incident_id=incident.id,
                event_type="quarantined",
                message=evaluation.explanation,
                payload={"reason": reason},
            )
            self._event_bus.publish(
                ComponentQuarantined(
                    component_id=component_ref.component_id,
                    component_kind=component_ref.kind,
                    reason=evaluation.explanation,
                )
            )

    def _ensure_incident(
        self,
        *,
        component_ref: ComponentRef,
        severity: IncidentSeverity,
        reason: str,
        state: ComponentHealthState,
    ) -> IncidentRecord:
        incident = self._incident_repository.get_open_for_component(component_ref.component_id)
        now = self._now()
        if incident is None:
            incident = IncidentRecord(
                id=make_id("inc"),
                component_id=component_ref.component_id,
                component_kind=component_ref.kind,
                severity=severity,
                status=IncidentStatus.OPEN,
                title=f"{component_ref.display_name} unhealthy",
                summary=reason,
                workspace_id=state.workspace_id,
                session_id=state.session_id,
                opened_at=now,
                updated_at=now,
                payload={"display_name": component_ref.display_name},
            )
            self._incident_repository.save(incident)
            self._incident_repository.add_timeline_entry(
                incident_id=incident.id,
                event_type="opened",
                message=reason,
                payload={"severity": severity.value},
            )
            self._event_bus.publish(
                IncidentOpened(
                    incident_id=incident.id,
                    component_id=component_ref.component_id,
                    component_kind=component_ref.kind,
                    severity=severity,
                    title=incident.title,
                )
            )
            return incident

        incident.summary = reason
        incident.updated_at = now
        if self._SEVERITY_ORDER[severity] > self._SEVERITY_ORDER[incident.severity]:
            incident.severity = severity
        self._incident_repository.save(incident)
        self._incident_repository.add_timeline_entry(
            incident_id=incident.id,
            event_type="failure_observed",
            message=reason,
            payload={"severity": severity.value},
        )
        return incident

    def _set_incident_status(
        self,
        incident: IncidentRecord,
        new_status: IncidentStatus,
        message: str,
    ) -> None:
        previous_status = incident.status
        if previous_status is new_status:
            incident.updated_at = self._now()
            self._incident_repository.save(incident)
            return
        incident.status = new_status
        incident.updated_at = self._now()
        if new_status is IncidentStatus.RESOLVED:
            incident.resolved_at = incident.updated_at
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

    def _mark_component_healthy(
        self,
        *,
        state: ComponentHealthState,
        heartbeat_at: datetime,
        payload: dict[str, object],
    ) -> None:
        previous_status = state.status
        state.status = HealthStatus.HEALTHY
        state.quarantined = False
        state.quarantine_reason = None
        state.consecutive_failures = 0
        state.cooldown_until = None
        state.next_recovery_at = None
        state.last_heartbeat_at = heartbeat_at
        state.last_recovery_at = heartbeat_at
        state.updated_at = self._now()
        state.payload.update(payload)
        self._component_health_repository.save(state)
        self._record_transition(state, previous_status, "component reported healthy")
        incident = self._incident_repository.get_open_for_component(state.component_id)
        if incident is not None:
            self._set_incident_status(
                incident,
                IncidentStatus.RESOLVED,
                "component recovered and reported healthy",
            )
        pending = self._recovery_attempt_repository.latest_pending_for_component(
            state.component_id
        )
        if pending is not None and pending.status in {
            RecoveryAttemptStatus.SCHEDULED,
            RecoveryAttemptStatus.RUNNING,
        }:
            pending.status = RecoveryAttemptStatus.SUCCEEDED
            pending.finished_at = self._now()
            self._recovery_attempt_repository.save(pending)
            self._event_bus.publish(
                RecoveryAttemptRecorded(
                    attempt_id=pending.id,
                    incident_id=pending.incident_id,
                    component_id=state.component_id,
                    component_kind=state.component_kind,
                    status=pending.status,
                    action=pending.action,
                    attempt_number=pending.attempt_number,
                )
            )

    def _record_transition(
        self,
        state: ComponentHealthState,
        previous_status: HealthStatus,
        reason: str,
    ) -> None:
        if previous_status is state.status:
            return
        self._component_health_repository.record_transition(
            component_id=state.component_id,
            component_kind=state.component_kind,
            previous_status=previous_status,
            new_status=state.status,
            reason=reason,
            payload={"last_incident_id": state.last_incident_id},
        )
        self._event_bus.publish(
            ComponentHealthChanged(
                component_id=state.component_id,
                component_kind=state.component_kind,
                previous_status=previous_status,
                new_status=state.status,
                reason=reason,
            )
        )

    def _require_state(self, component_id: str) -> ComponentHealthState:
        state = self._component_health_repository.get(component_id)
        if state is None:
            raise LookupError(f"Component '{component_id}' was not found.")
        return state

    def _task_component_ref(self, snapshot: TaskSnapshot) -> ComponentRef:
        metadata = dict(snapshot.metadata)
        return ComponentRef(
            component_id=str(metadata.get("component_id", f"task:{snapshot.name}")),
            kind=self._component_kind_from_metadata(
                metadata.get("component_kind"),
                default=ComponentKind.BACKGROUND_TASK,
            ),
            display_name=str(metadata.get("display_name", snapshot.name)),
        )

    @staticmethod
    def _component_kind_from_metadata(
        raw_value: object,
        *,
        default: ComponentKind,
    ) -> ComponentKind:
        if isinstance(raw_value, ComponentKind):
            return raw_value
        if isinstance(raw_value, str):
            try:
                return ComponentKind(raw_value)
            except ValueError:
                return default
        return default

    @staticmethod
    def _task_target_kind(snapshot: TaskSnapshot) -> SessionTargetKind:
        metadata = dict(snapshot.metadata)
        raw_value = metadata.get("target_kind")
        if isinstance(raw_value, SessionTargetKind):
            return raw_value
        if isinstance(raw_value, str):
            try:
                return SessionTargetKind(raw_value)
            except ValueError:
                return SessionTargetKind.LOCAL
        return SessionTargetKind.LOCAL

    @staticmethod
    def _target_kind_from_metadata(raw_value: object) -> SessionTargetKind:
        if isinstance(raw_value, SessionTargetKind):
            return raw_value
        if isinstance(raw_value, str):
            try:
                return SessionTargetKind(raw_value)
            except ValueError:
                return SessionTargetKind.LOCAL
        return SessionTargetKind.LOCAL

    def _now(self) -> datetime:
        return self._now_factory()

    @staticmethod
    def _runtime_payload(state: ComponentHealthState) -> dict[str, object]:
        payload = dict(state.payload)
        merged = dict(payload)
        nested = payload.get("payload")
        while isinstance(nested, dict):
            merged.update(nested)
            nested = nested.get("payload")
        return merged
