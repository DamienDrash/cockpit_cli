"""Runtime/UI events."""

from __future__ import annotations

from dataclasses import dataclass

from cockpit.domain.events.base import RuntimeEvent
from cockpit.shared.enums import StatusLevel


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
    snapshot: dict[str, object]


@dataclass(slots=True, kw_only=True)
class PTYStarted(RuntimeEvent):
    panel_id: str
    cwd: str
    pid: int | None = None


@dataclass(slots=True, kw_only=True)
class PTYStartupFailed(RuntimeEvent):
    panel_id: str
    cwd: str
    reason: str


@dataclass(slots=True, kw_only=True)
class ProcessOutputReceived(RuntimeEvent):
    panel_id: str
    chunk: str


@dataclass(slots=True, kw_only=True)
class TerminalExited(RuntimeEvent):
    panel_id: str
    exit_code: int


@dataclass(slots=True, kw_only=True)
class StatusMessagePublished(RuntimeEvent):
    message: str
    level: StatusLevel = StatusLevel.INFO
