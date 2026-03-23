"""Base handler contracts."""

from __future__ import annotations

from dataclasses import dataclass, field


class CommandHandlingError(RuntimeError):
    """Base handler error."""


class CommandContextError(CommandHandlingError):
    """Raised when command context is missing or invalid."""


class ConfirmationRequiredError(CommandHandlingError):
    """Raised when a command requires explicit user confirmation."""

    def __init__(self, message: str, *, payload: dict[str, object]) -> None:
        super().__init__(message)
        self.payload = payload


class PolicyViolationError(CommandHandlingError):
    """Raised when a command is blocked or needs elevated mode."""

    def __init__(self, message: str, *, payload: dict[str, object]) -> None:
        super().__init__(message)
        self.payload = payload


@dataclass(slots=True)
class DispatchResult:
    success: bool
    message: str | None = None
    data: dict[str, object] = field(default_factory=dict)


class NoOpHandler:
    """Simple handler used for bootstrap-time command registration."""

    def __init__(self, message: str) -> None:
        self._message = message

    def __call__(self, _command: object) -> DispatchResult:
        return DispatchResult(success=True, message=self._message)
