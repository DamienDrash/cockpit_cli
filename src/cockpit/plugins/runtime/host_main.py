"""Isolated managed plugin host entrypoint."""

from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
from typing import Any, TextIO

from cockpit.core.dispatch.handler_base import DispatchResult
from cockpit.core.command import Command
from cockpit.core.panel_state import PanelState
from cockpit.plugins.models import PluginManifest
from cockpit.plugins.loader import PluginLoader
from cockpit.plugins.runtime.contracts import HostedCommandExport, HostedPanelExport
from cockpit.core.enums import CommandSource
from cockpit.core.utils import serialize_value


class HostedPluginContext:
    """Capture plugin registrations inside the isolated host."""

    def __init__(self, *, project_root: Path) -> None:
        self.project_root = project_root
        self.command_catalog: list[str] = []
        self.panel_specs: dict[str, Any] = {}
        self.command_handlers: dict[str, Any] = {}

    def register_panel(self, spec: Any) -> None:
        panel_id = getattr(spec, "panel_id", None)
        if not isinstance(panel_id, str) or not panel_id:
            raise ValueError("Hosted plugin panels must define a string panel_id.")
        self.panel_specs[panel_id] = spec

    def register_command(self, name: str, handler: Any) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("Hosted plugin commands must define a string name.")
        self.command_handlers[name] = handler
        if name not in self.command_catalog:
            self.command_catalog.append(name)


class HostedPluginRuntime:
    """Runtime facade for a single managed plugin module."""

    def __init__(
        self,
        *,
        plugin_id: str,
        module_name: str,
        install_path: Path,
        project_root: Path,
        allowed_permissions: tuple[str, ...],
    ) -> None:
        self._plugin_id = plugin_id
        self._module_name = module_name
        self._install_path = install_path
        self._project_root = project_root
        self._allowed_permissions = set(allowed_permissions)
        self._context = HostedPluginContext(project_root=project_root)
        self._panel_instances: dict[str, Any] = {}
        self._loader = PluginLoader()
        self._manifest = self._load_plugin()

    @property
    def manifest(self) -> PluginManifest:
        return self._manifest

    def startup_payload(self) -> dict[str, object]:
        return {
            "plugin_id": self._plugin_id,
            "module": self._module_name,
            "manifest": self._manifest.to_dict(),
            "panels": [
                HostedPanelExport(
                    panel_id=spec.panel_id,
                    panel_type=spec.panel_type,
                    display_name=spec.display_name,
                ).to_dict()
                for spec in self._context.panel_specs.values()
            ],
            "commands": [
                HostedCommandExport(name=name).to_dict()
                for name in self._context.command_handlers
            ],
            "admin_pages": list(self._manifest.admin_pages),
        }

    def invoke(self, method: str, params: dict[str, object]) -> dict[str, object]:
        if method == "shutdown":
            return {}
        if method == "command.invoke":
            return self._invoke_command(params)
        if method.startswith("panel."):
            return self._handle_panel_action(method.removeprefix("panel."), params)
        raise RuntimeError(f"Unsupported plugin host method '{method}'.")

    def _load_plugin(self) -> PluginManifest:
        sys.path.insert(0, str(self._install_path))
        importlib.invalidate_caches()
        register_hook = self._loader._load_register_hook(self._module_name)
        register_hook(self._context)
        manifest = self._loader.manifest_for_module(self._module_name)
        if manifest is None:
            manifest = PluginManifest(
                name=self._module_name,
                module=self._module_name,
                version="0.0.0",
                runtime_mode="hosted",
            )
        if manifest.runtime_mode != "hosted":
            raise RuntimeError(
                f"Managed plugin '{manifest.name}' must declare runtime_mode='hosted'."
            )
        self._validate_permissions(manifest)
        return manifest

    def _validate_permissions(self, manifest: PluginManifest) -> None:
        declared = {
            permission.strip()
            for permission in manifest.permissions
            if isinstance(permission, str) and permission.strip()
        }
        if self._context.panel_specs and "ui.read" not in declared:
            raise RuntimeError(
                "Hosted plugins that export panels must declare ui.read."
            )
        if self._context.command_handlers and "commands.execute" not in declared:
            raise RuntimeError(
                "Hosted plugins that export commands must declare commands.execute."
            )

    def _invoke_command(self, params: dict[str, object]) -> dict[str, object]:
        command_name = str(params.get("command_name", ""))
        handler = self._context.command_handlers.get(command_name)
        if handler is None:
            raise LookupError(f"Plugin command '{command_name}' is not registered.")
        command_payload = params.get("command", {})
        if not isinstance(command_payload, dict):
            raise TypeError("Plugin command payload must be a JSON object.")
        command = Command(
            id=str(command_payload.get("id", "")),
            source=CommandSource(
                str(command_payload.get("source", CommandSource.PALETTE.value))
            ),
            name=str(command_payload.get("name", command_name)),
            args=dict(command_payload.get("args", {}))
            if isinstance(command_payload.get("args"), dict)
            else {},
            context=dict(command_payload.get("context", {}))
            if isinstance(command_payload.get("context"), dict)
            else {},
        )
        result = handler(command)
        if not isinstance(result, DispatchResult):
            raise TypeError("Plugin command handlers must return DispatchResult.")
        return {"dispatch_result": serialize_value(result)}

    def _handle_panel_action(
        self, action: str, params: dict[str, object]
    ) -> dict[str, object]:
        panel_id = str(params.get("panel_id", ""))
        panel = self._panel_instance(panel_id)
        payload = params.get("payload", {})
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise TypeError("Plugin panel payload must be a JSON object.")
        if action == "initialize":
            panel.initialize(payload)
        elif action == "restore_state":
            panel.restore_state(payload)
        elif action == "snapshot_state":
            state = panel.snapshot_state()
            if not isinstance(state, PanelState):
                raise TypeError("Plugin panel snapshot_state must return PanelState.")
            return {
                "panel_state": serialize_value(state),
                "render_text": self._render_panel(panel),
            }
        elif action == "command_context":
            context = panel.command_context()
            return {
                "command_context": dict(context) if isinstance(context, dict) else {},
                "render_text": self._render_panel(panel),
            }
        elif action == "suspend":
            panel.suspend()
        elif action == "resume":
            panel.resume()
        elif action == "dispose":
            panel.dispose()
        elif action == "focus":
            focus = getattr(panel, "focus", None)
            if callable(focus):
                focus()
        elif action == "apply_command_result":
            apply = getattr(panel, "apply_command_result", None)
            if callable(apply):
                apply(payload)
        else:
            raise RuntimeError(f"Unsupported panel action '{action}'.")
        return {"render_text": self._render_panel(panel)}

    def _panel_instance(self, panel_id: str) -> Any:
        if panel_id in self._panel_instances:
            return self._panel_instances[panel_id]
        spec = self._context.panel_specs.get(panel_id)
        if spec is None:
            raise LookupError(f"Plugin panel '{panel_id}' is not registered.")
        container = SimpleNamespace(
            project_root=self._project_root, plugin_id=self._plugin_id
        )
        panel = spec.factory(container)
        self._panel_instances[panel_id] = panel
        return panel

    @staticmethod
    def _render_panel(panel: Any) -> str:
        render_text = getattr(panel, "_render_text", None)
        if callable(render_text):
            try:
                result = render_text()
                if isinstance(result, str):
                    return result
            except Exception:
                pass
        renderable = getattr(panel, "renderable", None)
        if renderable is not None:
            return str(renderable)
        render = getattr(panel, "render", None)
        if callable(render):
            try:
                return str(render())
            except Exception:
                pass
        snapshot = getattr(panel, "snapshot_state", None)
        if callable(snapshot):
            try:
                state = snapshot()
                if isinstance(state, PanelState):
                    return json.dumps(state.snapshot, indent=2, sort_keys=True)
            except Exception:
                pass
        return f"{getattr(panel, 'PANEL_TYPE', 'plugin')} panel ready."


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cockpit managed plugin host")
    parser.add_argument("--plugin-id", required=True)
    parser.add_argument("--module", required=True)
    parser.add_argument("--install-path", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--allowed-permissions", default="[]")
    parser.add_argument("--app-version", default="0.0.0")
    return parser.parse_args()


def _open_channel() -> tuple[socket.socket, TextIO, TextIO]:
    raw_fd = os.environ.get("COCKPIT_PLUGIN_HOST_FD")
    if raw_fd is None:
        raise RuntimeError("COCKPIT_PLUGIN_HOST_FD is required.")
    channel = socket.socket(fileno=int(raw_fd))
    reader = channel.makefile("r", encoding="utf-8")
    writer = channel.makefile("w", encoding="utf-8", buffering=1)
    return channel, reader, writer


def _send_message(writer: TextIO, payload: dict[str, object]) -> None:
    writer.write(json.dumps(payload, sort_keys=True) + "\n")
    writer.flush()


def main() -> int:
    args = _parse_args()
    channel, reader, writer = _open_channel()
    try:
        runtime = HostedPluginRuntime(
            plugin_id=args.plugin_id,
            module_name=args.module,
            install_path=Path(args.install_path),
            project_root=Path(args.project_root),
            allowed_permissions=tuple(
                str(item)
                for item in json.loads(args.allowed_permissions)
                if isinstance(item, str)
            ),
        )
        _send_message(
            writer,
            {
                "type": "startup",
                "ok": True,
                "payload": runtime.startup_payload(),
            },
        )
        for line in reader:
            payload: dict[str, object] | None = None
            try:
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise TypeError("Plugin host message must be a JSON object.")
                method = str(payload.get("method", ""))
                params = payload.get("params", {})
                if not isinstance(params, dict):
                    raise TypeError("Plugin host params must be a JSON object.")
                result = runtime.invoke(method, params)
                _send_message(
                    writer,
                    {
                        "type": "response",
                        "request_id": payload.get("request_id"),
                        "ok": True,
                        "result": result,
                    },
                )
                if method == "shutdown":
                    break
            except Exception as exc:
                _send_message(
                    writer,
                    {
                        "type": "response",
                        "request_id": payload.get("request_id")
                        if isinstance(payload, dict)
                        else None,
                        "ok": False,
                        "error": str(exc),
                    },
                )
                if isinstance(payload, dict) and payload.get("method") == "shutdown":
                    break
    except Exception as exc:
        _send_message(
            writer,
            {
                "type": "startup",
                "ok": False,
                "error": str(exc),
            },
        )
        return 1
    finally:
        writer.close()
        reader.close()
        channel.close()
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess tests
    raise SystemExit(main())
