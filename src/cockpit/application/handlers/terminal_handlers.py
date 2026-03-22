"""Terminal control handlers."""

from __future__ import annotations

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.application.handlers.base import CommandContextError, DispatchResult
from cockpit.domain.commands.command import Command
from cockpit.domain.events.runtime_events import PanelFocused
from cockpit.runtime.pty_manager import PTYManager
from cockpit.shared.enums import SessionTargetKind


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

        target_kind = command.context.get("target_kind", SessionTargetKind.LOCAL)
        if isinstance(target_kind, str):
            try:
                target_kind = SessionTargetKind(target_kind)
            except ValueError as exc:
                raise CommandContextError(
                    "target_kind context must be a valid session target kind."
                ) from exc
        if not isinstance(target_kind, SessionTargetKind):
            raise CommandContextError("target_kind context must be a valid session target kind.")
        target_ref = command.context.get("target_ref")
        if target_ref is not None and not isinstance(target_ref, str):
            raise CommandContextError("target_ref context must be a string.")

        session = self._pty_manager.restart_session(
            panel_id,
            cwd,
            target_kind=target_kind,
            target_ref=target_ref,
        )
        if session is None:
            raise CommandContextError("Terminal restart failed.")
        return DispatchResult(
            success=True,
            message=f"Terminal restarted in {session.cwd}",
            data={"panel_id": panel_id, "cwd": session.cwd},
        )


class SearchTerminalHandler:
    """Run a search against the terminal buffer in the active panel."""

    def __call__(self, command: Command) -> DispatchResult:
        panel_id = command.context.get("panel_id", "work-panel")
        if not isinstance(panel_id, str):
            raise CommandContextError("panel_id context must be a string.")
        query = self._resolve_query(command)
        return DispatchResult(
            success=True,
            message=f"Searching terminal for '{query}'.",
            data={
                "result_panel_id": panel_id,
                "result_payload": {
                    "terminal_action": "search",
                    "query": query,
                },
            },
        )

    @staticmethod
    def _resolve_query(command: Command) -> str:
        named_query = command.args.get("query")
        if isinstance(named_query, str) and named_query.strip():
            return named_query.strip()
        argv = command.args.get("argv", [])
        if not isinstance(argv, list):
            raise CommandContextError("A search term is required.")
        query = " ".join(str(token) for token in argv if isinstance(token, str)).strip()
        if not query:
            raise CommandContextError("A search term is required.")
        return query


class NavigateTerminalSearchHandler:
    """Move to the next or previous terminal search result."""

    def __init__(self, *, direction: str) -> None:
        self._direction = direction

    def __call__(self, command: Command) -> DispatchResult:
        panel_id = command.context.get("panel_id", "work-panel")
        if not isinstance(panel_id, str):
            raise CommandContextError("panel_id context must be a string.")
        return DispatchResult(
            success=True,
            message=f"Moved to {self._direction} terminal search result.",
            data={
                "result_panel_id": panel_id,
                "result_payload": {
                    "terminal_action": f"search_{self._direction}",
                },
            },
        )


class ExportTerminalBufferHandler:
    """Export the terminal buffer to a text file."""

    def __call__(self, command: Command) -> DispatchResult:
        panel_id = command.context.get("panel_id", "work-panel")
        if not isinstance(panel_id, str):
            raise CommandContextError("panel_id context must be a string.")
        path = self._resolve_path(command)
        return DispatchResult(
            success=True,
            message=f"Exporting terminal buffer to {path}.",
            data={
                "result_panel_id": panel_id,
                "result_payload": {
                    "terminal_action": "export",
                    "path": path,
                },
            },
        )

    @staticmethod
    def _resolve_path(command: Command) -> str:
        named_path = command.args.get("path")
        if isinstance(named_path, str) and named_path.strip():
            return named_path.strip()
        argv = command.args.get("argv", [])
        if isinstance(argv, list):
            for token in argv:
                if isinstance(token, str) and token.strip():
                    return token.strip()
        return ".cockpit/terminal-buffer.txt"
