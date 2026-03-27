"""Base event models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from cockpit.core.enums import EventCategory
from cockpit.core.utils import make_id, serialize_contract, utc_now


@dataclass(slots=True, kw_only=True)
class BaseEvent:
    event_id: str = field(default_factory=lambda: make_id("evt"))
    occurred_at: datetime = field(default_factory=utc_now)

    @property
    def category(self) -> EventCategory:
        raise NotImplementedError

    def to_dict(self) -> dict[str, object]:
        payload = serialize_contract(self)
        payload["category"] = self.category.value
        return payload


@dataclass(slots=True, kw_only=True)
class DomainEvent(BaseEvent):
    @property
    def category(self) -> EventCategory:
        return EventCategory.DOMAIN


@dataclass(slots=True, kw_only=True)
class RuntimeEvent(BaseEvent):
    @property
    def category(self) -> EventCategory:
        return EventCategory.RUNTIME
