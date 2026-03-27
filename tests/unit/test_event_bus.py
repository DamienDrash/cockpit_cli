import unittest

from cockpit.core.dispatch.event_bus import EventBus, PanelEventScope
from cockpit.core.events.base import BaseEvent
from cockpit.core.events.runtime import StatusMessagePublished


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

    def test_ring_buffer_caps_published_history(self) -> None:
        bus = EventBus(max_published=5)
        for i in range(10):
            bus.publish(StatusMessagePublished(message=f"msg {i}"))

        self.assertEqual(len(bus.published), 5)
        self.assertEqual(bus.published[0].message, "msg 5")
        self.assertEqual(bus.published[-1].message, "msg 9")

    def test_panel_event_scope_filters_by_panel_id(self) -> None:
        bus = EventBus()
        scope_a = PanelEventScope(bus, "panel-a")
        scope_b = PanelEventScope(bus, "panel-b")

        seen_a: list[str] = []
        seen_b: list[str] = []

        from cockpit.core.events.runtime import PanelMounted

        scope_a.subscribe(PanelMounted, lambda e: seen_a.append(e.panel_id))
        scope_b.subscribe(PanelMounted, lambda e: seen_b.append(e.panel_id))

        # Global event for this purpose: StatusMessagePublished (no panel_id)
        # We need to subscribe scopes to it too if we want to test global delivery
        scope_a.subscribe(StatusMessagePublished, lambda e: seen_a.append("global"))
        scope_b.subscribe(StatusMessagePublished, lambda e: seen_b.append("global"))

        bus.publish(StatusMessagePublished(message="global"))

        # Targeted event -> only panel-a sees it
        bus.publish(PanelMounted(panel_id="panel-a", panel_type="work"))
        bus.publish(PanelMounted(panel_id="panel-b", panel_type="work"))

        self.assertEqual(seen_a, ["global", "panel-a"])
        self.assertEqual(seen_b, ["global", "panel-b"])


if __name__ == "__main__":
    unittest.main()
