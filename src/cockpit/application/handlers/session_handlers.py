"""Session-related handlers."""

from __future__ import annotations

from collections.abc import Callable

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.application.handlers.base import CommandContextError, DispatchResult
from cockpit.application.services.navigation_controller import NavigationController
from cockpit.domain.commands.command import Command
from cockpit.domain.events.domain_events import SessionRestored
from cockpit.domain.models.layout import Layout, PanelRef, SplitNode
from cockpit.domain.models.session import Session

SessionResolver = Callable[[Command], Session | None]


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
    return {
        "workspace_name": workspace.name,
        "workspace_id": workspace.id,
        "workspace_root": workspace_root,
        "session_id": session.id,
        "layout_id": layout.id,
        "tabs": _layout_tabs(layout),
        "active_tab_id": session.active_tab_id or "work",
        "focused_panel_id": session.focused_panel_id,
        "cwd": getattr(state, "cwd"),
        "browser_path": str(browser_path),
        "selected_path": str(selected_path),
        "snapshot": dict(snapshot),
        "restored": getattr(state, "restored"),
        "recovery_message": getattr(state, "recovery_message"),
    }


def _layout_tabs(layout: Layout) -> list[dict[str, str]]:
    tabs: list[dict[str, str]] = []
    for tab in layout.tabs:
        panel = _first_panel_ref(tab.root_split)
        tabs.append(
            {
                "id": tab.id,
                "name": tab.name,
                "panel_id": panel.panel_id if panel is not None else f"{tab.id}-panel",
                "panel_type": panel.panel_type if panel is not None else tab.id,
            }
        )
    return tabs


def _first_panel_ref(node: SplitNode) -> PanelRef | None:
    for child in node.children:
        if isinstance(child, PanelRef):
            return child
        if isinstance(child, SplitNode):
            panel = _first_panel_ref(child)
            if panel is not None:
                return panel
    return None


class RestoreSessionHandler:
    """Handle session restore requests."""

    def __init__(
        self,
        event_bus: EventBus,
        resolver: SessionResolver | None = None,
        navigation_controller: NavigationController | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._resolver = resolver
        self._navigation_controller = navigation_controller

    def __call__(self, command: Command) -> DispatchResult:
        session = self._resolver(command) if self._resolver else None
        if session is not None:
            self._event_bus.publish(
                SessionRestored(
                    session_id=session.id,
                    workspace_id=session.workspace_id,
                )
            )
            return DispatchResult(
                success=True,
                message=f"Session restored: {session.name}",
                data=session.to_dict(),
            )

        if self._navigation_controller is not None:
            workspace_id = command.context.get("workspace_id")
            if workspace_id is not None and not isinstance(workspace_id, str):
                raise CommandContextError("workspace_id context must be a string.")
            try:
                state = self._navigation_controller.restore_session(workspace_id)
            except LookupError as exc:
                raise CommandContextError(str(exc)) from exc
            return DispatchResult(
                success=True,
                message=f"Restored session: {state.session.name}",
                data=_navigation_result_data(state),
            )

        return DispatchResult(success=True, message="Session restore requested.")
