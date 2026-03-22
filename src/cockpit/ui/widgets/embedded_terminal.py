"""Embedded terminal output widget."""

from __future__ import annotations

import re

from textual.widgets import Static


ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
OSC_RE = re.compile(r"\x1b\][^\x07]*(?:\x07|\x1b\\)")
CONTROL_RE = re.compile(r"[\x00-\x07\x0b-\x0c\x0e-\x1a\x1c-\x1f]")


class EmbeddedTerminal(Static):
    """Focusable terminal output surface backed by the runtime PTY stream."""

    can_focus = True

    def __init__(self) -> None:
        super().__init__("Terminal idle. Focus here and type to send input.", id="embedded-terminal")
        self._buffer = ""
        self._max_chars = 16_000
        self._placeholder = "Terminal idle. Focus here and type to send input."
        self._viewport_offset = 0

    def clear(self, message: str = "Launching terminal...") -> None:
        self._buffer = ""
        self._placeholder = message
        self._viewport_offset = 0
        self.update(message)

    def append_output(self, chunk: str) -> None:
        sanitized = self._sanitize(chunk)
        if not sanitized:
            return
        follow_output = self._viewport_offset == 0
        self._buffer = self._apply_stream_update(self._buffer, sanitized)[-self._max_chars :]
        if follow_output:
            self._viewport_offset = 0
        self._refresh_view()

    def set_status(self, message: str) -> None:
        self.append_output(message)

    def current_output(self) -> str:
        return self._buffer

    def page_up(self) -> None:
        lines = self._buffer_lines()
        if not lines:
            return
        step = self._viewport_step()
        max_offset = max(0, len(lines) - step)
        self._viewport_offset = min(max_offset, self._viewport_offset + step)
        self._refresh_view()

    def page_down(self) -> None:
        if self._viewport_offset == 0:
            return
        step = self._viewport_step()
        self._viewport_offset = max(0, self._viewport_offset - step)
        self._refresh_view()

    def scroll_to_end(self) -> None:
        if self._viewport_offset == 0 and self._buffer:
            return
        self._viewport_offset = 0
        self._refresh_view()

    def viewport_offset(self) -> int:
        return self._viewport_offset

    def _sanitize(self, chunk: str) -> str:
        without_osc = OSC_RE.sub("", chunk)
        without_ansi = ANSI_RE.sub("", without_osc)
        normalized = without_ansi.replace("\r\n", "\n")
        return CONTROL_RE.sub("", normalized)

    def _apply_stream_update(self, buffer: str, chunk: str) -> str:
        result = buffer
        for character in chunk:
            if character == "\r":
                last_newline = result.rfind("\n")
                result = result[: last_newline + 1] if last_newline >= 0 else ""
                continue
            if character in {"\b", "\x7f"}:
                if result and result[-1] != "\n":
                    result = result[:-1]
                continue
            result = f"{result}{character}"
        return result

    def _refresh_view(self) -> None:
        if not self._buffer:
            self.update(self._placeholder)
            return
        lines = self._buffer_lines()
        end = len(lines) - self._viewport_offset if self._viewport_offset else len(lines)
        start = max(0, end - self._viewport_step())
        visible = lines[start:end]
        self.update("\n".join(visible))

    def _buffer_lines(self) -> list[str]:
        lines = self._buffer.split("\n")
        if lines and lines[-1] == "":
            return lines[:-1] or [""]
        return lines

    def _viewport_step(self) -> int:
        size = getattr(self, "size", None)
        height = getattr(size, "height", 0) if size is not None else 0
        if height <= 0:
            content_size = getattr(self, "content_size", None)
            height = getattr(content_size, "height", 0) if content_size is not None else 0
        return max(1, int(height) if height else 10)
