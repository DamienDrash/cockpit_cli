"""Route shell launches to local or SSH adapters."""

from __future__ import annotations

from cockpit.infrastructure.shell.base import ShellAdapter, ShellLaunchConfig
from cockpit.shared.enums import SessionTargetKind


class ShellAdapterRouter:
    """Dispatch build requests to the correct target-specific shell adapter."""

    def __init__(self, *, local_adapter: ShellAdapter, ssh_adapter: ShellAdapter) -> None:
        self._local_adapter = local_adapter
        self._ssh_adapter = ssh_adapter

    def build_launch_config(
        self,
        cwd: str,
        *,
        command: list[str] | tuple[str, ...] | None = None,
        target_kind: SessionTargetKind = SessionTargetKind.LOCAL,
        target_ref: str | None = None,
    ) -> ShellLaunchConfig:
        if target_kind is SessionTargetKind.SSH:
            return self._ssh_adapter.build_launch_config(
                cwd,
                command=command,
                target_kind=target_kind,
                target_ref=target_ref,
            )
        return self._local_adapter.build_launch_config(
            cwd,
            command=command,
            target_kind=target_kind,
            target_ref=target_ref,
        )
