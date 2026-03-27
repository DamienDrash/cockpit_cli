"""External plugin loading for panels and commands."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import importlib
from pathlib import Path
from typing import Any, Protocol

from cockpit.core.dispatch.command_dispatcher import CommandDispatcher
from cockpit.plugins.models import PluginManifest
from cockpit.ui.panels.registry import PanelRegistry, PanelSpec


class PluginRegistrationHook(Protocol):
    def __call__(self, context: "PluginBootstrapContext") -> None: ...


@dataclass(slots=True)
class PluginBootstrapContext:
    project_root: Path
    panel_registry: PanelRegistry
    command_dispatcher: CommandDispatcher
    command_catalog: list[str] = field(default_factory=list)

    def register_panel(self, spec: PanelSpec) -> None:
        self.panel_registry.register(spec)

    def register_command(self, name: str, handler: Callable[[Any], Any]) -> None:
        self.command_dispatcher.register(name, handler)
        if name not in self.command_catalog:
            self.command_catalog.append(name)


class PluginLoader:
    """Load importable plugin modules declared in config."""

    def __init__(self, *, allowed_module_prefixes: tuple[str, ...] = ()) -> None:
        self._allowed_module_prefixes = tuple(
            prefix.strip()
            for prefix in allowed_module_prefixes
            if isinstance(prefix, str) and prefix.strip()
        )

    def load_from_config(
        self,
        payload: dict[str, object],
        *,
        context: PluginBootstrapContext,
    ) -> list[str]:
        raw_plugins = payload.get("plugins", [])
        loaded_modules: list[str] = []
        if not isinstance(raw_plugins, list):
            return loaded_modules
        for raw_plugin in raw_plugins:
            module_name = self._module_name(raw_plugin)
            if not module_name:
                continue
            register_hook = self._load_register_hook(module_name)
            register_hook(context)
            loaded_modules.append(module_name)
        return loaded_modules

    def _module_name(self, raw_plugin: object) -> str | None:
        if isinstance(raw_plugin, str) and raw_plugin:
            return raw_plugin
        if isinstance(raw_plugin, dict):
            enabled = raw_plugin.get("enabled", True)
            if enabled is False:
                return None
            module_name = raw_plugin.get("module")
            if isinstance(module_name, str) and module_name:
                return module_name
        return None

    def _load_register_hook(self, module_name: str) -> PluginRegistrationHook:
        if self._allowed_module_prefixes and not any(
            module_name.startswith(prefix) for prefix in self._allowed_module_prefixes
        ):
            raise ValueError(
                f"Plugin module '{module_name}' is not permitted in the in-process loader."
            )
        module = importlib.import_module(module_name)
        register = getattr(module, "register_plugin", None)
        if not callable(register):
            raise ValueError(
                f"Plugin module '{module_name}' does not expose a callable register_plugin(context)."
            )
        return register

    def manifest_for_module(self, module_name: str) -> PluginManifest | None:
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
                version=str(raw_manifest.get("version", "0.0.0")),
                compat_range=str(raw_manifest.get("compat_range", "*")),
                summary=(
                    str(raw_manifest["summary"])
                    if raw_manifest.get("summary") is not None
                    else None
                ),
                panels=[
                    str(item)
                    for item in raw_manifest.get("panels", [])
                    if isinstance(item, str)
                ],
                commands=[
                    str(item)
                    for item in raw_manifest.get("commands", [])
                    if isinstance(item, str)
                ],
                datasources=[
                    str(item)
                    for item in raw_manifest.get("datasources", [])
                    if isinstance(item, str)
                ],
                admin_pages=[
                    str(item)
                    for item in raw_manifest.get("admin_pages", [])
                    if isinstance(item, str)
                ],
            )
        return None
