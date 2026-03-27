"""Terminal engine base contracts."""

from __future__ import annotations

from typing import Protocol

from cockpit.terminal.engine.models import TerminalEngineSnapshot


class TerminalEngine(Protocol):
    """Screen-emulation boundary used by the TUI layer."""

    def reset(self) -> None: ...

    def feed(self, chunk: str) -> None: ...

    def resize(self, rows: int, cols: int) -> None: ...

    def snapshot(self) -> TerminalEngineSnapshot: ...
