"""Runtime/UI events."""

from __future__ import annotations

from dataclasses import dataclass

from cockpit.core.events.base import RuntimeEvent
from cockpit.core.enums import SessionTargetKind, StatusLevel


@dataclass(slots=True, kw_only=True)
class PanelMounted(RuntimeEvent):
    panel_id: str
    panel_type: str


@dataclass(slots=True, kw_only=True)
class PanelFocused(RuntimeEvent):
    panel_id: str


@dataclass(slots=True, kw_only=True)
class PanelStateChanged(RuntimeEvent):
    panel_id: str
    panel_type: str
    snapshot: dict[str, object]
    config: dict[str, object]


@dataclass(slots=True, kw_only=True)
class PTYStarted(RuntimeEvent):
    panel_id: str
    cwd: str
    pid: int | None = None
    command: tuple[str, ...] = ()
    target_kind: SessionTargetKind = SessionTargetKind.LOCAL
    target_ref: str | None = None


@dataclass(slots=True, kw_only=True)
class PTYStartupFailed(RuntimeEvent):
    panel_id: str
    cwd: str
    reason: str
    command: tuple[str, ...] = ()
    target_kind: SessionTargetKind = SessionTargetKind.LOCAL
    target_ref: str | None = None


@dataclass(slots=True, kw_only=True)
class ProcessOutputReceived(RuntimeEvent):
    panel_id: str
    chunk: str


@dataclass(slots=True, kw_only=True)
class TerminalExited(RuntimeEvent):
    panel_id: str
    exit_code: int
    cwd: str = ""
    command: tuple[str, ...] = ()
    expected: bool = False
    target_kind: SessionTargetKind = SessionTargetKind.LOCAL
    target_ref: str | None = None


@dataclass(slots=True, kw_only=True)
class StatusMessagePublished(RuntimeEvent):
    message: str
    level: StatusLevel = StatusLevel.INFO
