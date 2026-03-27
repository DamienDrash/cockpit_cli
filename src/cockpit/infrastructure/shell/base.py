"""Shared shell adapter contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from cockpit.core.enums import SessionTargetKind


@dataclass(slots=True, frozen=True)
class ShellLaunchConfig:
    command: tuple[str, ...]
    cwd: str
    env: dict[str, str]


class ShellAdapter(Protocol):
    """Build launch configurations for local or remote shell sessions."""

    def build_launch_config(
        self,
        cwd: str,
        *,
        command: list[str] | tuple[str, ...] | None = None,
        target_kind: SessionTargetKind = SessionTargetKind.LOCAL,
        target_ref: str | None = None,
    ) -> ShellLaunchConfig: ...
