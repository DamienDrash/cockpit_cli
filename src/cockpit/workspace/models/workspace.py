"""Workspace and target models."""

from __future__ import annotations

from dataclasses import dataclass, field

from cockpit.core.enums import SessionTargetKind
from cockpit.core.utils import serialize_contract


@dataclass(slots=True)
class SessionTarget:
    kind: SessionTargetKind = SessionTargetKind.LOCAL
    ref: str | None = None

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class Workspace:
    id: str
    name: str
    root_path: str
    target: SessionTarget = field(default_factory=SessionTarget)
    default_layout_id: str | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)
