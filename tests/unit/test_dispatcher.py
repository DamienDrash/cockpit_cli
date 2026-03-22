import unittest

from cockpit.application.dispatch.command_dispatcher import (
    CommandDispatcher,
    UnknownCommandError,
)
from cockpit.application.dispatch.event_bus import EventBus
from cockpit.application.handlers.base import (
    CommandContextError,
    DispatchResult,
)
from cockpit.domain.commands.command import Command
from cockpit.domain.events.domain_events import CommandExecuted
from cockpit.domain.events.runtime_events import StatusMessagePublished
from cockpit.shared.enums import CommandSource


class CommandDispatcherTests(unittest.TestCase):
    def test_routes_command_and_publishes_success_event(self) -> None:
        bus = EventBus()
        dispatcher = CommandDispatcher(event_bus=bus)

        def handler(_command: Command) -> DispatchResult:
            return DispatchResult(success=True, message="ok")

        dispatcher.register("workspace.open", handler)

        result = dispatcher.dispatch(
            Command(id="cmd_1", source=CommandSource.SLASH, name="workspace.open")
        )

        self.assertTrue(result.success)
        self.assertTrue(any(isinstance(event, CommandExecuted) for event in bus.published))

    def test_turns_context_errors_into_failure_results(self) -> None:
        bus = EventBus()
        dispatcher = CommandDispatcher(event_bus=bus)

        def handler(_command: Command) -> DispatchResult:
            raise CommandContextError("missing workspace context")

        dispatcher.register("terminal.focus", handler)

        result = dispatcher.dispatch(
            Command(id="cmd_1", source=CommandSource.KEYBINDING, name="terminal.focus")
        )

        self.assertFalse(result.success)
        self.assertTrue(
            any(isinstance(event, StatusMessagePublished) for event in bus.published)
        )

    def test_raises_for_unknown_command(self) -> None:
        dispatcher = CommandDispatcher(event_bus=EventBus())

        with self.assertRaises(UnknownCommandError):
            dispatcher.dispatch(
                Command(id="cmd_1", source=CommandSource.SLASH, name="unknown.command")
            )


if __name__ == "__main__":
    unittest.main()

