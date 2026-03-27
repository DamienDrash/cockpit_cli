"""Local shell launch adapter."""

from __future__ import annotations

import os
from pathlib import Path

from cockpit.infrastructure.shell.base import ShellLaunchConfig
from cockpit.core.enums import SessionTargetKind


class LocalShellAdapter:
    """Build launch configuration for local shell sessions."""

    def __init__(self, shell: str | None = None) -> None:
        self._shell = shell or os.environ.get("SHELL") or "/bin/bash"

    def build_launch_config(
        self,
        cwd: str,
        *,
        command: list[str] | tuple[str, ...] | None = None,
        target_kind: SessionTargetKind = SessionTargetKind.LOCAL,
        target_ref: str | None = None,
    ) -> ShellLaunchConfig:
        if target_kind is not SessionTargetKind.LOCAL:
            raise ValueError(
                f"LocalShellAdapter cannot launch target kind '{target_kind.value}'."
            )
        if target_ref is not None:
            raise ValueError(
                "LocalShellAdapter does not accept a remote target reference."
            )
        path = Path(cwd).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Shell cwd '{path}' does not exist.")
        if not path.is_dir():
            raise NotADirectoryError(f"Shell cwd '{path}' is not a directory.")

        launch_command = tuple(command or self._default_command())
        env = os.environ.copy()
        env.setdefault("TERM", "xterm-256color")
        env.setdefault("COLORTERM", "truecolor")
        env.setdefault("PS1", "cockpit$ ")
        return ShellLaunchConfig(
            command=launch_command,
            cwd=str(path),
            env=env,
        )

    def _default_command(self) -> list[str]:
        shell_path = Path(self._shell)
        name = shell_path.name
        if name == "bash":
            return [self._shell, "--noprofile", "--norc", "-i"]
        if name == "zsh":
            return [self._shell, "-f", "-i"]
        return [self._shell, "-i"]
