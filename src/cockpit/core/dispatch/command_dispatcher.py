"""Command dispatcher."""

from __future__ import annotations

from collections.abc import Callable

from cockpit.core.dispatch.handler_base import (
    CommandContextError,
    CommandHandlingError,
    ConfirmationRequiredError,
    DispatchResult,
    PolicyViolationError,
)
from cockpit.core.dispatch.event_bus import EventBus
from cockpit.core.command import Command
from cockpit.workspace.events import CommandExecuted
from cockpit.core.events.runtime import StatusMessagePublished
from cockpit.core.enums import StatusLevel

CommandHandler = Callable[[Command], DispatchResult]
CommandObserver = Callable[[Command, DispatchResult], None]


class UnknownCommandError(LookupError):
    """Raised when a command handler is not registered."""


class CommandDispatcher:
    """Dispatches command objects to registered handlers."""

    def __init__(self, *, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._handlers: dict[str, CommandHandler] = {}
        self._observers: list[CommandObserver] = []

    def register(self, command_name: str, handler: CommandHandler) -> None:
        if command_name in self._handlers:
            raise ValueError(f"Handler already registered for '{command_name}'.")
        self._handlers[command_name] = handler

    def observe(self, observer: CommandObserver) -> None:
        self._observers.append(observer)

    def dispatch(self, command: Command) -> DispatchResult:
        handler = self._handlers.get(command.name)
        if handler is None:
            raise UnknownCommandError(f"No handler registered for '{command.name}'.")

        try:
            result = handler(command)
        except ConfirmationRequiredError as exc:
            self._event_bus.publish(
                StatusMessagePublished(message=str(exc), level=StatusLevel.WARNING)
            )
            return DispatchResult(
                success=False,
                message=str(exc),
                data={
                    "confirmation_required": True,
                    **exc.payload,
                },
            )
        except PolicyViolationError as exc:
            self._event_bus.publish(
                StatusMessagePublished(message=str(exc), level=StatusLevel.WARNING)
            )
            failure = DispatchResult(
                success=False,
                message=str(exc),
                data={"policy_violation": True, **exc.payload},
            )
            self._notify_observers(command, failure)
            self._event_bus.publish(
                CommandExecuted(
                    command_id=command.id,
                    name=command.name,
                    source=command.source,
                    success=False,
                    message=failure.message,
                )
            )
            return failure
        except CommandContextError as exc:
            self._event_bus.publish(
                StatusMessagePublished(message=str(exc), level=StatusLevel.ERROR)
            )
            failure = DispatchResult(success=False, message=str(exc))
            self._notify_observers(command, failure)
            self._event_bus.publish(
                CommandExecuted(
                    command_id=command.id,
                    name=command.name,
                    source=command.source,
                    success=False,
                    message=failure.message,
                )
            )
            return failure
        except CommandHandlingError as exc:
            self._event_bus.publish(
                StatusMessagePublished(message=str(exc), level=StatusLevel.ERROR)
            )
            failure = DispatchResult(success=False, message=str(exc))
            self._notify_observers(command, failure)
            self._event_bus.publish(
                CommandExecuted(
                    command_id=command.id,
                    name=command.name,
                    source=command.source,
                    success=False,
                    message=failure.message,
                )
            )
            return failure

        self._notify_observers(command, result)
        self._event_bus.publish(
            CommandExecuted(
                command_id=command.id,
                name=command.name,
                source=command.source,
                success=result.success,
                message=result.message,
            )
        )
        if result.message:
            level = StatusLevel.INFO if result.success else StatusLevel.ERROR
            self._event_bus.publish(
                StatusMessagePublished(message=result.message, level=level)
            )
        return result

    def _notify_observers(self, command: Command, result: DispatchResult) -> None:
        for observer in self._observers:
            observer(command, result)
