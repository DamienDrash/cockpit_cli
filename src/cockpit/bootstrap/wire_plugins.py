"""Plugin context wiring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cockpit.plugins.services.plugin_service import PluginService
from cockpit.workspace.repositories import (
    InstalledPluginRepository,
)
from cockpit.core.persistence.sqlite_store import SQLiteStore


def wire_plugins(
    store: SQLiteStore,
    start: Path | None,
    plugin_config: dict[str, Any],
) -> dict[str, Any]:
    """Wire plugin components."""
    installed_plugin_repository = InstalledPluginRepository(store)

    plugin_service = PluginService(
        installed_plugin_repository,
        start=start,
        trusted_sources=tuple(
            item
            for item in plugin_config.get("trusted_sources", [])
            if isinstance(item, str) and item
        )
        if isinstance(plugin_config.get("trusted_sources", []), list)
        else (),
        allowed_permissions=tuple(
            item
            for item in plugin_config.get("allowed_permissions", [])
            if isinstance(item, str) and item
        )
        if isinstance(plugin_config.get("allowed_permissions", []), list)
        else (),
    )

    return {
        "plugin_service": plugin_service,
    }
