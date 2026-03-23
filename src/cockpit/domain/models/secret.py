"""Managed secret metadata."""

from __future__ import annotations

from dataclasses import dataclass, field

from cockpit.shared.utils import serialize_contract


@dataclass(slots=True)
class ManagedSecretEntry:
    name: str
    provider: str
    reference: dict[str, object]
    description: str | None = None
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)
