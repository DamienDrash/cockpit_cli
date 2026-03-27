"""Command object."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from cockpit.core.enums import CommandSource
from cockpit.core.utils import serialize_contract, utc_now


@dataclass(slots=True)
class Command:
    id: str
    source: CommandSource
    name: str
    args: dict[str, object] = field(default_factory=dict)
    context: dict[str, object] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class CommandHistoryEntry:
    command_id: str
    name: str
    source: CommandSource
    args: dict[str, object] = field(default_factory=dict)
    context: dict[str, object] = field(default_factory=dict)
    success: bool | None = None
    message: str | None = None
    recorded_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class CommandAuditEntry:
    command_id: str
    action: str
    workspace_id: str | None = None
    session_id: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    recorded_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)
