"""Route runtime output streams to in-memory buffers."""

from __future__ import annotations

from threading import Lock


class StreamRouter:
    """Stores terminal output per panel for later inspection or repaint."""

    def __init__(self, *, max_buffer_chars: int = 32_000) -> None:
        self._max_buffer_chars = max_buffer_chars
        self._buffers: dict[str, str] = {}
        self._lock = Lock()

    def clear(self, panel_id: str) -> None:
        with self._lock:
            self._buffers[panel_id] = ""

    def route_output(self, panel_id: str, chunk: str) -> None:
        with self._lock:
            existing = self._buffers.get(panel_id, "")
            combined = f"{existing}{chunk}"
            self._buffers[panel_id] = combined[-self._max_buffer_chars :]

    def get_buffer(self, panel_id: str) -> str:
        with self._lock:
            return self._buffers.get(panel_id, "")
