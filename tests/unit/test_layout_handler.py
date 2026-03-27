import unittest

from cockpit.core.dispatch.event_bus import EventBus
from cockpit.workspace.handlers.layout_handlers import (
    AdjustActiveLayoutRatioHandler,
    ApplyDefaultLayoutHandler,
    FocusNextPanelHandler,
    ToggleActiveLayoutOrientationHandler,
)
from cockpit.core.dispatch.handler_base import CommandContextError
from cockpit.core.command import Command
from cockpit.workspace.events import LayoutApplied
from cockpit.core.enums import CommandSource


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

    def test_toggles_active_layout_orientation(self) -> None:
        handler = ToggleActiveLayoutOrientationHandler()

        result = handler(
            Command(
                id="cmd_2",
                source=CommandSource.SLASH,
                name="layout.toggle_orientation",
                context={
                    "active_tab_id": "work",
                    "tabs": [
                        {
                            "id": "work",
                            "root_split": {
                                "orientation": "vertical",
                                "ratio": 0.7,
                                "children": [
                                    {"panel_id": "work-panel", "panel_type": "work"},
                                    {"panel_id": "db-panel", "panel_type": "db"},
                                ],
                            },
                        }
                    ],
                },
            )
        )

        self.assertTrue(result.success)
        self.assertEqual(
            result.data["tabs"][0]["root_split"]["orientation"], "horizontal"
        )

    def test_adjusts_active_layout_ratio(self) -> None:
        handler = AdjustActiveLayoutRatioHandler(delta=0.1)

        result = handler(
            Command(
                id="cmd_3",
                source=CommandSource.SLASH,
                name="layout.grow",
                context={
                    "active_tab_id": "work",
                    "tabs": [
                        {
                            "id": "work",
                            "root_split": {
                                "orientation": "vertical",
                                "ratio": 0.7,
                                "children": [
                                    {"panel_id": "work-panel", "panel_type": "work"},
                                    {"panel_id": "db-panel", "panel_type": "db"},
                                ],
                            },
                        }
                    ],
                },
            )
        )

        self.assertTrue(result.success)
        self.assertEqual(result.data["tabs"][0]["root_split"]["ratio"], 0.8)

    def test_focuses_next_visible_panel(self) -> None:
        handler = FocusNextPanelHandler()

        result = handler(
            Command(
                id="cmd_4",
                source=CommandSource.SLASH,
                name="panel.focus_next",
                context={
                    "visible_panel_ids": ["work-panel", "db-panel"],
                    "focused_panel_id": "work-panel",
                },
            )
        )

        self.assertTrue(result.success)
        self.assertEqual(result.data["focus_panel_id"], "db-panel")

    def test_focus_next_panel_requires_visible_panels(self) -> None:
        handler = FocusNextPanelHandler()

        with self.assertRaises(CommandContextError):
            handler(
                Command(
                    id="cmd_5",
                    source=CommandSource.SLASH,
                    name="panel.focus_next",
                    context={},
                )
            )


if __name__ == "__main__":
    unittest.main()
