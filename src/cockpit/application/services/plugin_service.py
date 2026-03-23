"""Managed plugin installation and runtime activation."""

from __future__ import annotations

import importlib
from importlib import metadata as importlib_metadata
import importlib.util
import hashlib
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from cockpit.domain.models.plugin import InstalledPlugin, PluginManifest
from cockpit.infrastructure.persistence.repositories import InstalledPluginRepository
from cockpit.shared.config import discover_project_root, state_dir
from cockpit.shared.utils import make_id

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
        inserted: list[str] = []
        for plugin in self._runtime_plugins():
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
        return [
            plugin.module
            for plugin in self._runtime_plugins()
            if plugin.enabled and plugin.status == "installed"
        ]

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
        install_spec = self._install_spec(requirement, version_pin)
        self._run_pip_install(install_spec, install_path)
        if str(install_path) not in sys.path:
            sys.path.insert(0, str(install_path))
        importlib.invalidate_caches()
        manifest = self._load_manifest(module_name)
        self._validate_manifest(manifest)
        runtime_manifest = self._with_runtime_manifest_data(
            manifest,
            install_path,
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
        return plugin

    def update_plugin(self, plugin_id: str) -> InstalledPlugin:
        plugin = self._require_plugin(plugin_id)
        self._validate_requirement(plugin.requirement, plugin.source)
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
        self._validate_manifest(manifest)
        runtime_manifest = self._with_runtime_manifest_data(
            manifest,
            install_path,
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
        plugins = self._runtime_plugins()
        return {
            "count": len(plugins),
            "enabled": sum(1 for plugin in plugins if plugin.enabled),
            "modules": [plugin.module for plugin in plugins],
            "trusted_sources": list(self._effective_trusted_sources()),
            "allowed_permissions": list(self._effective_allowed_permissions()),
            "app_version": self._app_version,
            "integrity_failed": sum(1 for plugin in plugins if plugin.status == "integrity_failed"),
            "incompatible": sum(1 for plugin in plugins if plugin.status == "incompatible"),
            "permission_denied": sum(1 for plugin in plugins if plugin.status == "permission_denied"),
            "runtime_unsupported": sum(1 for plugin in plugins if plugin.status == "runtime_unsupported"),
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
                permissions=[str(item) for item in raw_manifest.get("permissions", []) if isinstance(item, str)],
                runtime_mode=str(raw_manifest.get("runtime_mode", "inprocess")),
            )
        spec = importlib.util.find_spec(module_name)
        version = self._distribution_version(module_name) if spec is not None else "0.0.0"
        return PluginManifest(name=module_name, module=module_name, version=version)

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
        runtime_mode = plugin.manifest.get("runtime_mode")
        if isinstance(runtime_mode, str) and runtime_mode.strip() and runtime_mode != "inprocess":
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
            status="installed",
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
        expected_integrity_sha256: str | None = None,
    ) -> dict[str, object]:
        manifest_payload = manifest.to_dict()
        installed_integrity = self._compute_install_integrity(install_path)
        manifest_payload["installed_integrity_sha256"] = installed_integrity
        manifest_payload["current_integrity_sha256"] = installed_integrity
        if isinstance(expected_integrity_sha256, str) and expected_integrity_sha256.strip():
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
        if not isinstance(raw_permissions, list):
            return True
        allowed_permissions = set(self._effective_allowed_permissions())
        for permission in raw_permissions:
            if not isinstance(permission, str):
                continue
            normalized = permission.strip()
            if normalized and normalized not in allowed_permissions:
                return False
        return True

    @staticmethod
    def _is_local_requirement(requirement: str) -> bool:
        expanded = Path(os.path.expanduser(requirement))
        return expanded.exists()
