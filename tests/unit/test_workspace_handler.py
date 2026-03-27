import unittest

from cockpit.core.dispatch.event_bus import EventBus
from cockpit.workspace.handlers.workspace_handlers import OpenWorkspaceHandler
from cockpit.core.command import Command
from cockpit.workspace.events import WorkspaceOpened
from cockpit.workspace.models.workspace import SessionTarget, Workspace
from cockpit.core.enums import CommandSource, SessionTargetKind


class WorkspaceHandlerTests(unittest.TestCase):
    def test_open_workspace_publishes_event_when_workspace_resolved(self) -> None:
        bus = EventBus()

        def opener(_command: Command) -> Workspace:
            return Workspace(
                id="ws_local",
                name="Local",
                root_path="/tmp/project",
                target=SessionTarget(kind=SessionTargetKind.LOCAL),
            )

        handler = OpenWorkspaceHandler(bus, opener=opener)

        result = handler(
            Command(id="cmd_1", source=CommandSource.SLASH, name="workspace.open")
        )

        self.assertTrue(result.success)
        self.assertTrue(
            any(isinstance(event, WorkspaceOpened) for event in bus.published)
        )


if __name__ == "__main__":
    unittest.main()
