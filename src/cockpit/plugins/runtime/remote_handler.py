"""Core-side command handler proxies for isolated managed plugins."""

from __future__ import annotations

from cockpit.core.dispatch.handler_base import DispatchResult


class RemotePluginCommandHandler:
    """Forward command execution into a managed plugin host."""

    def __init__(
        self,
        *,
        plugin_service: object,
        plugin_id: str,
        command_name: str,
    ) -> None:
        self._plugin_service = plugin_service
        self._plugin_id = plugin_id
        self._command_name = command_name

    def __call__(self, command: object) -> DispatchResult:
        invoke = getattr(self._plugin_service, "invoke_command")
        try:
            return invoke(
                plugin_id=self._plugin_id,
                command_name=self._command_name,
                command=command,
            )
        except Exception as exc:
            return DispatchResult(
                success=False,
                message=f"Plugin host error: {exc}",
            )
