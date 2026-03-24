"""Structured diagnostics aggregation for Stage 1 operational surfaces."""

from __future__ import annotations

from dataclasses import asdict
from urllib.parse import urlparse

from cockpit.application.services.datasource_service import DataSourceService
from cockpit.domain.models.diagnostics import (
    CurlRequestDiagnostics,
    DatasourceDiagnostics,
    DockerContainerDiagnostics,
)
from cockpit.infrastructure.db.database_adapter import DatabaseAdapter
from cockpit.infrastructure.docker.docker_adapter import DockerAdapter
from cockpit.infrastructure.http.http_adapter import HttpAdapter
from cockpit.infrastructure.persistence.ops_repositories import (
    ComponentHealthRepository,
    GuardDecisionRepository,
    IncidentRepository,
    OperationDiagnosticsRepository,
)
from cockpit.infrastructure.ssh.tunnel_manager import SSHTunnelManager
from cockpit.shared.enums import (
    ComponentKind,
    GuardDecisionOutcome,
    OperationFamily,
    TargetRiskLevel,
)


class OperationsDiagnosticsService:
    """Aggregate deep diagnostics for Docker, DB, and Curl surfaces."""

    def __init__(
        self,
        *,
        docker_adapter: DockerAdapter,
        database_adapter: DatabaseAdapter,
        http_adapter: HttpAdapter,
        datasource_service: DataSourceService,
        tunnel_manager: SSHTunnelManager,
        component_health_repository: ComponentHealthRepository,
        incident_repository: IncidentRepository,
        guard_decision_repository: GuardDecisionRepository,
        operation_diagnostics_repository: OperationDiagnosticsRepository,
    ) -> None:
        self._docker_adapter = docker_adapter
        self._database_adapter = database_adapter
        self._http_adapter = http_adapter
        self._datasource_service = datasource_service
        self._tunnel_manager = tunnel_manager
        self._component_health_repository = component_health_repository
        self._incident_repository = incident_repository
        self._guard_decision_repository = guard_decision_repository
        self._operation_diagnostics_repository = operation_diagnostics_repository

    def record_operation(
        self,
        *,
        family: OperationFamily,
        component_id: str,
        subject_ref: str,
        success: bool,
        severity: str,
        summary: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        self._operation_diagnostics_repository.record(
            operation_family=family,
            component_id=component_id,
            subject_ref=subject_ref,
            success=success,
            severity=severity,
            summary=summary,
            payload=payload or {},
        )

    def docker_diagnostics(self) -> list[dict[str, object]]:
        details = self._docker_adapter.collect_diagnostics()
        records = []
        for detail in details:
            component_id = f"docker:{detail.container_id}"
            incident = self._incident_repository.get_open_for_component(component_id)
            diag = DockerContainerDiagnostics(
                container_id=detail.container_id,
                name=detail.name,
                image=detail.image,
                state=detail.state,
                status=detail.status,
                health=detail.health,
                restart_policy=detail.restart_policy,
                exit_code=detail.exit_code,
                restart_count=detail.restart_count,
                last_error=detail.last_error,
                last_finished_at=detail.last_finished_at,
                recent_logs=list(detail.recent_logs),
                risk_level=TargetRiskLevel.DEV,
                last_incident_id=incident.id if incident is not None else None,
                last_incident_status=incident.status.value if incident is not None else None,
            )
            self._operation_diagnostics_repository.update_cache(
                component_id=component_id,
                component_kind=ComponentKind.DOCKER_RUNTIME,
                snapshot=diag.to_dict(),
            )
            records.append(diag.to_dict())
        return records

    def datasource_diagnostics(self) -> list[dict[str, object]]:
        recent_failures = self._operation_diagnostics_repository.list_recent_failures(
            family=OperationFamily.DB,
            limit=50,
        )
        failure_counts: dict[str, int] = {}
        last_failure_message: dict[str, str] = {}
        for record in recent_failures:
            payload = record.payload
            subject = record.subject_ref
            failure_counts[subject] = failure_counts.get(subject, 0) + 1
            if subject not in last_failure_message and isinstance(payload.get("message"), str):
                last_failure_message[subject] = str(payload.get("message"))

        tunnel_state = {
            str(item.get("profile_id", "")): bool(item.get("alive", False))
            for item in self._tunnel_manager.snapshot_tunnels()
        }
        decisions = self._guard_decision_repository.list_recent(limit=100)
        last_guard: dict[str, GuardDecisionOutcome] = {}
        for row in decisions:
            payload = row.get("payload", {})
            if not isinstance(payload, dict):
                continue
            subject_ref = payload.get("subject_ref")
            if isinstance(subject_ref, str) and subject_ref and subject_ref not in last_guard:
                last_guard[subject_ref] = GuardDecisionOutcome(str(row["outcome"]))

        rows: list[dict[str, object]] = []
        for profile in self._datasource_service.list_profiles():
            subject_ref = profile.id
            reachable = "unknown"
            if subject_ref in last_failure_message:
                reachable = "failing"
            else:
                recent = self._operation_diagnostics_repository.list_recent(
                    family=OperationFamily.DB,
                    component_id=f"datasource:{profile.id}",
                    limit=1,
                )
                if recent:
                    reachable = "reachable" if recent[0].success else "failing"
            hints = []
            if "can_explain" in profile.capabilities:
                hints.append("supports EXPLAIN/preview")
            if profile.risk_level.lower() != "dev":
                hints.append("non-dev guard policy applies")
            if profile.target_kind.value == "ssh":
                hints.append("tunnel-backed target")
            diag = DatasourceDiagnostics(
                profile_id=profile.id,
                name=profile.name,
                backend=profile.backend,
                reachable=reachable,
                target=profile.target_kind.value,
                tunnel_alive=tunnel_state.get(profile.id),
                risk_level=TargetRiskLevel(profile.risk_level.lower()),
                capabilities=list(profile.capabilities),
                recent_failure_count=failure_counts.get(subject_ref, 0),
                last_message=last_failure_message.get(subject_ref),
                last_operation=(
                    self._operation_diagnostics_repository.list_recent(
                        family=OperationFamily.DB,
                        component_id=f"datasource:{profile.id}",
                        limit=1,
                    )[0].summary
                    if self._operation_diagnostics_repository.list_recent(
                        family=OperationFamily.DB,
                        component_id=f"datasource:{profile.id}",
                        limit=1,
                    )
                    else None
                ),
                last_guard_outcome=last_guard.get(subject_ref),
                safety_hints=hints,
            )
            self._operation_diagnostics_repository.update_cache(
                component_id=f"datasource:{profile.id}",
                component_kind=ComponentKind.DATASOURCE,
                snapshot=diag.to_dict(),
            )
            rows.append(diag.to_dict())
        return rows

    def curl_diagnostics(self) -> list[dict[str, object]]:
        recent = self._operation_diagnostics_repository.list_recent(
            family=OperationFamily.CURL,
            limit=50,
        )
        grouped: dict[str, list[dict[str, object]]] = {}
        for record in recent:
            grouped.setdefault(record.subject_ref, []).append(record.to_dict())
        decisions = self._guard_decision_repository.list_recent(limit=100)
        last_guard: dict[str, GuardDecisionOutcome] = {}
        for row in decisions:
            payload = row.get("payload", {})
            if not isinstance(payload, dict):
                continue
            subject_ref = payload.get("subject_ref")
            if isinstance(subject_ref, str) and subject_ref and subject_ref not in last_guard:
                last_guard[subject_ref] = GuardDecisionOutcome(str(row["outcome"]))
        rows: list[dict[str, object]] = []
        for subject_ref, entries in grouped.items():
            latest = entries[0]
            payload = latest.get("payload", {})
            if not isinstance(payload, dict):
                payload = {}
            failure_streak = 0
            for item in entries:
                if bool(item.get("success", False)):
                    break
                failure_streak += 1
            parsed = urlparse(subject_ref)
            diag = CurlRequestDiagnostics(
                subject_ref=subject_ref,
                method=str(payload.get("method", latest.get("summary", "GET"))).upper(),
                url=subject_ref,
                risk_level=TargetRiskLevel(str(payload.get("risk_level", "dev"))),
                last_status_code=(
                    int(payload["status_code"])
                    if isinstance(payload.get("status_code"), int)
                    else None
                ),
                last_duration_ms=(
                    int(payload["duration_ms"])
                    if isinstance(payload.get("duration_ms"), int)
                    else None
                ),
                success=bool(latest.get("success", False)),
                failure_streak=failure_streak,
                placeholder_names=[
                    str(item)
                    for item in payload.get("placeholder_names", [])
                    if isinstance(item, str)
                ],
                last_guard_outcome=last_guard.get(subject_ref),
                recent_messages=[
                    str(item.get("summary", ""))
                    for item in entries[:5]
                    if isinstance(item, dict)
                ],
            )
            component_id = f"http:{parsed.netloc or subject_ref}"
            self._operation_diagnostics_repository.update_cache(
                component_id=component_id,
                component_kind=ComponentKind.HTTP_REQUEST,
                snapshot=diag.to_dict(),
            )
            rows.append(diag.to_dict())
        return rows

    def overview(self) -> dict[str, object]:
        return {
            "docker": self.docker_diagnostics(),
            "db": self.datasource_diagnostics(),
            "curl": self.curl_diagnostics(),
            "notification": [
                record.to_dict()
                for record in self._operation_diagnostics_repository.list_recent(
                    family=OperationFamily.NOTIFICATION,
                    limit=25,
                )
            ],
            "recent_guard_decisions": self._guard_decision_repository.list_recent(limit=20),
            "recent_operations": [
                record.to_dict()
                for record in self._operation_diagnostics_repository.list_recent(limit=25)
            ],
        }
