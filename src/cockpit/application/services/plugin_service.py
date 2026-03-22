"""Managed plugin installation and runtime activation."""

from __future__ import annotations

import importlib
from importlib import metadata as importlib_metadata
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

from cockpit.domain.models.plugin import InstalledPlugin, PluginManifest
from cockpit.infrastructure.persistence.repositories import InstalledPluginRepository
from cockpit.shared.config import state_dir
from cockpit.shared.utils import make_id


class PluginService:
    """Install, pin, remove, and activate Cockpit plugins."""

    def __init__(
        self,
        repository: InstalledPluginRepository,
        *,
        start: Path | None = None,
        pip_runner: object | None = None,
    ) -> None:
        self._repository = repository
        self._start = start
        self._pip_runner = pip_runner or subprocess.run

    def list_plugins(self) -> list[InstalledPlugin]:
        return self._repository.list_all()

    def get_plugin(self, plugin_id: str) -> InstalledPlugin | None:
        return self._repository.get(plugin_id)

    def enable_runtime_paths(self) -> list[str]:
        inserted: list[str] = []
        for plugin in self.list_plugins():
            if not plugin.enabled or not plugin.install_path:
                continue
            install_path = str(Path(plugin.install_path).resolve())
            if install_path not in sys.path:
                sys.path.insert(0, install_path)
                inserted.append(install_path)
        if inserted:
            importlib.invalidate_caches()
        return inserted

    def enabled_modules(self) -> list[str]:
        self.enable_runtime_paths()
        return [plugin.module for plugin in self.list_plugins() if plugin.enabled]

    def install_plugin(
        self,
        *,
        requirement: str,
        module_name: str,
        display_name: str | None = None,
        version_pin: str | None = None,
        source: str | None = None,
    ) -> InstalledPlugin:
        if not requirement.strip():
            raise ValueError("Plugin requirement must not be empty.")
        if not module_name.strip():
            raise ValueError("Plugin module name must not be empty.")
        plugin_id = make_id("plg")
        install_path = self._plugin_install_root(plugin_id)
        install_path.mkdir(parents=True, exist_ok=True)
        install_spec = self._install_spec(requirement, version_pin)
        self._run_pip_install(install_spec, install_path)
        if str(install_path) not in sys.path:
            sys.path.insert(0, str(install_path))
        importlib.invalidate_caches()
        manifest = self._load_manifest(module_name)
        plugin = InstalledPlugin(
            id=plugin_id,
            name=display_name or manifest.name,
            module=module_name,
            requirement=requirement,
            version_pin=version_pin,
            install_path=str(install_path),
            enabled=True,
            source=source,
            manifest=manifest.to_dict(),
            status="installed",
        )
        self._repository.save(plugin)
        return plugin

    def update_plugin(self, plugin_id: str) -> InstalledPlugin:
        plugin = self._require_plugin(plugin_id)
        install_path = Path(plugin.install_path or self._plugin_install_root(plugin_id))
        install_path.mkdir(parents=True, exist_ok=True)
        self._run_pip_install(
            self._install_spec(plugin.requirement, plugin.version_pin),
            install_path,
        )
        if str(install_path) not in sys.path:
            sys.path.insert(0, str(install_path))
        importlib.invalidate_caches()
        manifest = self._load_manifest(plugin.module)
        updated = InstalledPlugin(
            id=plugin.id,
            name=plugin.name,
            module=plugin.module,
            requirement=plugin.requirement,
            version_pin=plugin.version_pin,
            install_path=str(install_path),
            enabled=plugin.enabled,
            source=plugin.source,
            manifest=manifest.to_dict(),
            status="installed",
        )
        self._repository.save(updated)
        return updated

    def set_enabled(self, plugin_id: str, enabled: bool) -> InstalledPlugin:
        plugin = self._require_plugin(plugin_id)
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
        return updated

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
        if plugin.install_path:
            shutil.rmtree(plugin.install_path, ignore_errors=True)
        self._repository.delete(plugin_id)

    def diagnostics(self) -> dict[str, object]:
        plugins = self.list_plugins()
        return {
            "count": len(plugins),
            "enabled": sum(1 for plugin in plugins if plugin.enabled),
            "modules": [plugin.module for plugin in plugins],
        }

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
            raise RuntimeError(stderr.strip() or f"pip install failed for {requirement}.")

    def _load_manifest(self, module_name: str) -> PluginManifest:
        module = importlib.import_module(module_name)
        raw_manifest = getattr(module, "PLUGIN_MANIFEST", None)
        if callable(raw_manifest):
            raw_manifest = raw_manifest()
        if isinstance(raw_manifest, PluginManifest):
            return raw_manifest
        if isinstance(raw_manifest, dict):
            return PluginManifest(
                name=str(raw_manifest.get("name", module_name)),
                module=str(raw_manifest.get("module", module_name)),
                version=str(raw_manifest.get("version", self._distribution_version(module_name))),
                compat_range=str(raw_manifest.get("compat_range", "*")),
                summary=(
                    str(raw_manifest["summary"])
                    if raw_manifest.get("summary") is not None
                    else None
                ),
                panels=[str(item) for item in raw_manifest.get("panels", []) if isinstance(item, str)],
                commands=[str(item) for item in raw_manifest.get("commands", []) if isinstance(item, str)],
                datasources=[str(item) for item in raw_manifest.get("datasources", []) if isinstance(item, str)],
                admin_pages=[str(item) for item in raw_manifest.get("admin_pages", []) if isinstance(item, str)],
            )
        spec = importlib.util.find_spec(module_name)
        version = self._distribution_version(module_name) if spec is not None else "0.0.0"
        return PluginManifest(name=module_name, module=module_name, version=version)

    @staticmethod
    def _install_spec(requirement: str, version_pin: str | None) -> str:
        if version_pin:
            normalized = requirement.strip()
            if any(token in normalized for token in ("://", "/", "@")):
                return normalized
            return f"{normalized}=={version_pin}"
        return requirement.strip()

    def _require_plugin(self, plugin_id: str) -> InstalledPlugin:
        plugin = self.get_plugin(plugin_id)
        if plugin is None:
            raise LookupError(f"Plugin '{plugin_id}' was not found.")
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
