"""libvterm-backed terminal engine."""

from __future__ import annotations

from cockpit.terminal.bindings.libvterm_ffi import load_libvterm
from cockpit.terminal.engine.base import TerminalEngine
from cockpit.terminal.engine.models import TerminalCursorState, TerminalEngineSnapshot


class LibVTermTerminalEngine(TerminalEngine):
    """Thin libvterm-backed engine wrapper."""

    def __init__(self, *, rows: int = 24, cols: int = 80) -> None:
        ffi, lib = load_libvterm()
        self._ffi = ffi
        self._lib = lib
        self._rows = max(1, int(rows))
        self._cols = max(1, int(cols))
        self._term = lib.vterm_new(self._rows, self._cols)
        if self._term == ffi.NULL:
            raise RuntimeError("libvterm could not allocate a terminal instance.")
        self._state = lib.vterm_obtain_state(self._term)
        self._screen = lib.vterm_obtain_screen(self._term)
        lib.vterm_set_utf8(self._term, 1)
        lib.vterm_screen_enable_altscreen(self._screen, 1)
        lib.vterm_screen_set_damage_merge(self._screen, lib.VTERM_DAMAGE_SCREEN)
        lib.vterm_screen_reset(self._screen, 1)

    def __del__(self) -> None:
        term = getattr(self, "_term", None)
        ffi = getattr(self, "_ffi", None)
        lib = getattr(self, "_lib", None)
        if term is not None and ffi is not None and lib is not None and term != ffi.NULL:
            lib.vterm_free(term)
            self._term = ffi.NULL

    def reset(self) -> None:
        self._lib.vterm_screen_reset(self._screen, 1)

    def feed(self, chunk: str) -> None:
        if not chunk:
            return
        payload = chunk.encode("utf-8", errors="ignore")
        self._lib.vterm_input_write(self._term, payload, len(payload))
        self._lib.vterm_screen_flush_damage(self._screen)

    def resize(self, rows: int, cols: int) -> None:
        self._rows = max(1, int(rows))
        self._cols = max(1, int(cols))
        self._lib.vterm_set_size(self._term, self._rows, self._cols)
        self._lib.vterm_screen_flush_damage(self._screen)

    def snapshot(self) -> TerminalEngineSnapshot:
        rect = self._ffi.new(
            "VTermRect *",
            {
                "start_row": 0,
                "end_row": self._rows,
                "start_col": 0,
                "end_col": self._cols,
            },
        )[0]
        buffer_len = max(1, self._rows * (self._cols + 1) * 4)
        raw_buffer = self._ffi.new("char[]", buffer_len)
        read_count = self._lib.vterm_screen_get_text(self._screen, raw_buffer, buffer_len, rect)
        text = self._ffi.buffer(raw_buffer, read_count)[:].decode("utf-8", errors="ignore")
        lines = text.splitlines()
        if not lines:
            lines = [""]
        cursor = self._ffi.new("VTermPos *")
        self._lib.vterm_state_get_cursorpos(self._state, cursor)
        return TerminalEngineSnapshot(
            rows=self._rows,
            cols=self._cols,
            lines=tuple(lines),
            cursor=TerminalCursorState(
                row=max(0, int(cursor.row)),
                col=max(0, int(cursor.col)),
                visible=True,
            ),
        )

