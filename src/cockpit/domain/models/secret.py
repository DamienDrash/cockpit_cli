"""Managed secret metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from cockpit.shared.utils import serialize_contract


@dataclass(slots=True)
class ManagedSecretEntry:
    name: str
    provider: str
    reference: dict[str, object]
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    rotated_at: datetime | None = None
    revision: int = 1

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)
