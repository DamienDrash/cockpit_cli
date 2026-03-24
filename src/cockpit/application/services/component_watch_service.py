"""Explicit watch configuration and probe execution for Stage 2 components."""

from __future__ import annotations

from datetime import datetime

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.application.services.datasource_service import DataSourceService
from cockpit.domain.events.health_events import ComponentWatchObserved
from cockpit.domain.models.watch import ComponentWatchConfig, ComponentWatchState
from cockpit.infrastructure.docker.docker_adapter import DockerAdapter
from cockpit.infrastructure.persistence.ops_repositories import (
    ComponentWatchRepository,
    OperationDiagnosticsRepository,
)
from cockpit.shared.enums import (
    ComponentKind,
    OperationFamily,
    SessionTargetKind,
    WatchProbeOutcome,
    WatchSubjectKind,
)
from cockpit.shared.utils import make_id, utc_now


class ComponentWatchService:
    """Manage opt-in datasource and Docker watch configurations."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        repository: ComponentWatchRepository,
        datasource_service: DataSourceService,
        docker_adapter: DockerAdapter,
        operation_diagnostics_repository: OperationDiagnosticsRepository,
    ) -> None:
        self._event_bus = event_bus
        self._repository = repository
        self._datasource_service = datasource_service
        self._docker_adapter = docker_adapter
        self._operation_diagnostics_repository = operation_diagnostics_repository

    def list_configs(self, *, enabled_only: bool = False) -> list[ComponentWatchConfig]:
        return self._repository.list_configs(enabled_only=enabled_only)

    def list_states(self) -> list[ComponentWatchState]:
        return self._repository.list_states()

    def get_config(self, watch_id: str) -> ComponentWatchConfig | None:
        return self._repository.get_config(watch_id)

    def get_state(self, component_id: str) -> ComponentWatchState | None:
        return self._repository.get_state(component_id)

    def save_config(self, config: ComponentWatchConfig) -> ComponentWatchConfig:
        self._repository.save_config(config)
        return self._repository.get_config(config.id) or config

    def delete_config(self, watch_id: str) -> None:
        self._repository.delete_config(watch_id)

    def probe_due_watches(self, *, now: datetime | None = None) -> list[ComponentWatchState]:
        effective_now = now or utc_now()
        updated: list[ComponentWatchState] = []
        for config in self._repository.list_configs(enabled_only=True):
            state = self._repository.get_state(config.component_id)
            if state is not None and state.last_probe_at is not None:
                age = (effective_now - state.last_probe_at).total_seconds()
                if age < max(1, config.probe_interval_seconds):
                    continue
            updated.append(self.probe_watch(config.id, now=effective_now))
        return updated

    def probe_watch(self, watch_id: str, *, now: datetime | None = None) -> ComponentWatchState:
        config = self._require_config(watch_id)
        effective_now = now or utc_now()
        if config.subject_kind is WatchSubjectKind.DATASOURCE:
            state = self._probe_datasource(config, effective_now)
        elif config.subject_kind is WatchSubjectKind.DOCKER_CONTAINER:
            state = self._probe_docker_container(config, effective_now)
        else:
            raise ValueError(f"Unsupported watch subject kind '{config.subject_kind.value}'.")
        self._repository.save_state(state)
        self._event_bus.publish(
            ComponentWatchObserved(
                component_id=config.component_id,
                component_kind=config.component_kind,
                outcome=state.last_outcome,
                status=state.last_status,
                summary=str(state.payload.get("summary", state.last_status)),
                target_ref=config.target_ref,
                metadata={
                    "watch_id": config.id,
                    "subject_kind": config.subject_kind.value,
                    "subject_ref": config.subject_ref,
                    "target_kind": config.target_kind.value,
                    "target_ref": config.target_ref,
                    "payload": state.payload,
                },
            )
        )
        return state

    def probe_watch_for_component(self, component_id: str) -> ComponentWatchState:
        for config in self._repository.list_configs(enabled_only=True):
            if config.component_id == component_id:
                return self.probe_watch(config.id)
        raise LookupError(f"No watch config exists for component '{component_id}'.")

    @staticmethod
    def new_datasource_watch(
        *,
        profile_id: str,
        name: str | None = None,
        probe_interval_seconds: int = 30,
        stale_timeout_seconds: int = 90,
    ) -> ComponentWatchConfig:
        now = utc_now()
        return ComponentWatchConfig(
            id=make_id("wch"),
            name=name or f"Datasource {profile_id}",
            component_id=f"watch:datasource:{profile_id}",
            component_kind=ComponentKind.DATASOURCE_WATCH,
            subject_kind=WatchSubjectKind.DATASOURCE,
            subject_ref=profile_id,
            enabled=True,
            probe_interval_seconds=probe_interval_seconds,
            stale_timeout_seconds=stale_timeout_seconds,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def new_docker_watch(
        *,
        container_ref: str,
        name: str | None = None,
        target_kind: SessionTargetKind = SessionTargetKind.LOCAL,
        target_ref: str | None = None,
        probe_interval_seconds: int = 30,
        stale_timeout_seconds: int = 90,
    ) -> ComponentWatchConfig:
        now = utc_now()
        return ComponentWatchConfig(
            id=make_id("wch"),
            name=name or f"Docker {container_ref}",
            component_id=f"watch:docker:{container_ref}",
            component_kind=ComponentKind.DOCKER_CONTAINER_WATCH,
            subject_kind=WatchSubjectKind.DOCKER_CONTAINER,
            subject_ref=container_ref,
            enabled=True,
            probe_interval_seconds=probe_interval_seconds,
            stale_timeout_seconds=stale_timeout_seconds,
            target_kind=target_kind,
            target_ref=target_ref,
            created_at=now,
            updated_at=now,
        )

    def _probe_datasource(
        self,
        config: ComponentWatchConfig,
        now: datetime,
    ) -> ComponentWatchState:
        try:
            result = self._datasource_service.inspect_profile(config.subject_ref)
            success = bool(result.success)
            summary = result.message or ("reachable" if success else "unreachable")
            self._operation_diagnostics_repository.record(
                operation_family=OperationFamily.DB,
                component_id=config.component_id,
                subject_ref=config.subject_ref,
                success=success,
                severity="info" if success else "high",
                summary=summary,
                payload={"watch_id": config.id, "operation": "watch_probe"},
                recorded_at=now,
            )
            return ComponentWatchState(
                component_id=config.component_id,
                watch_id=config.id,
                component_kind=config.component_kind,
                subject_kind=config.subject_kind,
                subject_ref=config.subject_ref,
                last_probe_at=now,
                last_success_at=now if success else None,
                last_failure_at=None if success else now,
                last_outcome=WatchProbeOutcome.SUCCESS if success else WatchProbeOutcome.FAILURE,
                last_status="reachable" if success else "unreachable",
                payload={
                    "summary": summary,
                    "backend": result.backend,
                    "operation": result.operation,
                    "success": success,
                },
            )
        except Exception as exc:
            self._operation_diagnostics_repository.record(
                operation_family=OperationFamily.DB,
                component_id=config.component_id,
                subject_ref=config.subject_ref,
                success=False,
                severity="high",
                summary=str(exc),
                payload={"watch_id": config.id, "operation": "watch_probe"},
                recorded_at=now,
            )
            return ComponentWatchState(
                component_id=config.component_id,
                watch_id=config.id,
                component_kind=config.component_kind,
                subject_kind=config.subject_kind,
                subject_ref=config.subject_ref,
                last_probe_at=now,
                last_failure_at=now,
                last_outcome=WatchProbeOutcome.FAILURE,
                last_status="unreachable",
                payload={"summary": str(exc)},
            )

    def _probe_docker_container(
        self,
        config: ComponentWatchConfig,
        now: datetime,
    ) -> ComponentWatchState:
        diagnostics = self._docker_adapter.collect_diagnostics(
            target_kind=config.target_kind,
            target_ref=config.target_ref,
        )
        detail = next(
            (
                item
                for item in diagnostics
                if item.container_id == config.subject_ref or item.name == config.subject_ref
            ),
            None,
        )
        if detail is None:
            summary = f"Docker container '{config.subject_ref}' was not found."
            success = False
            payload = {"summary": summary}
        else:
            healthy = (detail.health in {None, "", "healthy"}) and detail.state == "running"
            success = healthy
            summary = (
                f"Container {detail.name} is healthy."
                if healthy
                else f"Container {detail.name} is {detail.health or detail.state}."
            )
            payload = {
                "summary": summary,
                "container_id": detail.container_id,
                "name": detail.name,
                "state": detail.state,
                "status": detail.status,
                "health": detail.health,
                "restart_count": detail.restart_count,
                "exit_code": detail.exit_code,
            }
        self._operation_diagnostics_repository.record(
            operation_family=OperationFamily.DOCKER,
            component_id=config.component_id,
            subject_ref=config.subject_ref,
            success=success,
            severity="info" if success else "high",
            summary=summary,
            payload={"watch_id": config.id, **payload},
            recorded_at=now,
        )
        return ComponentWatchState(
            component_id=config.component_id,
            watch_id=config.id,
            component_kind=config.component_kind,
            subject_kind=config.subject_kind,
            subject_ref=config.subject_ref,
            last_probe_at=now,
            last_success_at=now if success else None,
            last_failure_at=None if success else now,
            last_outcome=WatchProbeOutcome.SUCCESS if success else WatchProbeOutcome.FAILURE,
            last_status="healthy" if success else "unhealthy",
            payload=payload,
        )

    def _require_config(self, watch_id: str) -> ComponentWatchConfig:
        config = self._repository.get_config(watch_id)
        if config is None:
            raise LookupError(f"Watch config '{watch_id}' was not found.")
        return config
