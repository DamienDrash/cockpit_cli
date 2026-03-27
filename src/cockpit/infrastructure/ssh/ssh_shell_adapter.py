"""SSH shell launch adapter."""

from __future__ import annotations

import os
import shlex

from cockpit.infrastructure.shell.base import ShellLaunchConfig
from cockpit.core.enums import SessionTargetKind


class SSHShellAdapter:
    """Build launch configuration for SSH-backed PTY sessions."""

    def __init__(self, ssh_binary: str = "ssh") -> None:
        self._ssh_binary = ssh_binary

    def build_launch_config(
        self,
        cwd: str,
        *,
        command: list[str] | tuple[str, ...] | None = None,
        target_kind: SessionTargetKind = SessionTargetKind.SSH,
        target_ref: str | None = None,
    ) -> ShellLaunchConfig:
        if target_kind is not SessionTargetKind.SSH:
            raise ValueError(
                f"SSHShellAdapter cannot launch target kind '{target_kind.value}'."
            )
        if not target_ref:
            raise ValueError("An SSH target reference is required.")

        remote_command = self._remote_command(cwd, command=command)
        env = os.environ.copy()
        env.setdefault("TERM", "xterm-256color")
        env.setdefault("COLORTERM", "truecolor")
        return ShellLaunchConfig(
            command=(self._ssh_binary, "-tt", target_ref, remote_command),
            cwd=os.getcwd(),
            env=env,
        )

    @staticmethod
    def _remote_command(
        cwd: str,
        *,
        command: list[str] | tuple[str, ...] | None = None,
    ) -> str:
        if command:
            remote_exec = shlex.join([str(part) for part in command])
        else:
            remote_exec = 'exec "${SHELL:-/bin/bash}" -li'
        return f"cd {shlex.quote(cwd)} >/dev/null 2>&1 || exit 1; {remote_exec}"
