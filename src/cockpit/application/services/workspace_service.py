"""Workspace service."""

from __future__ import annotations

from hashlib import sha1
from pathlib import Path

from cockpit.domain.models.workspace import SessionTarget, Workspace
from cockpit.infrastructure.persistence.repositories import WorkspaceRepository
from cockpit.shared.enums import SessionTargetKind


class WorkspaceService:
    """Resolves local workspace metadata and persistence."""

    def __init__(self, workspace_repository: WorkspaceRepository) -> None:
        self._workspace_repository = workspace_repository

    def open_path(self, raw_path: str) -> Workspace:
        path = Path(raw_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Workspace path '{path}' does not exist.")
        if not path.is_dir():
            raise NotADirectoryError(f"Workspace path '{path}' is not a directory.")

        workspace_id = self._workspace_id_for_path(path)
        workspace = self._workspace_repository.get(workspace_id)
        if workspace is None:
            workspace = Workspace(
                id=workspace_id,
                name=path.name or str(path),
                root_path=str(path),
                target=SessionTarget(kind=SessionTargetKind.LOCAL),
                default_layout_id="default",
            )
        else:
            workspace.root_path = str(path)
        self._workspace_repository.save(workspace)
        return workspace

    def get(self, workspace_id: str) -> Workspace | None:
        return self._workspace_repository.get(workspace_id)

    @staticmethod
    def _workspace_id_for_path(path: Path) -> str:
        return f"ws_{sha1(str(path).encode('utf-8')).hexdigest()[:12]}"
