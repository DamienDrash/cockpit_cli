"""Embedded terminal output widget."""

from __future__ import annotations

from textual.widgets import Static

from cockpit.ui.widgets.terminal_buffer import TerminalBuffer


class EmbeddedTerminal(Static):
    """Focusable terminal output surface backed by the runtime PTY stream."""

    can_focus = True

    def __init__(self) -> None:
        super().__init__("Terminal idle. Focus here and type to send input.", id="embedded-terminal")
        self._buffer = TerminalBuffer()
        self._max_chars = 16_000
        self._placeholder = "Terminal idle. Focus here and type to send input."
        self._viewport_offset = 0

    def clear(self, message: str = "Launching terminal...") -> None:
        self._buffer.reset()
        self._placeholder = message
        self._viewport_offset = 0
        self.update(message)

    def append_output(self, chunk: str) -> None:
        if not chunk:
            return
        follow_output = self._viewport_offset == 0
        self._buffer.feed(chunk)
        if follow_output:
            self._viewport_offset = 0
        self._refresh_view()

    def set_status(self, message: str) -> None:
        self.append_output(message)

    def current_output(self) -> str:
        return self._trimmed_buffer()

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

    def _refresh_view(self) -> None:
        buffer_text = self._trimmed_buffer()
        if not buffer_text:
            self.update(self._placeholder)
            return
        lines = self._buffer_lines(buffer_text)
        end = len(lines) - self._viewport_offset if self._viewport_offset else len(lines)
        start = max(0, end - self._viewport_step())
        visible = lines[start:end]
        self.update("\n".join(visible))

    def _buffer_lines(self, buffer_text: str | None = None) -> list[str]:
        if buffer_text is None:
            buffer_text = self._trimmed_buffer()
        lines = buffer_text.split("\n")
        if lines and lines[-1] == "":
            return lines[:-1] or [""]
        return lines

    def _trimmed_buffer(self) -> str:
        return self._buffer.render_text()[-self._max_chars :]

    def _viewport_step(self) -> int:
        size = getattr(self, "size", None)
        height = getattr(size, "height", 0) if size is not None else 0
        if height <= 0:
            content_size = getattr(self, "content_size", None)
            height = getattr(content_size, "height", 0) if content_size is not None else 0
        return max(1, int(height) if height else 10)
