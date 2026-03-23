"""Shared control-plane service for the local web admin."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import platform
import shutil
import sys

from cockpit.application.services.datasource_service import DataSourceService
from cockpit.application.services.layout_service import LayoutService
from cockpit.application.services.plugin_service import PluginService
from cockpit.application.services.secret_service import SecretService
from cockpit.domain.models.datasource import DataSourceOperationResult, DataSourceProfile
from cockpit.domain.models.layout import Layout
from cockpit.domain.models.secret import ManagedSecretEntry
from cockpit.infrastructure.persistence.repositories import WebAdminStateRepository
from cockpit.infrastructure.ssh.tunnel_manager import SSHTunnelManager
from cockpit.shared.enums import SessionTargetKind
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
        panel_registry: PanelRegistry,
        state_repository: WebAdminStateRepository,
        command_catalog: tuple[str, ...],
        tunnel_manager: SSHTunnelManager,
        project_root: Path,
    ) -> None:
        self._datasource_service = datasource_service
        self._secret_service = secret_service
        self._plugin_service = plugin_service
        self._layout_service = layout_service
        self._panel_registry = panel_registry
        self._state_repository = state_repository
        self._command_catalog = command_catalog
        self._tunnel_manager = tunnel_manager
        self._project_root = project_root

    def diagnostics(self) -> dict[str, object]:
        datasource_diagnostics = self._datasource_service.diagnostics()
        secret_diagnostics = self._secret_service.diagnostics()
        plugin_diagnostics = self._plugin_service.diagnostics()
        return {
            "project_root": str(self._project_root),
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "command_count": len(self._command_catalog),
            "panel_types": sorted(self._panel_registry.specs_by_type().keys()),
            "datasources": asdict(datasource_diagnostics),
            "secrets": asdict(secret_diagnostics),
            "plugins": plugin_diagnostics,
            "tunnels": self._tunnel_manager.list_tunnels(),
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
    ) -> DataSourceOperationResult:
        result = self._datasource_service.run_statement(
            profile_id,
            statement,
            operation=operation,
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
        )

    def delete_secret(self, name: str, *, purge_value: bool = False) -> None:
        self._secret_service.delete_entry(name, purge_value=purge_value)

    def rotate_secret(self, name: str, *, secret_value: str) -> ManagedSecretEntry:
        return self._secret_service.rotate_entry(name, secret_value=secret_value)

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

    def list_layouts(self) -> list[Layout]:
        return self._layout_service.list_layouts()

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
