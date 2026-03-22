"""Plugin manifest and installation models."""

from __future__ import annotations

from dataclasses import dataclass, field

from cockpit.shared.utils import serialize_contract


@dataclass(slots=True)
class PluginManifest:
    name: str
    module: str
    version: str
    compat_range: str = "*"
    summary: str | None = None
    panels: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    datasources: list[str] = field(default_factory=list)
    admin_pages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class InstalledPlugin:
    id: str
    name: str
    module: str
    requirement: str
    version_pin: str | None = None
    install_path: str | None = None
    enabled: bool = True
    source: str | None = None
    manifest: dict[str, object] = field(default_factory=dict)
    status: str = "installed"

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)
