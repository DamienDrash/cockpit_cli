"""Shared control-plane service for the local web admin."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import platform
import shutil
import sys

from cockpit.application.services.component_watch_service import ComponentWatchService
from cockpit.application.services.datasource_service import DataSourceService
from cockpit.application.services.escalation_policy_service import (
    EscalationPolicyService,
)
from cockpit.application.services.escalation_service import EscalationService
from cockpit.application.services.guard_policy_service import GuardPolicyService
from cockpit.application.services.incident_service import IncidentService
from cockpit.application.services.layout_service import LayoutService
from cockpit.application.services.notification_policy_service import NotificationPolicyService
from cockpit.application.services.notification_service import NotificationService
from cockpit.application.services.oncall_service import OnCallService
from cockpit.application.services.operations_diagnostics_service import (
    OperationsDiagnosticsService,
)
from cockpit.application.services.plugin_service import PluginService
from cockpit.application.services.secret_service import SecretService
from cockpit.application.services.self_healing_service import SelfHealingService
from cockpit.application.services.suppression_service import SuppressionService
from cockpit.domain.models.datasource import DataSourceOperationResult, DataSourceProfile
from cockpit.domain.models.escalation import EscalationPolicy, EscalationStep
from cockpit.domain.models.layout import Layout
from cockpit.domain.models.notifications import (
    NotificationChannel,
    NotificationRule,
    NotificationSuppressionRule,
)
from cockpit.domain.models.oncall import (
    OnCallSchedule,
    OperatorContactTarget,
    OperatorPerson,
    OperatorTeam,
    OwnershipBinding,
    RotationRule,
    ScheduleOverride,
    TeamMembership,
)
from cockpit.domain.models.policy import GuardContext
from cockpit.domain.models.secret import ManagedSecretEntry, VaultProfile, VaultSession, VaultLease
from cockpit.domain.models.watch import ComponentWatchConfig
from cockpit.infrastructure.db.database_adapter import DatabaseAdapter
from cockpit.infrastructure.persistence.repositories import WebAdminStateRepository
from cockpit.infrastructure.ssh.tunnel_manager import SSHTunnelManager
from cockpit.runtime.task_supervisor import TaskSupervisor
from cockpit.shared.enums import (
    ComponentKind,
    EscalationTargetKind,
    GuardActionKind,
    GuardDecisionOutcome,
    OwnershipSubjectKind,
    RotationIntervalKind,
    ScheduleCoverageKind,
    IncidentSeverity,
    IncidentStatus,
    TeamMembershipRole,
    NotificationChannelKind,
    NotificationEventClass,
    NotificationStatus,
    OperationFamily,
    SessionTargetKind,
    TargetRiskLevel,
    WatchSubjectKind,
)
from cockpit.shared.utils import make_id, utc_now
from cockpit.ui.panels.registry import PanelRegistry


class WebAdminService:
    """Expose shared admin-plane operations to the local HTTP surface."""

    def __init__(
        self,
        *,
        datasource_service: DataSourceService,
        secret_service: SecretService,
        plugin_service: PluginService,
        layout_service: LayoutService,
        incident_service: IncidentService,
        self_healing_service: SelfHealingService,
        operations_diagnostics_service: OperationsDiagnosticsService,
        notification_service: NotificationService,
        notification_policy_service: NotificationPolicyService,
        suppression_service: SuppressionService,
        component_watch_service: ComponentWatchService,
        guard_policy_service: GuardPolicyService,
        oncall_service: OnCallService,
        escalation_policy_service: EscalationPolicyService,
        escalation_service: EscalationService,
        panel_registry: PanelRegistry,
        state_repository: WebAdminStateRepository,
        command_catalog: tuple[str, ...],
        tunnel_manager: SSHTunnelManager,
        task_supervisor: TaskSupervisor,
        project_root: Path,
    ) -> None:
        self._datasource_service = datasource_service
        self._secret_service = secret_service
        self._plugin_service = plugin_service
        self._layout_service = layout_service
        self._incident_service = incident_service
        self._self_healing_service = self_healing_service
        self._operations_diagnostics_service = operations_diagnostics_service
        self._notification_service = notification_service
        self._notification_policy_service = notification_policy_service
        self._suppression_service = suppression_service
        self._component_watch_service = component_watch_service
        self._guard_policy_service = guard_policy_service
        self._oncall_service = oncall_service
        self._escalation_policy_service = escalation_policy_service
        self._escalation_service = escalation_service
        self._panel_registry = panel_registry
        self._state_repository = state_repository
        self._command_catalog = command_catalog
        self._tunnel_manager = tunnel_manager
        self._task_supervisor = task_supervisor
        self._project_root = project_root

    def diagnostics(self) -> dict[str, object]:
        datasource_diagnostics = self._datasource_service.diagnostics()
        secret_diagnostics = self._secret_service.diagnostics()
        plugin_diagnostics = self._plugin_service.diagnostics()
        notification_summary = self._notification_service.summary()
        watch_configs = self._component_watch_service.list_configs()
        watch_states = self._component_watch_service.list_states()
        task_snapshots = [
            self._task_snapshot_payload(snapshot)
            for snapshot in self._task_supervisor.list_snapshots()
        ]
        active_incidents = self._incident_service.list_incidents(
            limit=10,
            statuses=(
                IncidentStatus.OPEN,
                IncidentStatus.ACKNOWLEDGED,
                IncidentStatus.RECOVERING,
                IncidentStatus.QUARANTINED,
            ),
        )
        incident_rows = [incident.to_dict() for incident in active_incidents]
        recent_attempts = []
        for incident in active_incidents[:5]:
            detail = self._incident_service.get_incident_detail(incident.id)
            if detail is None:
                continue
            recent_attempts.extend(attempt.to_dict() for attempt in detail.recovery_attempts)
        operations = self._operations_diagnostics_service.overview()
        return {
            "project_root": str(self._project_root),
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "command_count": len(self._command_catalog),
            "panel_types": sorted(self._panel_registry.specs_by_type().keys()),
            "datasources": asdict(datasource_diagnostics),
            "secrets": asdict(secret_diagnostics),
            "plugins": plugin_diagnostics,
            "plugin_hosts": self._plugin_service.host_snapshots(),
            "tunnels": self._tunnel_manager.list_tunnels(),
            "health": self._self_healing_service.health_summary().to_dict(),
            "quarantined_components": [
                state.to_dict() for state in self._self_healing_service.list_quarantined()
            ],
            "active_incidents": incident_rows,
            "recent_recovery_attempts": recent_attempts[:10],
            "notifications": notification_summary,
            "notification_channels": [
                channel.to_dict()
                for channel in self._notification_policy_service.list_channels()
            ],
            "notification_rules": [
                rule.to_dict()
                for rule in self._notification_policy_service.list_rules()
            ],
            "suppression_rules": [
                rule.to_dict()
                for rule in self._suppression_service.list_rules()
            ],
            "oncall": {
                "people": [person.to_dict() for person in self._oncall_service.list_people()],
                "teams": [team.to_dict() for team in self._oncall_service.list_teams()],
                "bindings": [
                    binding.to_dict()
                    for binding in self._oncall_service.list_ownership_bindings()
                ],
                "schedules": [
                    schedule.to_dict() for schedule in self._oncall_service.list_schedules()
                ],
                "engagements": self._escalation_service.diagnostics(),
                "policies": [
                    policy.to_dict()
                    for policy in self._escalation_policy_service.list_policies()
                ],
            },
            "watches": {
                "configs": [config.to_dict() for config in watch_configs],
                "states": [state.to_dict() for state in watch_states],
                "unhealthy": [
                    state.to_dict()
                    for state in watch_states
                    if state.last_outcome.value != "success"
                ],
            },
            "tasks": task_snapshots,
            "web_admin_tasks": [
                snapshot
                for snapshot in task_snapshots
                if snapshot.get("component_kind") == ComponentKind.WEB_ADMIN.value
            ],
            "operations": operations,
            "tools": {
                "git": shutil.which("git") is not None,
                "docker": shutil.which("docker") is not None,
                "ssh": shutil.which("ssh") is not None,
            },
        }

    def list_datasources(self) -> list[DataSourceProfile]:
        return self._datasource_service.list_profiles()

    def create_datasource(self, payload: dict[str, object]) -> DataSourceProfile:
        target_kind = SessionTargetKind(payload.get("target_kind", "local"))
        options = self._json_mapping(payload.get("options_json"))
        secret_refs = self._json_mapping(payload.get("secret_refs_json"))
        tags = self._csv_list(payload.get("tags"))
        return self._datasource_service.create_profile(
            name=payload.get("name", "").strip() or payload.get("backend", "Datasource"),
            backend=payload.get("backend", "sqlite"),
            driver=payload.get("driver") or None,
            connection_url=payload.get("connection_url") or None,
            database_name=payload.get("database_name") or None,
            target_kind=target_kind,
            target_ref=payload.get("target_ref") or None,
            risk_level=payload.get("risk_level", "dev"),
            options=options,
            secret_refs=secret_refs,
            tags=tags,
        )

    def delete_datasource(self, profile_id: str) -> None:
        self._datasource_service.delete_profile(profile_id)

    def inspect_datasource(self, profile_id: str) -> DataSourceOperationResult:
        return self._datasource_service.inspect_profile(profile_id)

    def execute_datasource(
        self,
        profile_id: str,
        statement: str,
        *,
        operation: str,
        confirmed: bool = False,
        elevated_mode: bool = False,
    ) -> DataSourceOperationResult:
        profile = self._datasource_service.get_profile(profile_id)
        if profile is None:
            raise LookupError(f"Datasource profile '{profile_id}' was not found.")
        risk_level = self._target_risk(profile.risk_level)
        decision = self._guard_policy_service.evaluate(
            GuardContext(
                command_id=f"admin:{profile_id}",
                action_kind=self._guard_action_for_statement(statement),
                component_kind=ComponentKind.DATASOURCE,
                target_risk=risk_level,
                workspace_name="web-admin",
                target_ref=profile.target_ref,
                confirmed=confirmed,
                elevated_mode=elevated_mode,
                subject_ref=profile.id,
                description=f"admin datasource execution on {profile.name}",
                metadata={
                    "profile_id": profile.id,
                    "subject_ref": profile.id,
                    "query": statement,
                    "backend": profile.backend,
                },
            )
        )
        if decision.outcome is not GuardDecisionOutcome.ALLOW:
            raise ValueError(decision.explanation)
        result = self._datasource_service.run_statement(
            profile_id,
            statement,
            operation=operation,
        )
        self._operations_diagnostics_service.record_operation(
            family=OperationFamily.DB,
            component_id=f"datasource:{profile.id}",
            subject_ref=profile.id,
            success=result.success,
            severity="info" if result.success else "high",
            summary=result.message or "admin datasource statement executed",
            payload={
                "query": statement,
                "operation": operation,
                "message": result.message,
                "backend": profile.backend,
                "risk_level": risk_level.value,
                "guard_outcome": decision.outcome.value,
            },
        )
        self._state_repository.save(
            "web_admin:last_datasource_result",
            {
                "profile_id": profile_id,
                "statement": statement,
                "result": result.to_dict(),
            },
        )
        return result

    def last_datasource_result(self) -> dict[str, object] | None:
        return self._state_repository.get("web_admin:last_datasource_result")

    def list_secrets(self) -> list[ManagedSecretEntry]:
        return self._secret_service.list_entries()

    def create_secret(self, payload: dict[str, object]) -> ManagedSecretEntry:
        provider = str(payload.get("provider", "env"))
        return self._secret_service.upsert_entry(
            name=str(payload.get("name", "")),
            provider=provider,
            description=self._optional_str(payload.get("description")),
            tags=self._csv_list(payload.get("tags")),
            env_name=self._optional_str(payload.get("env_name")),
            file_path=self._optional_str(payload.get("file_path")),
            keyring_service=self._optional_str(payload.get("keyring_service")),
            keyring_username=self._optional_str(payload.get("keyring_username")),
            secret_value=self._optional_str(payload.get("secret_value")),
            vault_profile_id=self._optional_str(payload.get("vault_profile_id")),
            vault_kind=self._optional_str(payload.get("vault_kind")),
            vault_mount=self._optional_str(payload.get("vault_mount")),
            vault_path=self._optional_str(payload.get("vault_path")),
            vault_field=self._optional_str(payload.get("vault_field")),
            vault_version=(
                int(payload["vault_version"])
                if str(payload.get("vault_version", "")).strip().isdigit()
                else None
            ),
            vault_role=self._optional_str(payload.get("vault_role")),
        )

    def delete_secret(self, name: str, *, purge_value: bool = False) -> None:
        self._secret_service.delete_entry(name, purge_value=purge_value)

    def rotate_secret(self, name: str, *, secret_value: str) -> ManagedSecretEntry:
        return self._secret_service.rotate_entry(name, secret_value=secret_value)

    def list_vault_profiles(self) -> list[VaultProfile]:
        return self._secret_service.list_vault_profiles()

    def save_vault_profile(self, payload: dict[str, object]) -> VaultProfile:
        return self._secret_service.save_vault_profile(
            profile_id=self._optional_str(payload.get("profile_id")),
            name=str(payload.get("name", "")),
            address=str(payload.get("address", "")),
            auth_type=str(payload.get("auth_type", "token")),
            auth_mount=self._optional_str(payload.get("auth_mount")),
            role_name=self._optional_str(payload.get("role_name")),
            namespace=self._optional_str(payload.get("namespace")),
            description=self._optional_str(payload.get("description")),
            verify_tls=str(payload.get("verify_tls", "1")) != "0",
            ca_cert_path=self._optional_str(payload.get("ca_cert_path")),
            allow_local_cache=str(payload.get("allow_local_cache", "0")) == "1",
            cache_ttl_seconds=int(payload.get("cache_ttl_seconds", 3600) or 3600),
            risk_level=str(payload.get("risk_level", "dev")),
            tags=self._csv_list(payload.get("tags")),
        )

    def delete_vault_profile(self, profile_id: str, *, revoke: bool = False) -> None:
        self._secret_service.delete_vault_profile(profile_id, revoke=revoke)

    def login_vault_profile(self, profile_id: str, payload: dict[str, object]) -> VaultSession:
        return self._secret_service.login_vault_profile(
            profile_id,
            token=self._optional_str(payload.get("token")),
            role_id=self._optional_str(payload.get("role_id")),
            secret_id=self._optional_str(payload.get("secret_id")),
            jwt=self._optional_str(payload.get("jwt")),
        )

    def logout_vault_profile(self, profile_id: str, *, revoke: bool = False) -> None:
        self._secret_service.logout_vault_profile(profile_id, revoke=revoke)

    def vault_profile_health(self, profile_id: str) -> dict[str, object]:
        return self._secret_service.vault_profile_health(profile_id)

    def list_vault_sessions(self) -> list[VaultSession]:
        return self._secret_service.list_vault_sessions()

    def list_vault_leases(self) -> list[VaultLease]:
        return self._secret_service.list_vault_leases()

    def renew_vault_lease(self, lease_id: str, *, increment_seconds: int | None = None) -> VaultLease:
        return self._secret_service.renew_vault_lease(
            lease_id,
            increment_seconds=increment_seconds,
        )

    def revoke_vault_lease(self, lease_id: str) -> None:
        self._secret_service.revoke_vault_lease(lease_id)

    def transit_operation(self, payload: dict[str, object]) -> dict[str, object]:
        return self._secret_service.transit_operation(
            profile_id=str(payload.get("profile_id", "")),
            mount=str(payload.get("mount", "transit")),
            key_name=str(payload.get("key_name", "")),
            operation=str(payload.get("operation", "encrypt")),
            value=str(payload.get("value", "")),
            signature=self._optional_str(payload.get("signature")),
        )

    def list_plugins(self):
        return self._plugin_service.list_plugins()

    def install_plugin(self, payload: dict[str, str]):
        return self._plugin_service.install_plugin(
            requirement=payload.get("requirement", "").strip(),
            module_name=payload.get("module", "").strip(),
            display_name=payload.get("name") or None,
            version_pin=payload.get("version_pin") or None,
            source=payload.get("source") or None,
            integrity_sha256=payload.get("integrity_sha256") or None,
        )

    def update_plugin(self, plugin_id: str):
        return self._plugin_service.update_plugin(plugin_id)

    def toggle_plugin(self, plugin_id: str, enabled: bool):
        return self._plugin_service.set_enabled(plugin_id, enabled)

    def pin_plugin(self, plugin_id: str, version_pin: str | None):
        return self._plugin_service.pin_version(plugin_id, version_pin)

    def remove_plugin(self, plugin_id: str) -> None:
        self._plugin_service.remove_plugin(plugin_id)

    def list_notification_channels(self) -> list[NotificationChannel]:
        return self._notification_policy_service.list_channels()

    def save_notification_channel(self, payload: dict[str, object]) -> NotificationChannel:
        channel_id = self._optional_str(payload.get("channel_id"))
        existing = next(
            (item for item in self.list_notification_channels() if item.id == channel_id),
            None,
        )
        now = utc_now()
        channel = NotificationChannel(
            id=channel_id or NotificationPolicyService.new_channel(
                name=str(payload.get("name", "Notification Channel")),
                kind=NotificationChannelKind(str(payload.get("kind", "internal"))),
            ).id,
            name=str(payload.get("name", "Notification Channel")),
            kind=NotificationChannelKind(str(payload.get("kind", "internal"))),
            enabled=str(payload.get("enabled", "1")) != "0",
            target=self._json_mapping(payload.get("target_json")),
            secret_refs={
                str(key): str(value)
                for key, value in self._json_mapping(payload.get("secret_refs_json")).items()
            },
            timeout_seconds=int(payload.get("timeout_seconds", 5) or 5),
            max_attempts=int(payload.get("max_attempts", 3) or 3),
            base_backoff_seconds=int(payload.get("base_backoff_seconds", 2) or 2),
            max_backoff_seconds=int(payload.get("max_backoff_seconds", 30) or 30),
            risk_level=self._target_risk(str(payload.get("risk_level", "dev"))),
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
        )
        return self._notification_policy_service.save_channel(channel)

    def delete_notification_channel(self, channel_id: str) -> None:
        self._notification_policy_service.delete_channel(channel_id)

    def list_notification_rules(self) -> list[NotificationRule]:
        return self._notification_policy_service.list_rules()

    def save_notification_rule(self, payload: dict[str, object]) -> NotificationRule:
        rule_id = self._optional_str(payload.get("rule_id"))
        existing = next(
            (item for item in self.list_notification_rules() if item.id == rule_id),
            None,
        )
        now = utc_now()
        rule = NotificationRule(
            id=rule_id or NotificationPolicyService.new_rule(
                name=str(payload.get("name", "Notification Rule")),
            ).id,
            name=str(payload.get("name", "Notification Rule")),
            enabled=str(payload.get("enabled", "1")) != "0",
            event_classes=self._enum_csv_list(
                payload.get("event_classes"),
                NotificationEventClass,
            ),
            component_kinds=self._enum_csv_list(
                payload.get("component_kinds"),
                ComponentKind,
            ),
            severities=self._enum_csv_list(
                payload.get("severities"),
                IncidentSeverity,
            ),
            risk_levels=self._enum_csv_list(
                payload.get("risk_levels"),
                TargetRiskLevel,
            ),
            incident_statuses=self._enum_csv_list(
                payload.get("incident_statuses"),
                IncidentStatus,
            ),
            channel_ids=tuple(self._csv_list(payload.get("channel_ids"))),
            delivery_priority=int(payload.get("delivery_priority", 100) or 100),
            dedupe_window_seconds=int(payload.get("dedupe_window_seconds", 300) or 300),
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
        )
        return self._notification_policy_service.save_rule(rule)

    def delete_notification_rule(self, rule_id: str) -> None:
        self._notification_policy_service.delete_rule(rule_id)

    def list_suppression_rules(self) -> list[NotificationSuppressionRule]:
        return self._suppression_service.list_rules()

    def save_suppression_rule(
        self,
        payload: dict[str, object],
    ) -> NotificationSuppressionRule:
        suppression_id = self._optional_str(payload.get("suppression_id"))
        existing = next(
            (item for item in self.list_suppression_rules() if item.id == suppression_id),
            None,
        )
        now = utc_now()
        rule = NotificationSuppressionRule(
            id=suppression_id or self._suppression_service.new_rule(
                name=str(payload.get("name", "Suppression Rule")),
                reason=str(payload.get("reason", "Suppressed by operator policy.")),
            ).id,
            name=str(payload.get("name", "Suppression Rule")),
            enabled=str(payload.get("enabled", "1")) != "0",
            reason=str(payload.get("reason", "Suppressed by operator policy.")),
            starts_at=self._optional_datetime(payload.get("starts_at")),
            ends_at=self._optional_datetime(payload.get("ends_at")),
            event_classes=self._enum_csv_list(
                payload.get("event_classes"),
                NotificationEventClass,
            ),
            component_kinds=self._enum_csv_list(
                payload.get("component_kinds"),
                ComponentKind,
            ),
            severities=self._enum_csv_list(
                payload.get("severities"),
                IncidentSeverity,
            ),
            risk_levels=self._enum_csv_list(
                payload.get("risk_levels"),
                TargetRiskLevel,
            ),
            actor=self._optional_str(payload.get("actor")),
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
        )
        return self._suppression_service.save_rule(rule)

    def delete_suppression_rule(self, suppression_id: str) -> None:
        self._suppression_service.delete_rule(suppression_id)

    def list_notifications(
        self,
        *,
        status: str | None = None,
    ) -> list[dict[str, object]]:
        statuses = (
            (NotificationStatus(status),)
            if isinstance(status, str) and status
            else None
        )
        return [
            item.to_dict()
            for item in self._notification_service.list_notifications(
                statuses=statuses,
            )
        ]

    def notification_detail(self, notification_id: str) -> dict[str, object] | None:
        return self._notification_service.notification_detail(notification_id)

    def notification_summary(self) -> dict[str, object]:
        return self._notification_service.summary()

    def list_watch_configs(self) -> list[ComponentWatchConfig]:
        return self._component_watch_service.list_configs()

    def list_watch_states(self) -> list[dict[str, object]]:
        return [state.to_dict() for state in self._component_watch_service.list_states()]

    def save_datasource_watch(self, payload: dict[str, object]) -> ComponentWatchConfig:
        profile_id = str(payload.get("profile_id", "")).strip()
        if not profile_id:
            raise ValueError("Datasource watch requires a profile_id.")
        watch_id = self._optional_str(payload.get("watch_id"))
        existing = self._component_watch_service.get_config(watch_id) if watch_id else None
        config = existing or ComponentWatchService.new_datasource_watch(profile_id=profile_id)
        config.name = str(payload.get("name", config.name))
        config.component_id = f"watch:datasource:{profile_id}"
        config.component_kind = ComponentKind.DATASOURCE_WATCH
        config.subject_kind = WatchSubjectKind.DATASOURCE
        config.subject_ref = profile_id
        config.enabled = str(payload.get("enabled", "1")) != "0"
        config.probe_interval_seconds = int(payload.get("probe_interval_seconds", 30) or 30)
        config.stale_timeout_seconds = int(payload.get("stale_timeout_seconds", 90) or 90)
        config.target_kind = SessionTargetKind.LOCAL
        config.target_ref = None
        config.recovery_policy_override = self._json_mapping(
            payload.get("recovery_policy_override_json")
        )
        config.monitor_config = self._json_mapping(payload.get("monitor_config_json"))
        config.updated_at = utc_now()
        return self._component_watch_service.save_config(config)

    def save_docker_watch(self, payload: dict[str, object]) -> ComponentWatchConfig:
        container_ref = str(payload.get("container_ref", "")).strip()
        if not container_ref:
            raise ValueError("Docker watch requires a container_ref.")
        watch_id = self._optional_str(payload.get("watch_id"))
        existing = self._component_watch_service.get_config(watch_id) if watch_id else None
        config = existing or ComponentWatchService.new_docker_watch(container_ref=container_ref)
        config.name = str(payload.get("name", config.name))
        config.component_id = f"watch:docker:{container_ref}"
        config.component_kind = ComponentKind.DOCKER_CONTAINER_WATCH
        config.subject_kind = WatchSubjectKind.DOCKER_CONTAINER
        config.subject_ref = container_ref
        config.enabled = str(payload.get("enabled", "1")) != "0"
        config.probe_interval_seconds = int(payload.get("probe_interval_seconds", 30) or 30)
        config.stale_timeout_seconds = int(payload.get("stale_timeout_seconds", 90) or 90)
        config.target_kind = self._target_kind_from_value(payload.get("target_kind"))
        config.target_ref = self._optional_str(payload.get("target_ref"))
        config.recovery_policy_override = self._json_mapping(
            payload.get("recovery_policy_override_json")
        )
        config.monitor_config = self._json_mapping(payload.get("monitor_config_json"))
        config.updated_at = utc_now()
        return self._component_watch_service.save_config(config)

    def delete_watch(self, watch_id: str) -> None:
        self._component_watch_service.delete_config(watch_id)

    def probe_watch(self, watch_id: str) -> dict[str, object]:
        return self._component_watch_service.probe_watch(watch_id).to_dict()

    def list_layouts(self) -> list[Layout]:
        return self._layout_service.list_layouts()

    def layout_summaries(self) -> list[dict[str, object]]:
        return [
            {
                "id": layout.id,
                "name": layout.name,
                "tab_count": len(layout.tabs),
                "tabs": [
                    {
                        "id": tab.id,
                        "name": tab.name,
                    }
                    for tab in layout.tabs
                ],
            }
            for layout in self.list_layouts()
        ]

    def load_layout_document(self, layout_id: str) -> dict[str, object]:
        return self._layout_service.load_layout_document(layout_id)

    def validate_layout_document(self, payload: dict[str, object]) -> dict[str, object]:
        panel_types = {panel_type for panel_type, _panel_id, _display_name in self.available_panels()}
        panel_ids = {panel_id for _panel_type, panel_id, _display_name in self.available_panels()}
        return self._layout_service.validate_layout_document(
            payload,
            allowed_panel_types=panel_types,
            allowed_panel_ids=panel_ids,
        )

    def save_layout_document(self, payload: dict[str, object]) -> Layout:
        panel_types = {panel_type for panel_type, _panel_id, _display_name in self.available_panels()}
        panel_ids = {panel_id for _panel_type, panel_id, _display_name in self.available_panels()}
        return self._layout_service.save_layout_document(
            payload,
            allowed_panel_types=panel_types,
            allowed_panel_ids=panel_ids,
        )

    def clone_layout(self, source_layout_id: str, target_layout_id: str, name: str | None = None) -> Layout:
        return self._layout_service.save_variant(
            source_layout_id=source_layout_id,
            target_layout_id=target_layout_id,
            name=name,
        )

    def toggle_layout_tab(self, layout_id: str, tab_id: str) -> Layout:
        return self._layout_service.toggle_tab_orientation(layout_id=layout_id, tab_id=tab_id)

    def set_layout_ratio(self, layout_id: str, tab_id: str, ratio: float) -> Layout:
        return self._layout_service.set_tab_ratio(layout_id=layout_id, tab_id=tab_id, ratio=ratio)

    def add_panel_to_layout(self, layout_id: str, tab_id: str, panel_id: str, panel_type: str) -> Layout:
        return self._layout_service.add_panel_to_tab(
            layout_id=layout_id,
            tab_id=tab_id,
            panel_id=panel_id,
            panel_type=panel_type,
        )

    def remove_panel_from_layout(self, layout_id: str, tab_id: str, panel_id: str) -> Layout:
        return self._layout_service.remove_panel_from_tab(
            layout_id=layout_id,
            tab_id=tab_id,
            panel_id=panel_id,
        )

    def replace_panel_in_layout(
        self,
        layout_id: str,
        tab_id: str,
        existing_panel_id: str,
        replacement_panel_id: str,
        replacement_panel_type: str,
    ) -> Layout:
        return self._layout_service.replace_panel_in_tab(
            layout_id=layout_id,
            tab_id=tab_id,
            existing_panel_id=existing_panel_id,
            replacement_panel_id=replacement_panel_id,
            replacement_panel_type=replacement_panel_type,
        )

    def move_panel_in_layout(
        self,
        layout_id: str,
        tab_id: str,
        panel_id: str,
        direction: str,
    ) -> Layout:
        return self._layout_service.move_panel_in_tab(
            layout_id=layout_id,
            tab_id=tab_id,
            panel_id=panel_id,
            direction=direction,
        )

    def available_panels(self) -> list[tuple[str, str, str]]:
        specs = self._panel_registry.specs_by_type()
        return sorted(
            (spec.panel_type, spec.panel_id, spec.display_name)
            for spec in specs.values()
        )

    def save_last_page(self, page: str) -> None:
        self._state_repository.save("web_admin:last_page", {"page": page})

    def last_page(self) -> str | None:
        payload = self._state_repository.get("web_admin:last_page")
        if isinstance(payload, dict) and isinstance(payload.get("page"), str):
            return str(payload["page"])
        return None

    def close_tunnel(self, profile_id: str) -> None:
        self._tunnel_manager.close_tunnel(profile_id)

    def reconnect_tunnel(self, profile_id: str) -> None:
        self._tunnel_manager.reconnect_tunnel(profile_id)

    def list_incidents(
        self,
        *,
        status: str | None = None,
        severity: str | None = None,
        component_kind: str | None = None,
        search: str | None = None,
    ):
        statuses = (
            (IncidentStatus(status),)
            if isinstance(status, str) and status
            else None
        )
        severities = (
            (IncidentSeverity(severity),)
            if isinstance(severity, str) and severity
            else None
        )
        kind = (
            ComponentKind(component_kind)
            if isinstance(component_kind, str) and component_kind
            else None
        )
        return self._incident_service.list_incidents(
            statuses=statuses,
            severities=severities,
            component_kind=kind,
            search=search,
        )

    def incident_detail(self, incident_id: str):
        return self._incident_service.get_incident_detail(incident_id)

    def acknowledge_incident(self, incident_id: str):
        return self._incident_service.acknowledge_incident(incident_id)

    def close_incident(self, incident_id: str):
        return self._incident_service.close_incident(incident_id)

    def reset_component_quarantine(self, component_id: str) -> None:
        self._incident_service.reset_quarantine(component_id)

    def retry_component_recovery(self, component_id: str) -> bool:
        return self._incident_service.retry_component(component_id)

    def list_operator_people(self) -> list[OperatorPerson]:
        return self._oncall_service.list_people()

    def save_operator_person(self, payload: dict[str, object]) -> OperatorPerson:
        person_id = self._optional_str(payload.get("person_id"))
        existing = self._oncall_service.get_person(person_id) if person_id else None
        person = OperatorPerson(
            id=person_id or self._oncall_service.new_person(
                display_name=str(payload.get("display_name", "Operator")),
                handle=str(payload.get("handle", "operator")),
            ).id,
            display_name=str(payload.get("display_name", "")),
            handle=str(payload.get("handle", "")),
            enabled=str(payload.get("enabled", "1")) != "0",
            timezone=str(payload.get("timezone", "UTC")),
            contact_targets=self._contact_targets(payload.get("contact_targets_json")),
            metadata=self._json_mapping(payload.get("metadata_json")),
            created_at=existing.created_at if existing is not None else utc_now(),
            updated_at=utc_now(),
        )
        return self._oncall_service.save_person(person)

    def delete_operator_person(self, person_id: str) -> None:
        self._oncall_service.delete_person(person_id)

    def list_operator_teams(self) -> list[OperatorTeam]:
        return self._oncall_service.list_teams()

    def save_operator_team(self, payload: dict[str, object]) -> OperatorTeam:
        team_id = self._optional_str(payload.get("team_id"))
        existing = self._oncall_service.get_team(team_id) if team_id else None
        team = OperatorTeam(
            id=team_id or self._oncall_service.new_team(
                name=str(payload.get("name", "Team")),
                description=self._optional_str(payload.get("description")),
            ).id,
            name=str(payload.get("name", "")),
            enabled=str(payload.get("enabled", "1")) != "0",
            description=self._optional_str(payload.get("description")),
            default_escalation_policy_id=self._optional_str(
                payload.get("default_escalation_policy_id")
            ),
            created_at=existing.created_at if existing is not None else utc_now(),
            updated_at=utc_now(),
        )
        return self._oncall_service.save_team(team)

    def delete_operator_team(self, team_id: str) -> None:
        self._oncall_service.delete_team(team_id)

    def list_team_memberships(self) -> list[TeamMembership]:
        return self._oncall_service.list_memberships()

    def save_team_membership(self, payload: dict[str, object]) -> TeamMembership:
        membership_id = self._optional_str(payload.get("membership_id"))
        now = utc_now()
        membership = TeamMembership(
            id=membership_id or f"mem:{payload.get('team_id', '')}:{payload.get('person_id', '')}",
            team_id=str(payload.get("team_id", "")),
            person_id=str(payload.get("person_id", "")),
            role=TeamMembershipRole(str(payload.get("role", TeamMembershipRole.MEMBER.value))),
            enabled=str(payload.get("enabled", "1")) != "0",
            created_at=now,
            updated_at=now,
        )
        return self._oncall_service.save_membership(membership)

    def delete_team_membership(self, membership_id: str) -> None:
        self._oncall_service.delete_membership(membership_id)

    def list_ownership_bindings(self) -> list[OwnershipBinding]:
        return self._oncall_service.list_ownership_bindings()

    def save_ownership_binding(self, payload: dict[str, object]) -> OwnershipBinding:
        binding_id = self._optional_str(payload.get("binding_id"))
        existing = next(
            (item for item in self._oncall_service.list_ownership_bindings() if item.id == binding_id),
            None,
        )
        now = utc_now()
        binding = OwnershipBinding(
            id=binding_id or make_id("own"),
            name=str(payload.get("name", "Ownership Binding")),
            team_id=str(payload.get("team_id", "")),
            enabled=str(payload.get("enabled", "1")) != "0",
            component_kind=self._optional_enum(payload.get("component_kind"), ComponentKind),
            component_id=self._optional_str(payload.get("component_id")),
            subject_kind=self._optional_enum(payload.get("subject_kind"), OwnershipSubjectKind),
            subject_ref=self._optional_str(payload.get("subject_ref")),
            risk_level=self._optional_enum(payload.get("risk_level"), TargetRiskLevel),
            escalation_policy_id=self._optional_str(payload.get("escalation_policy_id")),
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
        )
        return self._oncall_service.save_ownership_binding(binding)

    def delete_ownership_binding(self, binding_id: str) -> None:
        self._oncall_service.delete_ownership_binding(binding_id)

    def list_oncall_schedules(self) -> list[OnCallSchedule]:
        return self._oncall_service.list_schedules()

    def save_oncall_schedule(self, payload: dict[str, object]) -> OnCallSchedule:
        schedule_id = self._optional_str(payload.get("schedule_id"))
        existing = next(
            (item for item in self._oncall_service.list_schedules() if item.id == schedule_id),
            None,
        )
        now = utc_now()
        schedule = OnCallSchedule(
            id=schedule_id or f"sch:{payload.get('team_id', '')}:{payload.get('name', '')}",
            team_id=str(payload.get("team_id", "")),
            name=str(payload.get("name", "")),
            timezone=str(payload.get("timezone", "UTC")),
            enabled=str(payload.get("enabled", "1")) != "0",
            coverage_kind=ScheduleCoverageKind(str(payload.get("coverage_kind", "always"))),
            schedule_config=self._json_mapping(payload.get("schedule_config_json")),
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
        )
        return self._oncall_service.save_schedule(schedule)

    def delete_oncall_schedule(self, schedule_id: str) -> None:
        self._oncall_service.delete_schedule(schedule_id)

    def list_rotations(self, schedule_id: str) -> list[RotationRule]:
        return self._oncall_service.list_rotations(schedule_id)

    def save_rotation(self, payload: dict[str, object]) -> RotationRule:
        rotation_id = self._optional_str(payload.get("rotation_id"))
        schedule_id = str(payload.get("schedule_id", ""))
        existing = next(
            (item for item in self._oncall_service.list_rotations(schedule_id) if item.id == rotation_id),
            None,
        )
        now = utc_now()
        rotation = RotationRule(
            id=rotation_id or f"rot:{schedule_id}:{payload.get('name', '')}",
            schedule_id=schedule_id,
            name=str(payload.get("name", "")),
            participant_ids=tuple(self._csv_list(payload.get("participant_ids"))),
            enabled=str(payload.get("enabled", "1")) != "0",
            anchor_at=self._optional_datetime(payload.get("anchor_at")),
            interval_kind=RotationIntervalKind(str(payload.get("interval_kind", "days"))),
            interval_count=int(payload.get("interval_count", 1) or 1),
            handoff_time=self._optional_str(payload.get("handoff_time")),
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
        )
        return self._oncall_service.save_rotation(rotation)

    def delete_rotation(self, rotation_id: str) -> None:
        self._oncall_service.delete_rotation(rotation_id)

    def list_overrides(self, schedule_id: str) -> list[ScheduleOverride]:
        return self._oncall_service.list_overrides(schedule_id)

    def save_override(self, payload: dict[str, object]) -> ScheduleOverride:
        override_id = self._optional_str(payload.get("override_id"))
        schedule_id = str(payload.get("schedule_id", ""))
        existing = next(
            (item for item in self._oncall_service.list_overrides(schedule_id) if item.id == override_id),
            None,
        )
        now = utc_now()
        override = ScheduleOverride(
            id=override_id or f"ovr:{schedule_id}:{payload.get('replacement_person_id', '')}:{now.timestamp()}",
            schedule_id=schedule_id,
            replacement_person_id=str(payload.get("replacement_person_id", "")),
            replaced_person_id=self._optional_str(payload.get("replaced_person_id")),
            starts_at=self._required_datetime(payload.get("starts_at")),
            ends_at=self._required_datetime(payload.get("ends_at")),
            reason=str(payload.get("reason", "")),
            priority=int(payload.get("priority", 100) or 100),
            enabled=str(payload.get("enabled", "1")) != "0",
            actor=self._optional_str(payload.get("actor")),
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
        )
        return self._oncall_service.save_override(override)

    def delete_override(self, override_id: str) -> None:
        self._oncall_service.delete_override(override_id)

    def list_escalation_policies(self) -> list[EscalationPolicy]:
        return self._escalation_policy_service.list_policies()

    def escalation_policy_detail(self, policy_id: str):
        return self._escalation_policy_service.get_policy_detail(policy_id)

    def save_escalation_policy(self, payload: dict[str, object]):
        policy_id = self._optional_str(payload.get("policy_id"))
        existing_detail = (
            self._escalation_policy_service.get_policy_detail(policy_id)
            if policy_id
            else None
        )
        now = utc_now()
        policy = EscalationPolicy(
            id=policy_id or self._escalation_policy_service.new_policy(
                name=str(payload.get("name", "Escalation Policy"))
            ).id,
            name=str(payload.get("name", "")),
            enabled=str(payload.get("enabled", "1")) != "0",
            default_ack_timeout_seconds=int(
                payload.get("default_ack_timeout_seconds", 900) or 900
            ),
            default_repeat_page_seconds=int(
                payload.get("default_repeat_page_seconds", 300) or 300
            ),
            max_repeat_pages=int(payload.get("max_repeat_pages", 2) or 0),
            terminal_behavior=str(payload.get("terminal_behavior", "exhaust")),
            created_at=(
                existing_detail.policy.created_at if existing_detail is not None else now
            ),
            updated_at=now,
        )
        steps_payload = self._json_list(payload.get("steps_json"))
        steps = []
        for index, item in enumerate(steps_payload):
            if not isinstance(item, dict):
                raise ValueError("Escalation steps JSON must contain objects.")
            step_id = self._optional_str(item.get("id"))
            steps.append(
                EscalationStep(
                    id=step_id or self._escalation_policy_service.new_step(
                        step_index=index,
                        target_kind=EscalationTargetKind(str(item.get("target_kind", "team"))),
                        target_ref=str(item.get("target_ref", "")),
                    ).id,
                    policy_id=policy.id,
                    step_index=int(item.get("step_index", index) or index),
                    target_kind=EscalationTargetKind(str(item.get("target_kind", "team"))),
                    target_ref=str(item.get("target_ref", "")),
                    ack_timeout_seconds=(
                        int(item["ack_timeout_seconds"])
                        if str(item.get("ack_timeout_seconds", "")).strip()
                        else None
                    ),
                    repeat_page_seconds=(
                        int(item["repeat_page_seconds"])
                        if str(item.get("repeat_page_seconds", "")).strip()
                        else None
                    ),
                    max_repeat_pages=(
                        int(item["max_repeat_pages"])
                        if str(item.get("max_repeat_pages", "")).strip()
                        else None
                    ),
                    reminder_enabled=str(item.get("reminder_enabled", "1")) != "0",
                    stop_on_ack=str(item.get("stop_on_ack", "1")) != "0",
                    created_at=now,
                    updated_at=now,
                )
            )
        return self._escalation_policy_service.save_policy(policy, steps=tuple(steps))

    def delete_escalation_policy(self, policy_id: str) -> None:
        self._escalation_policy_service.delete_policy(policy_id)

    def list_engagements(self, *, active_only: bool = False) -> list[dict[str, object]]:
        items = (
            self._escalation_service.list_active_engagements()
            if active_only
            else self._escalation_service.list_recent_engagements()
        )
        return [item.to_dict() for item in items]

    def engagement_detail(self, engagement_id: str):
        return self._escalation_service.get_engagement_detail(engagement_id)

    def acknowledge_engagement(self, engagement_id: str, *, actor: str = "web-admin"):
        return self._escalation_service.acknowledge_engagement(engagement_id, actor=actor)

    def handoff_engagement(
        self,
        engagement_id: str,
        *,
        actor: str = "web-admin",
        target_kind: str = "person",
        target_ref: str,
    ):
        return self._escalation_service.handoff_engagement(
            engagement_id,
            actor=actor,
            target_kind=EscalationTargetKind(target_kind),
            target_ref=target_ref,
        )

    def repage_engagement(self, engagement_id: str, *, actor: str = "web-admin"):
        return self._escalation_service.repage_engagement(engagement_id, actor=actor)

    @staticmethod
    def _guard_action_for_statement(statement: str) -> GuardActionKind:
        if DatabaseAdapter.is_destructive_query(statement):
            return GuardActionKind.DB_DESTRUCTIVE
        if DatabaseAdapter.is_mutating_query(statement):
            return GuardActionKind.DB_MUTATION
        return GuardActionKind.DB_QUERY

    @staticmethod
    def _target_risk(raw_level: str) -> TargetRiskLevel:
        try:
            return TargetRiskLevel(raw_level.lower())
        except ValueError:
            return TargetRiskLevel.DEV

    @staticmethod
    def _json_mapping(raw_value: object) -> dict[str, object]:
        if raw_value is None:
            return {}
        text = str(raw_value).strip()
        if not text:
            return {}
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object payload.")
        return {str(key): value for key, value in payload.items()}

    @staticmethod
    def _csv_list(raw_value: object) -> list[str]:
        if raw_value is None:
            return []
        return [
            item.strip()
            for item in str(raw_value).split(",")
            if item.strip()
        ]

    @staticmethod
    def _optional_str(raw_value: object) -> str | None:
        if raw_value is None:
            return None
        text = str(raw_value).strip()
        return text or None

    @staticmethod
    def _optional_datetime(raw_value: object) -> datetime | None:
        text = WebAdminService._optional_str(raw_value)
        if text is None:
            return None
        return datetime.fromisoformat(text)

    @staticmethod
    def _required_datetime(raw_value: object) -> datetime:
        text = WebAdminService._optional_str(raw_value)
        if text is None:
            raise ValueError("Expected ISO datetime value.")
        return datetime.fromisoformat(text)

    @staticmethod
    def _enum_csv_list(raw_value: object, enum_type: type) -> tuple:
        values = []
        for item in WebAdminService._csv_list(raw_value):
            values.append(enum_type(item))
        return tuple(values)

    @staticmethod
    def _optional_enum(raw_value: object, enum_type: type):
        text = WebAdminService._optional_str(raw_value)
        if text is None:
            return None
        return enum_type(text)

    @staticmethod
    def _json_list(raw_value: object) -> list[object]:
        if raw_value is None:
            return []
        text = str(raw_value).strip()
        if not text:
            return []
        payload = json.loads(text)
        if not isinstance(payload, list):
            raise ValueError("Expected a JSON array payload.")
        return payload

    @staticmethod
    def _contact_targets(raw_value: object) -> tuple[OperatorContactTarget, ...]:
        payload = WebAdminService._json_list(raw_value)
        targets = []
        for item in payload:
            if not isinstance(item, dict):
                raise ValueError("Contact targets must be JSON objects.")
            targets.append(
                OperatorContactTarget(
                    channel_id=str(item.get("channel_id", "")),
                    label=str(item.get("label", "")),
                    enabled=str(item.get("enabled", "1")) != "0",
                    priority=int(item.get("priority", 100) or 100),
                )
            )
        return tuple(targets)

    @staticmethod
    def _target_kind_from_value(raw_value: object) -> SessionTargetKind:
        if isinstance(raw_value, SessionTargetKind):
            return raw_value
        if isinstance(raw_value, str):
            try:
                return SessionTargetKind(raw_value)
            except ValueError:
                return SessionTargetKind.LOCAL
        return SessionTargetKind.LOCAL

    @staticmethod
    def _task_snapshot_payload(snapshot: object) -> dict[str, object]:
        return {
            "name": getattr(snapshot, "name", ""),
            "alive": bool(getattr(snapshot, "alive", False)),
            "restartable": bool(getattr(snapshot, "restartable", False)),
            "stale": bool(getattr(snapshot, "stale", False)),
            "age_seconds": getattr(snapshot, "age_seconds", 0.0),
            "last_progress_message": getattr(snapshot, "last_progress_message", None),
            "last_error": getattr(snapshot, "last_error", None),
            "restart_count": getattr(snapshot, "restart_count", 0),
            "component_id": (
                dict(getattr(snapshot, "metadata", {})).get("component_id")
                if isinstance(getattr(snapshot, "metadata", {}), dict)
                else None
            ),
            "component_kind": (
                dict(getattr(snapshot, "metadata", {})).get("component_kind")
                if isinstance(getattr(snapshot, "metadata", {}), dict)
                else None
            ),
            "display_name": (
                dict(getattr(snapshot, "metadata", {})).get("display_name")
                if isinstance(getattr(snapshot, "metadata", {}), dict)
                else None
            ),
        }
