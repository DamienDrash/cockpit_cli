"""Cyberpunk scanline overlay widget."""

from textual.widgets import Static


class ScanlineOverlay(Static):
    """Subtle CRT scanline overlay."""

    def __init__(self) -> None:
        # A pattern of thin horizontal lines or dots
        pattern = "░" * 20000 
        super().__init__(pattern, id="scanline-overlay")
        self.can_focus = False
        self.pick_at = False
