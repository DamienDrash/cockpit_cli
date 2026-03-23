"""Compatibility wrapper around the terminal engine boundary."""

from __future__ import annotations

from cockpit.terminal.engine.factory import create_terminal_engine


class TerminalBuffer:
    """Compatibility wrapper for legacy widget call sites."""

    def __init__(self) -> None:
        self._engine = create_terminal_engine()

    def reset(self) -> None:
        self._engine.reset()

    def feed(self, chunk: str) -> None:
        self._engine.feed(chunk)

    def render_text(self) -> str:
        return self._engine.snapshot().render_text()

    def snapshot(self):
        return self._engine.snapshot()

    def resize(self, rows: int, cols: int) -> None:
        self._engine.resize(rows, cols)
