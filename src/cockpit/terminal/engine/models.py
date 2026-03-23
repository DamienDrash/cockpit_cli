"""Typed terminal engine boundary objects."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True, frozen=True)
class TerminalCell:
    """Renderable terminal cell."""

    text: str = " "
    width: int = 1
    fg: str | None = None
    bg: str | None = None
    bold: bool = False
    italic: bool = False
    underline: bool = False
    reverse: bool = False


@dataclass(slots=True, frozen=True)
class TerminalCursorState:
    """Cursor state exposed to the UI layer."""

    row: int = 0
    col: int = 0
    visible: bool = True
    shape: str = "block"


@dataclass(slots=True, frozen=True)
class TerminalSelection:
    """Rectangular or linear selection coordinates."""

    start_row: int
    start_col: int
    end_row: int
    end_col: int


@dataclass(slots=True, frozen=True)
class TerminalSearchMatch:
    """A search match in the exported terminal text."""

    row: int
    start_col: int
    end_col: int
    query: str


@dataclass(slots=True, frozen=True)
class TerminalInputEvent:
    """Normalized terminal input event."""

    kind: str
    payload: str


@dataclass(slots=True, frozen=True)
class TerminalEngineSnapshot:
    """Immutable terminal snapshot passed to the UI layer."""

    rows: int
    cols: int
    lines: tuple[str, ...]
    scrollback: tuple[str, ...] = field(default_factory=tuple)
    cells: tuple[tuple[TerminalCell, ...], ...] = field(default_factory=tuple)
    scrollback_cells: tuple[tuple[TerminalCell, ...], ...] = field(default_factory=tuple)
    cursor: TerminalCursorState = field(default_factory=TerminalCursorState)
    title: str | None = None
    alternate_screen_active: bool = False

    def render_text(self) -> str:
        """Flatten the snapshot into display text."""
        lines = list(self.scrollback) + list(self.lines)
        while lines and lines[-1] == "":
            lines.pop()
        return "\n".join(lines)

    def render_rows(self) -> tuple[tuple[TerminalCell, ...], ...]:
        """Return the scrollback and visible rows as terminal cells."""
        if self.scrollback_cells or self.cells:
            return self.scrollback_cells + self.cells
        rows = tuple(_row_from_text(line) for line in self.scrollback + self.lines)
        return rows or (tuple(),)


def _row_from_text(text: str) -> tuple[TerminalCell, ...]:
    if not text:
        return tuple()
    return tuple(TerminalCell(text=character) for character in text)
