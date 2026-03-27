"""Workspace context wiring."""

from __future__ import annotations

from typing import Any

from cockpit.core.dispatch.command_dispatcher import CommandDispatcher
from cockpit.core.dispatch.event_bus import EventBus
from cockpit.workspace.handlers.layout_handlers import (
    AdjustActiveLayoutRatioHandler,
    ApplyDefaultLayoutHandler,
    FocusNextPanelHandler,
    ToggleActiveLayoutOrientationHandler,
)
from cockpit.workspace.handlers.session_handlers import RestoreSessionHandler
from cockpit.workspace.handlers.tab_handlers import FocusTabHandler
from cockpit.workspace.handlers.workspace_handlers import (
    OpenWorkspaceHandler,
    ReopenLastWorkspaceHandler,
)
from cockpit.workspace.services.connection_service import ConnectionService
from cockpit.workspace.services.layout_service import LayoutService
from cockpit.workspace.services.navigation_controller import NavigationController
from cockpit.workspace.services.session_service import SessionService
from cockpit.workspace.services.workspace_service import WorkspaceService
from cockpit.workspace.config_loader import ConfigLoader
from cockpit.workspace.repositories import (
    LayoutRepository,
    SessionRepository,
    SnapshotRepository,
    WorkspaceRepository,
)
from cockpit.core.persistence.sqlite_store import SQLiteStore


def wire_workspace(
    store: SQLiteStore,
    config_loader: ConfigLoader,
    event_bus: EventBus,
    command_dispatcher: CommandDispatcher,
) -> dict[str, Any]:
    """Wire workspace, session, and layout components."""
    workspace_repository = WorkspaceRepository(store)
    layout_repository = LayoutRepository(store)
    session_repository = SessionRepository(store)
    snapshot_repository = SnapshotRepository(store)

    connection_service = ConnectionService(config_loader)
    workspace_service = WorkspaceService(
        workspace_repository,
        connection_service=connection_service,
    )
    layout_service = LayoutService(layout_repository, config_loader)
    session_service = SessionService(session_repository, snapshot_repository)

    navigation_controller = NavigationController(
        event_bus=event_bus,
        workspace_service=workspace_service,
        layout_service=layout_service,
        session_service=session_service,
    )

    # Register handlers
    command_dispatcher.register(
        "workspace.open",
        OpenWorkspaceHandler(
            event_bus,
            navigation_controller=navigation_controller,
        ),
    )
    command_dispatcher.register(
        "workspace.reopen_last",
        ReopenLastWorkspaceHandler(
            event_bus,
            navigation_controller=navigation_controller,
        ),
    )
    command_dispatcher.register(
        "session.restore",
        RestoreSessionHandler(
            event_bus,
            navigation_controller=navigation_controller,
        ),
    )
    command_dispatcher.register("tab.focus", FocusTabHandler())
    command_dispatcher.register(
        "layout.apply_default", ApplyDefaultLayoutHandler(event_bus)
    )
    command_dispatcher.register(
        "layout.toggle_orientation",
        ToggleActiveLayoutOrientationHandler(),
    )
    command_dispatcher.register(
        "layout.grow",
        AdjustActiveLayoutRatioHandler(delta=0.1),
    )
    command_dispatcher.register(
        "layout.shrink",
        AdjustActiveLayoutRatioHandler(delta=-0.1),
    )
    command_dispatcher.register("panel.focus_next", FocusNextPanelHandler())

    return {
        "workspace_service": workspace_service,
        "layout_service": layout_service,
        "session_service": session_service,
        "navigation_controller": navigation_controller,
    }
