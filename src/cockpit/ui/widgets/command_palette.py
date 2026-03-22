"""Command palette widget."""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Static


@dataclass(slots=True, frozen=True)
class PaletteItem:
    label: str
    command_text: str
    description: str = ""


class CommandPalette(Vertical):
    """Minimal filterable command palette bound to the shared dispatcher path."""

    def __init__(self) -> None:
        super().__init__(id="command-palette")
        self.display = False
        self._items: list[PaletteItem] = []
        self._filtered_items: list[PaletteItem] = []
        self._selected_index = 0

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Filter commands", id="command-palette-input")
        yield Static("No commands available.", id="command-palette-results")

    def open(self, items: list[PaletteItem]) -> None:
        self._items = items
        self._selected_index = 0
        self.display = True
        palette_input = self.query_one(Input)
        palette_input.value = ""
        self.filter("")
        palette_input.focus()

    def close(self) -> None:
        self.display = False

    @property
    def is_open(self) -> bool:
        return bool(self.display)

    def filter(self, query: str) -> None:
        normalized = query.strip().lower()
        if not normalized:
            self._filtered_items = list(self._items)
        else:
            self._filtered_items = [
                item
                for item in self._items
                if normalized in item.label.lower()
                or normalized in item.command_text.lower()
                or normalized in item.description.lower()
            ]
        self._selected_index = min(self._selected_index, max(0, len(self._filtered_items) - 1))
        self._render_results()

    def move_selection(self, delta: int) -> None:
        if not self._filtered_items:
            return
        self._selected_index = max(
            0,
            min(len(self._filtered_items) - 1, self._selected_index + delta),
        )
        self._render_results()

    def selected_item(self) -> PaletteItem | None:
        if not self._filtered_items:
            return None
        return self._filtered_items[self._selected_index]

    def _render_results(self) -> None:
        results = self.query_one("#command-palette-results", Static)
        if not self._filtered_items:
            results.update("No matching commands.")
            return
        lines: list[str] = []
        for index, item in enumerate(self._filtered_items[:8]):
            marker = ">" if index == self._selected_index else " "
            description = f" - {item.description}" if item.description else ""
            lines.append(f"{marker} {item.label}: {item.command_text}{description}")
        results.update("\n".join(lines))
