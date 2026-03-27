"""Terminal engine contracts and implementations."""

from cockpit.terminal.engine.factory import create_terminal_engine
from cockpit.terminal.engine.models import (
    TerminalCell,
    TerminalCursorState,
    TerminalEngineSnapshot,
    TerminalInputEvent,
    TerminalSearchMatch,
    TerminalSelection,
)

__all__ = [
    "TerminalCell",
    "TerminalCursorState",
    "TerminalEngineSnapshot",
    "TerminalInputEvent",
    "TerminalSearchMatch",
    "TerminalSelection",
    "create_terminal_engine",
]
