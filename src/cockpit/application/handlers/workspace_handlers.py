"""Workspace-related handlers."""

from __future__ import annotations

from collections.abc import Callable

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.application.handlers.base import CommandContextError, DispatchResult
from cockpit.application.handlers.layout_payload import layout_tabs_payload
from cockpit.application.services.navigation_controller import NavigationController
from cockpit.domain.commands.command import Command
from cockpit.domain.events.domain_events import WorkspaceOpened
from cockpit.domain.models.workspace import Workspace

WorkspaceResolver = Callable[[Command], Workspace | None]
LastWorkspaceResolver = Callable[[], Workspace | None]


def _navigation_result_data(state: object) -> dict[str, object]:
    snapshot = getattr(state, "snapshot_payload", {})
    workspace = getattr(state, "workspace")
    session = getattr(state, "session")
    layout = getattr(state, "layout")
    workspace_root = workspace.root_path
    browser_path = snapshot.get(
        "browser_path",
        snapshot.get("selected_path", workspace_root),
    )
    selected_path = snapshot.get("selected_path", workspace_root)
    snapshot_tabs = snapshot.get("tabs")
    return {
        "workspace_name": workspace.name,
        "workspace_id": workspace.id,
        "workspace_root": workspace_root,
        "target_kind": workspace.target.kind.value,
        "target_ref": workspace.target.ref,
        "session_id": session.id,
        "layout_id": layout.id,
        "tabs": (
            snapshot_tabs
            if isinstance(snapshot_tabs, list)
            else layout_tabs_payload(layout)
        ),
        "active_tab_id": session.active_tab_id or "work",
        "focused_panel_id": session.focused_panel_id,
        "cwd": getattr(state, "cwd"),
        "browser_path": str(browser_path),
        "selected_path": str(selected_path),
        "snapshot": dict(snapshot),
        "restored": getattr(state, "restored"),
        "recovery_message": getattr(state, "recovery_message"),
    }


class OpenWorkspaceHandler:
    """Handle workspace open requests."""

    def __init__(
        self,
        event_bus: EventBus,
        opener: WorkspaceResolver | None = None,
        navigation_controller: NavigationController | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._opener = opener
        self._navigation_controller = navigation_controller

    def __call__(self, command: Command) -> DispatchResult:
        workspace = self._opener(command) if self._opener else None
        if workspace is not None:
            self._event_bus.publish(
                WorkspaceOpened(
                    workspace_id=workspace.id,
                    name=workspace.name,
                    root_path=workspace.root_path,
                    target_kind=workspace.target.kind,
                )
            )
            return DispatchResult(
                success=True,
                message=f"Workspace opened: {workspace.name}",
                data=workspace.to_dict(),
            )

        if self._navigation_controller is None:
            argv = command.args.get("argv", [])
            path = argv[0] if isinstance(argv, list) and argv else "."
            return DispatchResult(
                success=True,
                message=f"Workspace open requested for: {path}",
                data={"path": path},
            )

        argv = command.args.get("argv", [])
        path = argv[0] if isinstance(argv, list) and argv else "."
        if not isinstance(path, str):
            raise CommandContextError("Workspace path must be a string.")
        try:
            state = self._navigation_controller.open_workspace(path)
        except (FileNotFoundError, NotADirectoryError, LookupError, ValueError) as exc:
            raise CommandContextError(str(exc)) from exc
        return DispatchResult(
            success=True,
            message=f"Workspace ready: {state.workspace.name}",
            data=_navigation_result_data(state),
        )


class ReopenLastWorkspaceHandler:
    """Handle last-workspace reopen requests."""

    def __init__(
        self,
        event_bus: EventBus,
        resolver: LastWorkspaceResolver | None = None,
        navigation_controller: NavigationController | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._resolver = resolver
        self._navigation_controller = navigation_controller

    def __call__(self, _command: Command) -> DispatchResult:
        workspace = self._resolver() if self._resolver else None
        if workspace is None:
            if self._navigation_controller is None:
                return DispatchResult(
                    success=True,
                    message="Reopen last workspace requested.",
                )
            try:
                state = self._navigation_controller.reopen_last_workspace()
            except LookupError as exc:
                raise CommandContextError(str(exc)) from exc
            return DispatchResult(
                success=True,
                message=f"Reopened workspace: {state.workspace.name}",
                data=_navigation_result_data(state),
            )

        self._event_bus.publish(
            WorkspaceOpened(
                workspace_id=workspace.id,
                name=workspace.name,
                root_path=workspace.root_path,
                target_kind=workspace.target.kind,
            )
        )
        return DispatchResult(
            success=True,
            message=f"Reopened workspace: {workspace.name}",
            data=workspace.to_dict(),
        )
