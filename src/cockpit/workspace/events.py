"""Domain-level events."""

from __future__ import annotations

from dataclasses import dataclass

from cockpit.core.events.base import DomainEvent
from cockpit.core.enums import CommandSource, SessionTargetKind, SnapshotKind


@dataclass(slots=True, kw_only=True)
class WorkspaceOpened(DomainEvent):
    workspace_id: str
    name: str
    root_path: str
    target_kind: SessionTargetKind


@dataclass(slots=True, kw_only=True)
class SessionCreated(DomainEvent):
    session_id: str
    workspace_id: str


@dataclass(slots=True, kw_only=True)
class SessionRestored(DomainEvent):
    session_id: str
    workspace_id: str


@dataclass(slots=True, kw_only=True)
class LayoutApplied(DomainEvent):
    layout_id: str
    session_id: str | None = None


@dataclass(slots=True, kw_only=True)
class CommandExecuted(DomainEvent):
    command_id: str
    name: str
    source: CommandSource
    success: bool
    message: str | None = None


@dataclass(slots=True, kw_only=True)
class SnapshotSaved(DomainEvent):
    session_id: str
    snapshot_kind: SnapshotKind
