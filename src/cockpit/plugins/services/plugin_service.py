"""Managed plugin installation, verification, and isolated host activation."""

from __future__ import annotations

from importlib import metadata as importlib_metadata
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

from cockpit.core.dispatch.handler_base import DispatchResult
from cockpit.core.command import Command
from cockpit.plugins.models import InstalledPlugin, PluginManifest
from cockpit.workspace.repositories import InstalledPluginRepository
from cockpit.plugins.runtime.contracts import PluginHostStartup
from cockpit.plugins.runtime.host_client import PluginHostClient
from cockpit.plugins.runtime.remote_handler import RemotePluginCommandHandler
from cockpit.core.config import discover_project_root, state_dir
from cockpit.core.utils import make_id
from cockpit.ui.panels.registry import PanelRegistry, PanelSpec

try:  # pragma: no cover - optional dependency guard
    from packaging.specifiers import SpecifierSet
    from packaging.version import Version
except Exception:  # pragma: no cover - optional dependency guard
    SpecifierSet = None
    Version = None


DEFAULT_TRUSTED_SOURCE_PREFIXES = (
    "git+https://github.com/",
    "https://github.com/",
    "git@github.com:",
    "git+ssh://git@github.com/",
)

DEFAULT_ALLOWED_PLUGIN_PERMISSIONS = (
    "ui.read",
    "commands.execute",
    "datasource.read",
    "layout.read",
    "web.read",
)


class PluginService:
    """Install, pin, remove, and activate Cockpit plugins."""

    def __init__(
        self,
        repository: InstalledPluginRepository,
        *,
        start: Path | None = None,
        pip_runner: object | None = None,
        trusted_sources: tuple[str, ...] = (),
        allowed_permissions: tuple[str, ...] = (),
        app_version: str | None = None,
    ) -> None:
        self._repository = repository
        self._start = start
        self._project_root = discover_project_root(start)
        self._pip_runner = pip_runner or subprocess.run
        self._trusted_sources = tuple(
            item.strip()
            for item in trusted_sources
            if isinstance(item, str) and item.strip()
        )
        self._allowed_permissions = tuple(
            item.strip()
            for item in allowed_permissions
            if isinstance(item, str) and item.strip()
        )
        self._app_version = app_version or self._resolve_app_version()
        self._host_clients: dict[str, PluginHostClient] = {}
        self._host_exports: dict[str, PluginHostStartup] = {}
        self._registered_plugin_ids: set[str] = set()

    def list_plugins(self) -> list[InstalledPlugin]:
        return self._runtime_plugins()

    def get_plugin(self, plugin_id: str) -> InstalledPlugin | None:
        plugin = self._repository.get(plugin_id)
        if plugin is None:
            return None
        updated = self._runtime_state_for(plugin)
        if updated != plugin:
            self._repository.save(updated)
        return updated

    def enable_runtime_paths(self) -> list[str]:
        return []

    def enabled_modules(self) -> list[str]:
        return []

    def install_plugin(
        self,
        *,
        requirement: str,
        module_name: str,
        display_name: str | None = None,
        version_pin: str | None = None,
        source: str | None = None,
        integrity_sha256: str | None = None,
    ) -> InstalledPlugin:
        if not requirement.strip():
            raise ValueError("Plugin requirement must not be empty.")
        if not module_name.strip():
            raise ValueError("Plugin module name must not be empty.")
        self._validate_requirement(requirement, source)
        plugin_id = make_id("plg")
        install_path = self._plugin_install_root(plugin_id)
        install_path.mkdir(parents=True, exist_ok=True)
        self._run_pip_install(
            self._install_spec(requirement, version_pin), install_path
        )
        startup = self._inspect_plugin(plugin_id, module_name, install_path)
        manifest = self._manifest_from_startup(startup)
        self._validate_manifest(manifest)
        runtime_manifest = self._with_runtime_manifest_data(
            manifest,
            install_path,
            startup=startup,
            expected_integrity_sha256=integrity_sha256,
        )
        plugin = InstalledPlugin(
            id=plugin_id,
            name=display_name or manifest.name,
            module=module_name,
            requirement=requirement,
            version_pin=version_pin,
            install_path=str(install_path),
            enabled=True,
            source=source,
            manifest=runtime_manifest,
            status="installed",
        )
        self._repository.save(plugin)
        return self.get_plugin(plugin_id) or plugin

    def update_plugin(self, plugin_id: str) -> InstalledPlugin:
        plugin = self._require_plugin(plugin_id)
        self._validate_requirement(plugin.requirement, plugin.source)
        self._stop_host(plugin.id)
        install_path = Path(plugin.install_path or self._plugin_install_root(plugin_id))
        install_path.mkdir(parents=True, exist_ok=True)
        self._run_pip_install(
            self._install_spec(plugin.requirement, plugin.version_pin),
            install_path,
        )
        startup = self._inspect_plugin(plugin.id, plugin.module, install_path)
        manifest = self._manifest_from_startup(startup)
        self._validate_manifest(manifest)
        runtime_manifest = self._with_runtime_manifest_data(
            manifest,
            install_path,
            startup=startup,
            expected_integrity_sha256=self._expected_integrity(plugin),
        )
        updated = InstalledPlugin(
            id=plugin.id,
            name=plugin.name,
            module=plugin.module,
            requirement=plugin.requirement,
            version_pin=plugin.version_pin,
            install_path=str(install_path),
            enabled=plugin.enabled,
            source=plugin.source,
            manifest=runtime_manifest,
            status="installed",
        )
        self._repository.save(updated)
        return self.get_plugin(plugin_id) or updated

    def set_enabled(self, plugin_id: str, enabled: bool) -> InstalledPlugin:
        plugin = self._require_plugin(plugin_id)
        if not enabled:
            self._stop_host(plugin.id)
        updated = InstalledPlugin(
            id=plugin.id,
            name=plugin.name,
            module=plugin.module,
            requirement=plugin.requirement,
            version_pin=plugin.version_pin,
            install_path=plugin.install_path,
            enabled=enabled,
            source=plugin.source,
            manifest=dict(plugin.manifest),
            status=plugin.status,
        )
        self._repository.save(updated)
        return self.get_plugin(plugin_id) or updated

    def pin_version(self, plugin_id: str, version_pin: str | None) -> InstalledPlugin:
        plugin = self._require_plugin(plugin_id)
        updated = InstalledPlugin(
            id=plugin.id,
            name=plugin.name,
            module=plugin.module,
            requirement=plugin.requirement,
            version_pin=version_pin,
            install_path=plugin.install_path,
            enabled=plugin.enabled,
            source=plugin.source,
            manifest=dict(plugin.manifest),
            status=plugin.status,
        )
        self._repository.save(updated)
        return updated

    def remove_plugin(self, plugin_id: str) -> None:
        plugin = self._require_plugin(plugin_id)
        self._stop_host(plugin.id)
        if plugin.install_path:
            shutil.rmtree(plugin.install_path, ignore_errors=True)
        self._repository.delete(plugin_id)
        self._host_exports.pop(plugin_id, None)

    def shutdown(self) -> None:
        for plugin_id in list(self._host_clients):
            self._stop_host(plugin_id)

    def diagnostics(self) -> dict[str, object]:
        plugins = self._runtime_plugins()
        return {
            "count": len(plugins),
            "enabled": sum(1 for plugin in plugins if plugin.enabled),
            "modules": [plugin.module for plugin in plugins],
            "trusted_sources": list(self._effective_trusted_sources()),
            "allowed_permissions": list(self._effective_allowed_permissions()),
            "app_version": self._app_version,
            "integrity_failed": sum(
                1 for plugin in plugins if plugin.status == "integrity_failed"
            ),
            "incompatible": sum(
                1 for plugin in plugins if plugin.status == "incompatible"
            ),
            "permission_denied": sum(
                1 for plugin in plugins if plugin.status == "permission_denied"
            ),
            "runtime_unsupported": sum(
                1 for plugin in plugins if plugin.status == "runtime_unsupported"
            ),
            "host_running": sum(
                1 for plugin in plugins if plugin.status == "host_running"
            ),
            "host_failed": sum(
                1 for plugin in plugins if plugin.status == "host_failed"
            ),
            "registered": len(self._registered_plugin_ids),
            "hosts": {
                plugin_id: client.diagnostics()
                for plugin_id, client in self._host_clients.items()
            },
        }

    def host_snapshots(self) -> list[dict[str, object]]:
        snapshots: list[dict[str, object]] = []
        for plugin in self._runtime_plugins():
            if not plugin.enabled:
                continue
            if str(plugin.manifest.get("runtime_mode", "hosted")) != "hosted":
                continue
            client = self._host_clients.get(plugin.id)
            alive = client.is_running() if client is not None else False
            snapshots.append(
                {
                    "component_id": f"plugin-host:{plugin.id}",
                    "plugin_id": plugin.id,
                    "display_name": f"Plugin host {plugin.name}",
                    "alive": alive,
                    "status": plugin.status,
                    "last_error": client.last_error if client is not None else None,
                }
            )
        return snapshots

    def restart_host(self, plugin_id: str) -> None:
        plugin = self._require_hosted_plugin(plugin_id, required_permission="ui.read")
        self._stop_host(plugin.id)
        self._ensure_host(plugin)

    def register_managed_plugins(
        self,
        *,
        panel_registry: PanelRegistry,
        command_dispatcher: object,
        command_catalog: list[str],
    ) -> None:
        for plugin in self._runtime_plugins():
            if not plugin.enabled or plugin.id in self._registered_plugin_ids:
                continue
            runtime_mode = str(plugin.manifest.get("runtime_mode", "hosted"))
            if runtime_mode != "hosted":
                continue
            try:
                startup = self._ensure_host(plugin)
                self._register_hosted_exports(
                    plugin=plugin,
                    startup=startup,
                    panel_registry=panel_registry,
                    command_dispatcher=command_dispatcher,
                    command_catalog=command_catalog,
                )
            except Exception:
                failed = self._with_status(plugin, "host_failed")
                self._repository.save(failed)

    def invoke_command(
        self,
        *,
        plugin_id: str,
        command_name: str,
        command: object,
    ) -> DispatchResult:
        plugin = self._require_hosted_plugin(
            plugin_id, required_permission="commands.execute"
        )
        startup = self._ensure_host(plugin)
        if command_name not in {item.name for item in startup.commands}:
            raise LookupError(f"Plugin command '{command_name}' is not exported.")
        if not isinstance(command, Command):
            raise TypeError("Plugin command proxy expects a Command payload.")
        response = self._host_clients[plugin.id].call(
            "command.invoke",
            {
                "command_name": command_name,
                "command": command.to_dict(),
            },
        )
        payload = response.get("dispatch_result", {})
        if not isinstance(payload, dict):
            return DispatchResult(
                success=False, message="Plugin host returned an invalid command result."
            )
        return DispatchResult(
            success=bool(payload.get("success", False)),
            message=str(payload.get("message"))
            if payload.get("message") is not None
            else None,
            data=dict(payload.get("data", {}))
            if isinstance(payload.get("data"), dict)
            else {},
        )

    def invoke_panel_action(
        self,
        *,
        plugin_id: str,
        panel_id: str,
        action: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        plugin = self._require_hosted_plugin(plugin_id, required_permission="ui.read")
        startup = self._ensure_host(plugin)
        if panel_id not in {item.panel_id for item in startup.panels}:
            raise LookupError(f"Plugin panel '{panel_id}' is not exported.")
        return self._host_clients[plugin.id].call(
            f"panel.{action}",
            {
                "panel_id": panel_id,
                "payload": payload,
            },
        )

    def _register_hosted_exports(
        self,
        *,
        plugin: InstalledPlugin,
        startup: PluginHostStartup,
        panel_registry: PanelRegistry,
        command_dispatcher: object,
        command_catalog: list[str],
    ) -> None:
        from cockpit.plugins.runtime.remote_panel import RemotePluginPanel

        for panel_export in startup.panels:
            panel_registry.register(
                PanelSpec(
                    panel_type=panel_export.panel_type,
                    panel_id=panel_export.panel_id,
                    display_name=panel_export.display_name,
                    factory=lambda _container, panel_export=panel_export, plugin_id=plugin.id: (
                        RemotePluginPanel(
                            plugin_service=self,
                            plugin_id=plugin_id,
                            panel_id=panel_export.panel_id,
                            panel_type=panel_export.panel_type,
                            display_name=panel_export.display_name,
                        )
                    ),
                )
            )
        for command_export in startup.commands:
            command_dispatcher.register(
                command_export.name,
                RemotePluginCommandHandler(
                    plugin_service=self,
                    plugin_id=plugin.id,
                    command_name=command_export.name,
                ),
            )
            if command_export.name not in command_catalog:
                command_catalog.append(command_export.name)
        self._registered_plugin_ids.add(plugin.id)

    def _plugin_install_root(self, plugin_id: str) -> Path:
        return state_dir(self._start) / "plugins" / plugin_id

    def _run_pip_install(self, requirement: str, install_path: Path) -> None:
        result = self._pip_runner(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--upgrade",
                "--target",
                str(install_path),
                requirement,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if getattr(result, "returncode", 1) != 0:
            stderr = getattr(result, "stderr", "") or getattr(result, "stdout", "")
            raise RuntimeError(
                stderr.strip() or f"pip install failed for {requirement}."
            )

    @staticmethod
    def _install_spec(requirement: str, version_pin: str | None) -> str:
        normalized = requirement.strip()
        if not normalized:
            return normalized
        if Path(os.path.expanduser(normalized)).exists():
            return normalized
        if normalized.startswith("git+") and version_pin:
            base, fragment = normalized, ""
            if "#" in normalized:
                base, suffix = normalized.split("#", 1)
                fragment = f"#{suffix}"
            if "@" not in base[4:]:
                return f"{base}@{version_pin}{fragment}"
        if version_pin:
            if any(token in normalized for token in ("://", "/", "@")):
                return normalized
            return f"{normalized}=={version_pin}"
        return normalized

    def _inspect_plugin(
        self,
        plugin_id: str,
        module_name: str,
        install_path: Path,
    ) -> PluginHostStartup:
        client = self._build_host_client(
            plugin_id=plugin_id,
            module_name=module_name,
            install_path=install_path,
        )
        try:
            startup = client.start()
            return startup
        finally:
            client.stop()

    def _build_host_client(
        self,
        *,
        plugin_id: str,
        module_name: str,
        install_path: Path,
    ) -> PluginHostClient:
        return PluginHostClient(
            plugin_id=plugin_id,
            module_name=module_name,
            install_path=install_path,
            project_root=self._project_root,
            allowed_permissions=self._effective_allowed_permissions(),
            app_version=self._app_version,
        )

    def _ensure_host(self, plugin: InstalledPlugin) -> PluginHostStartup:
        client = self._host_clients.get(plugin.id)
        if client is None:
            if not plugin.install_path:
                raise LookupError(
                    f"Plugin '{plugin.id}' does not have an install path."
                )
            client = self._build_host_client(
                plugin_id=plugin.id,
                module_name=plugin.module,
                install_path=Path(plugin.install_path),
            )
            self._host_clients[plugin.id] = client
        startup = client.start()
        self._host_exports[plugin.id] = startup
        runtime_state = self._with_status(plugin, "host_running")
        self._repository.save(runtime_state)
        return startup

    def _stop_host(self, plugin_id: str) -> None:
        client = self._host_clients.pop(plugin_id, None)
        if client is not None:
            client.stop()

    def _manifest_from_startup(self, startup: PluginHostStartup) -> PluginManifest:
        payload = dict(startup.manifest)
        panels = [panel.panel_type for panel in startup.panels]
        commands = [command.name for command in startup.commands]
        return PluginManifest(
            name=str(payload.get("name", startup.module)),
            module=str(payload.get("module", startup.module)),
            version=str(payload.get("version", "0.0.0")),
            compat_range=str(payload.get("compat_range", "*")),
            summary=str(payload["summary"])
            if payload.get("summary") is not None
            else None,
            panels=(
                [
                    str(item)
                    for item in payload.get("panels", [])
                    if isinstance(item, str)
                ]
                or panels
            ),
            commands=(
                [
                    str(item)
                    for item in payload.get("commands", [])
                    if isinstance(item, str)
                ]
                or commands
            ),
            datasources=[
                str(item)
                for item in payload.get("datasources", [])
                if isinstance(item, str)
            ],
            admin_pages=[
                str(item)
                for item in payload.get("admin_pages", [])
                if isinstance(item, str)
            ],
            permissions=[
                str(item)
                for item in payload.get("permissions", [])
                if isinstance(item, str)
            ],
            runtime_mode=str(payload.get("runtime_mode", "hosted")),
        )

    def _require_plugin(self, plugin_id: str) -> InstalledPlugin:
        plugin = self.get_plugin(plugin_id)
        if plugin is None:
            raise LookupError(f"Plugin '{plugin_id}' was not found.")
        return plugin

    def _require_hosted_plugin(
        self,
        plugin_id: str,
        *,
        required_permission: str,
    ) -> InstalledPlugin:
        plugin = self._require_plugin(plugin_id)
        if not plugin.enabled:
            raise RuntimeError(f"Plugin '{plugin.name}' is disabled.")
        if str(plugin.manifest.get("runtime_mode", "hosted")) != "hosted":
            raise RuntimeError(
                f"Plugin '{plugin.name}' is not available in hosted mode."
            )
        if plugin.status in {
            "integrity_failed",
            "permission_denied",
            "incompatible",
            "runtime_unsupported",
            "missing_install",
        }:
            raise RuntimeError(
                f"Plugin '{plugin.name}' is unavailable ({plugin.status})."
            )
        permissions = plugin.manifest.get("permissions", [])
        if isinstance(permissions, list) and required_permission not in permissions:
            raise RuntimeError(
                f"Plugin '{plugin.name}' does not declare permission '{required_permission}'."
            )
        return plugin

    @staticmethod
    def _distribution_version(module_name: str) -> str:
        candidates = [module_name, module_name.split(".", 1)[0].replace("_", "-")]
        for candidate in candidates:
            try:
                return importlib_metadata.version(candidate)
            except importlib_metadata.PackageNotFoundError:
                continue
        return "0.0.0"

    def _resolve_app_version(self) -> str:
        try:
            return importlib_metadata.version("cockpit")
        except importlib_metadata.PackageNotFoundError:
            pass
        project_root = discover_project_root(self._start)
        pyproject_path = project_root / "pyproject.toml"
        if pyproject_path.exists():
            payload = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
            project_payload = payload.get("project", {})
            if isinstance(project_payload, dict):
                version = project_payload.get("version")
                if isinstance(version, str) and version.strip():
                    return version.strip()
        return "0.0.0"

    def _validate_requirement(self, requirement: str, source: str | None) -> None:
        normalized = requirement.strip()
        if not normalized:
            raise ValueError("Plugin requirement must not be empty.")
        if self._is_local_requirement(normalized):
            return
        if any(token in normalized for token in ("://", "git+")):
            candidates = [normalized]
            if isinstance(source, str) and source.strip():
                candidates.append(source.strip())
            trusted_sources = self._effective_trusted_sources()
            if not any(
                candidate.startswith(prefix)
                for candidate in candidates
                for prefix in trusted_sources
            ):
                raise ValueError(
                    "Plugin source is not trusted. Configure a trusted source prefix before installing it."
                )

    def _validate_manifest(self, manifest: PluginManifest) -> None:
        if (
            SpecifierSet is None
            or Version is None
            or not manifest.compat_range
            or manifest.compat_range == "*"
        ):
            return
        specifier = SpecifierSet(manifest.compat_range)
        if not specifier.contains(Version(self._app_version), prereleases=True):
            raise RuntimeError(
                f"Plugin '{manifest.name}' is incompatible with cockpit {self._app_version}."
            )

    def _runtime_plugins(self) -> list[InstalledPlugin]:
        refreshed: list[InstalledPlugin] = []
        for plugin in self._repository.list_all():
            updated = self._runtime_state_for(plugin)
            if updated != plugin:
                self._repository.save(updated)
            refreshed.append(updated)
        return refreshed

    def _runtime_state_for(self, plugin: InstalledPlugin) -> InstalledPlugin:
        if not plugin.install_path:
            return plugin
        install_path = Path(plugin.install_path)
        if not install_path.exists():
            return self._with_status(plugin, "missing_install")
        if not self._manifest_is_compatible(plugin.manifest):
            return self._with_status(plugin, "incompatible")
        runtime_mode = str(plugin.manifest.get("runtime_mode", "hosted"))
        if runtime_mode != "hosted":
            return self._with_status(plugin, "runtime_unsupported")
        if not self._permissions_allowed(plugin.manifest):
            return self._with_status(plugin, "permission_denied")
        current_integrity = self._compute_install_integrity(install_path)
        expected_integrity = self._expected_integrity(plugin)
        manifest = dict(plugin.manifest)
        manifest["current_integrity_sha256"] = current_integrity
        if expected_integrity and current_integrity != expected_integrity:
            return InstalledPlugin(
                id=plugin.id,
                name=plugin.name,
                module=plugin.module,
                requirement=plugin.requirement,
                version_pin=plugin.version_pin,
                install_path=plugin.install_path,
                enabled=plugin.enabled,
                source=plugin.source,
                manifest=manifest,
                status="integrity_failed",
            )
        host_client = self._host_clients.get(plugin.id)
        status = "installed"
        if plugin.enabled and host_client is not None:
            if host_client.is_running():
                status = "host_running"
            elif host_client.last_error:
                status = "host_failed"
        return InstalledPlugin(
            id=plugin.id,
            name=plugin.name,
            module=plugin.module,
            requirement=plugin.requirement,
            version_pin=plugin.version_pin,
            install_path=plugin.install_path,
            enabled=plugin.enabled,
            source=plugin.source,
            manifest=manifest,
            status=status,
        )

    def _manifest_is_compatible(self, manifest_payload: dict[str, object]) -> bool:
        compat_range = manifest_payload.get("compat_range")
        if not isinstance(compat_range, str) or not compat_range or compat_range == "*":
            return True
        if SpecifierSet is None or Version is None:
            return True
        return SpecifierSet(compat_range).contains(
            Version(self._app_version),
            prereleases=True,
        )

    @staticmethod
    def _with_status(plugin: InstalledPlugin, status: str) -> InstalledPlugin:
        return InstalledPlugin(
            id=plugin.id,
            name=plugin.name,
            module=plugin.module,
            requirement=plugin.requirement,
            version_pin=plugin.version_pin,
            install_path=plugin.install_path,
            enabled=plugin.enabled,
            source=plugin.source,
            manifest=dict(plugin.manifest),
            status=status,
        )

    def _with_runtime_manifest_data(
        self,
        manifest: PluginManifest,
        install_path: Path,
        *,
        startup: PluginHostStartup,
        expected_integrity_sha256: str | None = None,
    ) -> dict[str, object]:
        manifest_payload = manifest.to_dict()
        manifest_payload["exported_panels"] = [
            panel.to_dict() for panel in startup.panels
        ]
        manifest_payload["exported_commands"] = [
            command.to_dict() for command in startup.commands
        ]
        installed_integrity = self._compute_install_integrity(install_path)
        manifest_payload["installed_integrity_sha256"] = installed_integrity
        manifest_payload["current_integrity_sha256"] = installed_integrity
        if (
            isinstance(expected_integrity_sha256, str)
            and expected_integrity_sha256.strip()
        ):
            expected = expected_integrity_sha256.strip().lower()
            if installed_integrity != expected:
                raise RuntimeError(
                    f"Plugin '{manifest.name}' does not match the expected integrity hash."
                )
            manifest_payload["expected_integrity_sha256"] = expected
        return manifest_payload

    @staticmethod
    def _expected_integrity(plugin: InstalledPlugin) -> str | None:
        expected = plugin.manifest.get("expected_integrity_sha256")
        if isinstance(expected, str) and expected.strip():
            return expected.strip().lower()
        installed = plugin.manifest.get("installed_integrity_sha256")
        if isinstance(installed, str) and installed.strip():
            return installed.strip().lower()
        return None

    @staticmethod
    def _compute_install_integrity(install_path: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(install_path.rglob("*")):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                continue
            relative = path.relative_to(install_path).as_posix()
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()

    def _effective_trusted_sources(self) -> tuple[str, ...]:
        if self._trusted_sources:
            return self._trusted_sources
        return DEFAULT_TRUSTED_SOURCE_PREFIXES

    def _effective_allowed_permissions(self) -> tuple[str, ...]:
        if self._allowed_permissions:
            return self._allowed_permissions
        return DEFAULT_ALLOWED_PLUGIN_PERMISSIONS

    def _permissions_allowed(self, manifest_payload: dict[str, object]) -> bool:
        raw_permissions = manifest_payload.get("permissions", [])
        declared = {
            permission.strip()
            for permission in raw_permissions
            if isinstance(permission, str) and permission.strip()
        }
        allowed_permissions = set(self._effective_allowed_permissions())
        if any(permission not in allowed_permissions for permission in declared):
            return False
        exported_panels = manifest_payload.get("exported_panels", [])
        exported_commands = manifest_payload.get("exported_commands", [])
        if (
            isinstance(exported_panels, list)
            and exported_panels
            and "ui.read" not in declared
        ):
            return False
        if (
            isinstance(exported_commands, list)
            and exported_commands
            and "commands.execute" not in declared
        ):
            return False
        return True

    @staticmethod
    def _is_local_requirement(requirement: str) -> bool:
        expanded = Path(os.path.expanduser(requirement))
        return expanded.exists()
