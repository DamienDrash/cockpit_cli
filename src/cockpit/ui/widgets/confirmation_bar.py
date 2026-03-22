"""Inline confirmation bar for destructive actions."""

from __future__ import annotations

from textual.widgets import Static


class ConfirmationBar(Static):
    """Shows a pending destructive action confirmation."""

    def __init__(self) -> None:
        super().__init__("", id="confirmation-bar", markup=False)
        self.display = False

    @property
    def is_open(self) -> bool:
        return bool(self.display)

    def open(self, message: str) -> None:
        self.update(message)
        self.display = True

    def close(self) -> None:
        self.display = False
        self.update("")
