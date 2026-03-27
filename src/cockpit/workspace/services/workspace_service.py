"""Workspace service."""

from __future__ import annotations

from hashlib import sha1
from pathlib import Path
from urllib.parse import urlparse

from cockpit.workspace.services.connection_service import ConnectionService
from cockpit.workspace.models.workspace import SessionTarget, Workspace
from cockpit.workspace.repositories import WorkspaceRepository
from cockpit.core.enums import SessionTargetKind


class WorkspaceService:
    """Resolves local workspace metadata and persistence."""

    def __init__(
        self,
        workspace_repository: WorkspaceRepository,
        connection_service: ConnectionService | None = None,
    ) -> None:
        self._workspace_repository = workspace_repository
        self._connection_service = connection_service

    def open_path(self, raw_path: str) -> Workspace:
        target, root_path, workspace_name = self._resolve_workspace_target(raw_path)
        workspace_id = self._workspace_id_for_target(target, root_path)
        workspace = self._workspace_repository.get(workspace_id)
        if workspace is None:
            workspace = Workspace(
                id=workspace_id,
                name=workspace_name,
                root_path=root_path,
                target=target,
                default_layout_id="default",
            )
        else:
            workspace.name = workspace_name
            workspace.root_path = root_path
            workspace.target = target
        self._workspace_repository.save(workspace)
        return workspace

    def get(self, workspace_id: str) -> Workspace | None:
        return self._workspace_repository.get(workspace_id)

    def _resolve_workspace_target(
        self, raw_path: str
    ) -> tuple[SessionTarget, str, str]:
        profile_target = self._resolve_profile_target(raw_path)
        if profile_target is not None:
            return profile_target

        parsed = urlparse(raw_path)
        if parsed.scheme == "ssh":
            if not parsed.netloc:
                raise ValueError(
                    "SSH workspace URIs must include a host, e.g. ssh://user@host/path."
                )
            remote_path = parsed.path or "."
            target = SessionTarget(kind=SessionTargetKind.SSH, ref=parsed.netloc)
            workspace_name = Path(remote_path).name or parsed.netloc
            return target, remote_path, workspace_name

        path = Path(raw_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Workspace path '{path}' does not exist.")
        if not path.is_dir():
            raise NotADirectoryError(f"Workspace path '{path}' is not a directory.")
        target = SessionTarget(kind=SessionTargetKind.LOCAL)
        return target, str(path), path.name or str(path)

    def _resolve_profile_target(
        self, raw_path: str
    ) -> tuple[SessionTarget, str, str] | None:
        if not raw_path.startswith("@"):
            return None
        if self._connection_service is None:
            raise ValueError(
                "Connection profiles are not configured for this workspace."
            )

        alias_expression = raw_path[1:]
        alias, separator, override_path = alias_expression.partition(":")
        if not alias:
            raise ValueError(
                "Connection profile paths must look like '@alias' or '@alias:/path'."
            )

        profile = self._connection_service.get(alias)
        if profile is None:
            raise FileNotFoundError(f"Connection profile '{alias}' is not configured.")

        remote_path = override_path if separator else profile.default_path
        remote_path = remote_path or "."
        target = SessionTarget(kind=SessionTargetKind.SSH, ref=profile.target_ref)
        workspace_name = Path(remote_path).name or alias
        return target, remote_path, workspace_name

    @staticmethod
    def _workspace_id_for_target(target: SessionTarget, root_path: str) -> str:
        key = f"{target.kind.value}:{target.ref or ''}:{root_path}"
        return f"ws_{sha1(key.encode('utf-8')).hexdigest()[:12]}"
