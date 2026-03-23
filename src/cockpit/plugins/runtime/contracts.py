"""Contracts shared between the core process and managed plugin hosts."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class HostedPanelExport:
    panel_id: str
    panel_type: str
    display_name: str

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> "HostedPanelExport":
        return cls(
            panel_id=str(payload.get("panel_id", "")),
            panel_type=str(payload.get("panel_type", "")),
            display_name=str(payload.get("display_name", payload.get("panel_type", ""))),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "panel_id": self.panel_id,
            "panel_type": self.panel_type,
            "display_name": self.display_name,
        }


@dataclass(slots=True)
class HostedCommandExport:
    name: str

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> "HostedCommandExport":
        return cls(name=str(payload.get("name", "")))

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name}


@dataclass(slots=True)
class PluginHostStartup:
    plugin_id: str
    module: str
    manifest: dict[str, object] = field(default_factory=dict)
    panels: tuple[HostedPanelExport, ...] = ()
    commands: tuple[HostedCommandExport, ...] = ()
    admin_pages: tuple[str, ...] = ()
    pid: int | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> "PluginHostStartup":
        raw_panels = payload.get("panels", [])
        raw_commands = payload.get("commands", [])
        raw_admin_pages = payload.get("admin_pages", [])
        return cls(
            plugin_id=str(payload.get("plugin_id", "")),
            module=str(payload.get("module", "")),
            manifest=(
                dict(payload["manifest"])
                if isinstance(payload.get("manifest"), dict)
                else {}
            ),
            panels=tuple(
                HostedPanelExport.from_payload(item)
                for item in raw_panels
                if isinstance(item, dict)
            ),
            commands=tuple(
                HostedCommandExport.from_payload(item)
                for item in raw_commands
                if isinstance(item, dict)
            ),
            admin_pages=tuple(
                str(item) for item in raw_admin_pages if isinstance(item, str)
            ),
            pid=(
                int(payload["pid"])
                if isinstance(payload.get("pid"), int)
                else None
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "plugin_id": self.plugin_id,
            "module": self.module,
            "manifest": dict(self.manifest),
            "panels": [panel.to_dict() for panel in self.panels],
            "commands": [command.to_dict() for command in self.commands],
            "admin_pages": list(self.admin_pages),
            "pid": self.pid,
        }
