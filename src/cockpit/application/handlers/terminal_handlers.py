"""Terminal control handlers."""

from __future__ import annotations

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.application.handlers.base import CommandContextError, DispatchResult
from cockpit.domain.commands.command import Command
from cockpit.domain.events.runtime_events import PanelFocused
from cockpit.runtime.pty_manager import PTYManager


class FocusTerminalHandler:
    """Publish focus requests for the current terminal panel."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    def __call__(self, command: Command) -> DispatchResult:
        panel_id = command.context.get("panel_id", "work-panel")
        if not isinstance(panel_id, str):
            raise CommandContextError("panel_id context must be a string.")
        self._event_bus.publish(PanelFocused(panel_id=panel_id))
        return DispatchResult(
            success=True,
            message="Terminal focused.",
            data={"panel_id": panel_id},
        )


class RestartTerminalHandler:
    """Restart the terminal session for the active panel."""

    def __init__(self, pty_manager: PTYManager) -> None:
        self._pty_manager = pty_manager

    def __call__(self, command: Command) -> DispatchResult:
        panel_id = command.context.get("panel_id", "work-panel")
        if not isinstance(panel_id, str):
            raise CommandContextError("panel_id context must be a string.")

        cwd = command.context.get("cwd")
        if cwd is None:
            session = self._pty_manager.get_session(panel_id)
            cwd = session.cwd if session is not None else command.context.get(
                "workspace_root"
            )
        if not isinstance(cwd, str):
            raise CommandContextError("No cwd is available for terminal restart.")

        session = self._pty_manager.restart_session(panel_id, cwd)
        if session is None:
            raise CommandContextError("Terminal restart failed.")
        return DispatchResult(
            success=True,
            message=f"Terminal restarted in {session.cwd}",
            data={"panel_id": panel_id, "cwd": session.cwd},
        )
