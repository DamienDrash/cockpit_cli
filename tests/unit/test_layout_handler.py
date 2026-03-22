import unittest

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.application.handlers.layout_handlers import ApplyDefaultLayoutHandler
from cockpit.domain.commands.command import Command
from cockpit.domain.events.domain_events import LayoutApplied
from cockpit.shared.enums import CommandSource


class ApplyDefaultLayoutHandlerTests(unittest.TestCase):
    def test_resets_to_first_available_tab_and_publishes_event(self) -> None:
        event_bus = EventBus()
        handler = ApplyDefaultLayoutHandler(event_bus)

        result = handler(
            Command(
                id="cmd_1",
                source=CommandSource.SLASH,
                name="layout.apply_default",
                context={
                    "layout_id": "default",
                    "session_id": "sess_1",
                    "available_tab_ids": ["work", "git", "logs"],
                },
            )
        )

        self.assertTrue(result.success)
        self.assertEqual(result.data["active_tab_id"], "work")
        layout_events = [
            event for event in event_bus.published if isinstance(event, LayoutApplied)
        ]
        self.assertEqual(len(layout_events), 1)
        self.assertEqual(layout_events[0].layout_id, "default")
        self.assertEqual(layout_events[0].session_id, "sess_1")


if __name__ == "__main__":
    unittest.main()
