"""Embedded terminal output widget."""

from __future__ import annotations

import re

from textual.widgets import Static


ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class EmbeddedTerminal(Static):
    """Focusable terminal output surface backed by the runtime PTY stream."""

    can_focus = True

    def __init__(self) -> None:
        super().__init__("Terminal idle. Focus here and type to send input.", id="embedded-terminal")
        self._buffer = ""
        self._max_chars = 16_000

    def clear(self, message: str = "Launching terminal...") -> None:
        self._buffer = ""
        self.update(message)

    def append_output(self, chunk: str) -> None:
        sanitized = self._sanitize(chunk)
        if not sanitized:
            return
        self._buffer = f"{self._buffer}{sanitized}"[-self._max_chars :]
        self.update(self._buffer)

    def set_status(self, message: str) -> None:
        if self._buffer:
            self.update(f"{self._buffer}\n{message}")
        else:
            self.update(message)

    def current_output(self) -> str:
        return self._buffer

    def _sanitize(self, chunk: str) -> str:
        normalized = chunk.replace("\r\n", "\n").replace("\r", "\n")
        without_ansi = ANSI_RE.sub("", normalized)
        return CONTROL_RE.sub("", without_ansi)
