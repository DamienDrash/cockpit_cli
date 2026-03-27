"""Navigation orchestration service."""

from __future__ import annotations

from dataclasses import dataclass, field

from cockpit.core.dispatch.event_bus import EventBus
from cockpit.workspace.services.layout_service import LayoutService
from cockpit.workspace.services.session_service import (
    SessionOpenState,
    SessionService,
)
from cockpit.workspace.services.workspace_service import WorkspaceService
from cockpit.workspace.events import (
    LayoutApplied,
    SessionCreated,
    SessionRestored,
    SnapshotSaved,
    WorkspaceOpened,
)
from cockpit.core.events.runtime import StatusMessagePublished
from cockpit.workspace.models.layout import Layout
from cockpit.workspace.models.session import Session
from cockpit.workspace.models.workspace import Workspace
from cockpit.core.enums import SnapshotKind, StatusLevel


@dataclass(slots=True)
class NavigationState:
    workspace: Workspace
    layout: Layout
    session: Session
    cwd: str
    restored: bool
    snapshot_payload: dict[str, object] = field(default_factory=dict)
    recovery_message: str | None = None


class NavigationController:
    """Coordinates workspace open and session resume flows."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        workspace_service: WorkspaceService,
        layout_service: LayoutService,
        session_service: SessionService,
    ) -> None:
        self._event_bus = event_bus
        self._workspace_service = workspace_service
        self._layout_service = layout_service
        self._session_service = session_service

    def open_workspace(self, raw_path: str) -> NavigationState:
        workspace = self._workspace_service.open_path(raw_path)
        layout = self._layout_service.resolve_for_workspace(workspace)
        session_state = self._session_service.open_for_workspace(workspace, layout)
        return self._publish_open_state(workspace, layout, session_state)

    def reopen_last_workspace(self) -> NavigationState:
        session = self._session_service.latest_session()
        if session is None:
            raise LookupError("No workspace session is available to reopen.")
        workspace = self._workspace_service.get(session.workspace_id)
        if workspace is None:
            raise LookupError(
                f"Workspace '{session.workspace_id}' referenced by the last session is missing."
            )
        layout = self._layout_service.resolve_for_workspace(workspace)
        session_state = self._session_service.restore_workspace(workspace)
        return self._publish_open_state(workspace, layout, session_state)

    def restore_session(self, workspace_id: str | None = None) -> NavigationState:
        if workspace_id is None:
            latest_session = self._session_service.latest_session()
            if latest_session is None:
                raise LookupError("No saved session is available to restore.")
            workspace_id = latest_session.workspace_id

        workspace = self._workspace_service.get(workspace_id)
        if workspace is None:
            raise LookupError(f"Workspace '{workspace_id}' could not be found.")

        layout = self._layout_service.resolve_for_workspace(workspace)
        session_state = self._session_service.restore_workspace(workspace)
        return self._publish_open_state(workspace, layout, session_state)

    def _publish_open_state(
        self,
        workspace: Workspace,
        layout: Layout,
        session_state: SessionOpenState,
    ) -> NavigationState:
        session = session_state.session
        self._event_bus.publish(
            WorkspaceOpened(
                workspace_id=workspace.id,
                name=workspace.name,
                root_path=workspace.root_path,
                target_kind=workspace.target.kind,
            )
        )
        if session_state.restored:
            self._event_bus.publish(
                SessionRestored(
                    session_id=session.id,
                    workspace_id=workspace.id,
                )
            )
        else:
            self._event_bus.publish(
                SessionCreated(
                    session_id=session.id,
                    workspace_id=workspace.id,
                )
            )
            if session_state.created_snapshot:
                self._event_bus.publish(
                    SnapshotSaved(
                        session_id=session.id,
                        snapshot_kind=SnapshotKind.RESUME,
                    )
                )
        self._event_bus.publish(
            LayoutApplied(
                layout_id=layout.id,
                session_id=session.id,
            )
        )

        if session_state.recovery_message:
            self._event_bus.publish(
                StatusMessagePublished(
                    message=session_state.recovery_message,
                    level=StatusLevel.WARNING,
                )
            )

        return NavigationState(
            workspace=workspace,
            layout=layout,
            session=session,
            cwd=session_state.cwd,
            restored=session_state.restored,
            snapshot_payload=session_state.snapshot_payload,
            recovery_message=session_state.recovery_message,
        )
