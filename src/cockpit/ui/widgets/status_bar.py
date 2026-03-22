"""Status bar widget."""

from __future__ import annotations

from textual.widgets import Static

from cockpit.shared.enums import StatusLevel


class StatusBar(Static):
    """Simple status bar for bootstrap feedback."""

    def __init__(self) -> None:
        super().__init__("Ready", id="status-bar")

    def set_message(self, message: str, level: StatusLevel = StatusLevel.INFO) -> None:
        self.update(f"[{level.value}] {message}")

