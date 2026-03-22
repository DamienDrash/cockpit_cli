"""Typed in-process event bus."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from threading import RLock
from typing import TypeVar

from cockpit.domain.events.base import BaseEvent

EventT = TypeVar("EventT", bound=BaseEvent)
EventHandler = Callable[[BaseEvent], None]


class EventBus:
    """Publish/subscribe event bus for in-process events."""

    def __init__(self) -> None:
        self._subscribers: dict[type[BaseEvent], list[EventHandler]] = defaultdict(list)
        self._published: list[BaseEvent] = []
        self._lock = RLock()

    @property
    def published(self) -> tuple[BaseEvent, ...]:
        with self._lock:
            return tuple(self._published)

    def subscribe(self, event_type: type[EventT], handler: EventHandler) -> None:
        with self._lock:
            self._subscribers[event_type].append(handler)

    def publish(self, event: BaseEvent) -> None:
        with self._lock:
            self._published.append(event)
            subscribers = {
                event_type: tuple(handlers)
                for event_type, handlers in self._subscribers.items()
            }
        seen: set[int] = set()
        for event_type in type(event).mro():
            if not issubclass(event_type, BaseEvent):
                continue
            for handler in subscribers.get(event_type, ()):
                marker = id(handler)
                if marker in seen:
                    continue
                seen.add(marker)
                handler(event)
