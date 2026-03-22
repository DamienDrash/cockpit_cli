"""Session service."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from cockpit.domain.models.layout import Layout
from cockpit.domain.models.session import Session
from cockpit.domain.models.workspace import Workspace
from cockpit.infrastructure.persistence.repositories import (
    SessionRepository,
    SnapshotRepository,
)
from cockpit.shared.enums import SessionStatus, SessionTargetKind, SnapshotKind
from cockpit.shared.utils import make_id, utc_now


@dataclass(slots=True)
class SessionOpenState:
    session: Session
    cwd: str
    restored: bool
    created_snapshot: bool = False
    recovery_message: str | None = None
    snapshot_payload: dict[str, object] = field(default_factory=dict)


class SessionService:
    """Creates or restores workspace sessions from persisted state."""

    def __init__(
        self,
        session_repository: SessionRepository,
        snapshot_repository: SnapshotRepository,
    ) -> None:
        self._session_repository = session_repository
        self._snapshot_repository = snapshot_repository

    def open_for_workspace(self, workspace: Workspace, layout: Layout) -> SessionOpenState:
        session = self._session_repository.get_latest_for_workspace(workspace.id)
        if session is None:
            return self._create_session(workspace, layout)
        return self._restore_session(session, workspace)

    def restore_workspace(self, workspace: Workspace) -> SessionOpenState:
        session = self._session_repository.get_latest_for_workspace(workspace.id)
        if session is None:
            msg = f"No saved session exists for workspace '{workspace.name}'."
            raise LookupError(msg)
        return self._restore_session(session, workspace)

    def latest_session(self) -> Session | None:
        return self._session_repository.get_latest()

    def save_resume_snapshot(
        self,
        *,
        session_id: str,
        payload: dict[str, object],
        active_tab_id: str | None = None,
        focused_panel_id: str | None = None,
    ) -> str:
        session = self._session_repository.get(session_id)
        if session is None:
            raise LookupError(f"Session '{session_id}' could not be found.")

        snapshot_ref = self._snapshot_repository.save(
            session_id=session_id,
            snapshot_kind=SnapshotKind.RESUME,
            payload=payload,
            snapshot_ref=session.snapshot_ref,
        )
        session.snapshot_ref = snapshot_ref
        if active_tab_id is not None:
            session.active_tab_id = active_tab_id
        if focused_panel_id is not None:
            session.focused_panel_id = focused_panel_id
        session.updated_at = utc_now()
        self._session_repository.save(session)
        return snapshot_ref

    def _create_session(self, workspace: Workspace, layout: Layout) -> SessionOpenState:
        now = utc_now()
        active_tab_id = layout.focus_path[0] if layout.focus_path else None
        focused_panel_id = layout.focus_path[-1] if layout.focus_path else None
        session = Session(
            id=make_id("sess"),
            workspace_id=workspace.id,
            name=f"{workspace.name} workspace",
            status=SessionStatus.ACTIVE,
            active_tab_id=active_tab_id,
            focused_panel_id=focused_panel_id,
            snapshot_ref=None,
            created_at=now,
            updated_at=now,
            last_opened_at=now,
        )
        self._session_repository.save(session)

        snapshot_payload = {
            "cwd": workspace.root_path,
            "browser_path": workspace.root_path,
            "selected_path": workspace.root_path,
            "active_tab_id": active_tab_id,
            "focused_panel_id": focused_panel_id,
        }
        snapshot_ref = self._snapshot_repository.save(
            session_id=session.id,
            snapshot_kind=SnapshotKind.RESUME,
            payload=snapshot_payload,
        )
        session.snapshot_ref = snapshot_ref
        session.updated_at = utc_now()
        self._session_repository.save(session)
        return SessionOpenState(
            session=session,
            cwd=workspace.root_path,
            restored=False,
            created_snapshot=True,
            snapshot_payload=snapshot_payload,
        )

    def _restore_session(self, session: Session, workspace: Workspace) -> SessionOpenState:
        cwd = workspace.root_path
        recovery_message: str | None = None
        snapshot_payload: dict[str, object] = {}

        if session.snapshot_ref:
            decoded = self._snapshot_repository.load(session.snapshot_ref)
            if decoded.success and decoded.envelope is not None:
                snapshot_payload = decoded.envelope.payload
                requested_cwd = snapshot_payload.get("cwd")
                if isinstance(requested_cwd, str):
                    if workspace.target.kind is SessionTargetKind.SSH:
                        cwd = requested_cwd
                    else:
                        requested_path = Path(requested_cwd).expanduser()
                        if requested_path.exists() and requested_path.is_dir():
                            cwd = str(requested_path.resolve())
                        else:
                            recovery_message = (
                                f"Saved cwd '{requested_cwd}' is unavailable. "
                                "Falling back to workspace root."
                            )
            else:
                recovery_message = decoded.error or "Saved snapshot could not be restored."

        session.last_opened_at = utc_now()
        session.updated_at = utc_now()
        self._session_repository.save(session)
        return SessionOpenState(
            session=session,
            cwd=cwd,
            restored=True,
            recovery_message=recovery_message,
            snapshot_payload=snapshot_payload,
        )
