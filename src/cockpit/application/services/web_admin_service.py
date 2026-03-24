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
from cockpit.application.services.guard_policy_service import GuardPolicyService
from cockpit.application.services.incident_service import IncidentService
from cockpit.application.services.layout_service import LayoutService
from cockpit.application.services.notification_policy_service import NotificationPolicyService
from cockpit.application.services.notification_service import NotificationService
from cockpit.application.services.operations_diagnostics_service import (
    OperationsDiagnosticsService,
)
from cockpit.application.services.plugin_service import PluginService
from cockpit.application.services.secret_service import SecretService
from cockpit.application.services.self_healing_service import SelfHealingService
from cockpit.application.services.suppression_service import SuppressionService
from cockpit.domain.models.datasource import DataSourceOperationResult, DataSourceProfile
from cockpit.domain.models.layout import Layout
from cockpit.domain.models.notifications import (
    NotificationChannel,
    NotificationRule,
    NotificationSuppressionRule,
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
    GuardActionKind,
    GuardDecisionOutcome,
    IncidentSeverity,
    IncidentStatus,
    NotificationChannelKind,
    NotificationEventClass,
    NotificationStatus,
    OperationFamily,
    SessionTargetKind,
    TargetRiskLevel,
    WatchSubjectKind,
)
from cockpit.shared.utils import utc_now
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
    def _enum_csv_list(raw_value: object, enum_type: type) -> tuple:
        values = []
        for item in WebAdminService._csv_list(raw_value):
            values.append(enum_type(item))
        return tuple(values)

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
