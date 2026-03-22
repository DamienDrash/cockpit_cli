import unittest

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.domain.events.base import BaseEvent
from cockpit.domain.events.runtime_events import StatusMessagePublished


class EventBusTests(unittest.TestCase):
    def test_dispatches_specific_and_base_subscribers(self) -> None:
        bus = EventBus()
        seen: list[str] = []

        def handle_base(_event: BaseEvent) -> None:
            seen.append("base")

        def handle_specific(_event: BaseEvent) -> None:
            seen.append("specific")

        bus.subscribe(BaseEvent, handle_base)
        bus.subscribe(StatusMessagePublished, handle_specific)

        bus.publish(StatusMessagePublished(message="ready"))

        self.assertEqual(seen, ["specific", "base"])
        self.assertEqual(len(bus.published), 1)


if __name__ == "__main__":
    unittest.main()

