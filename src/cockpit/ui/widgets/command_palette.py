"""Command palette placeholder widget."""

from textual.widgets import Static


class CommandPalette(Static):
    """Minimal palette placeholder for the bootstrap app."""

    def __init__(self) -> None:
        super().__init__("Command palette not implemented yet.", id="command-palette")

