"""Typed in-process event bus."""

from __future__ import annotations

from collections import deque, defaultdict
from collections.abc import Callable
from threading import RLock
from typing import TypeVar, Protocol, runtime_checkable

from cockpit.core.events.base import BaseEvent

EventT = TypeVar("EventT", bound=BaseEvent)
EventHandler = Callable[[BaseEvent], None]


@runtime_checkable
class ScopedEvent(Protocol):
    """Protocol for events that carry a panel identity."""

    panel_id: str | None


class EventBus:
    """Publish/subscribe event bus for in-process events."""

    def __init__(self, max_published: int = 10000) -> None:
        self._subscribers: dict[type[BaseEvent], list[EventHandler]] = defaultdict(list)
        self._published: deque[BaseEvent] = deque(maxlen=max_published)
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


class PanelEventScope:
    """Restricts event broadcasts to a specific panel identity.

    This wrapper around EventBus ensures that events carrying a panel_id
    are only delivered if they match the scope's panel_id. Events without
    a panel_id (global events) are always delivered.
    """

    def __init__(self, bus: EventBus, panel_id: str) -> None:
        self._bus = bus
        self._panel_id = panel_id

    def subscribe(self, event_type: type[EventT], handler: EventHandler) -> None:
        """Subscribe to an event type within this panel scope."""

        def _filtered_handler(event: BaseEvent) -> None:
            # Check if event has a panel_id attribute (either via protocol or getattr)
            event_panel_id = getattr(event, "panel_id", None)

            # Deliver if:
            # 1. Event has no panel_id (global event)
            # 2. Event panel_id matches this scope's panel_id
            if event_panel_id is None or event_panel_id == self._panel_id:
                handler(event)

        self._bus.subscribe(event_type, _filtered_handler)
