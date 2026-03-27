"""libvterm-backed terminal engine."""

from __future__ import annotations

import re

from cockpit.terminal.bindings.libvterm_ffi import load_libvterm
from cockpit.terminal.engine.base import TerminalEngine
from cockpit.terminal.engine.fallback import FallbackTerminalEngine
from cockpit.terminal.engine.models import (
    TerminalCell,
    TerminalCursorState,
    TerminalEngineSnapshot,
)


ALTSCREEN_SEQUENCE_RE = re.compile(r"(\x1b\[\?1049[hl])")
BARE_LF_RE = re.compile(r"(?<!\r)\n")


class LibVTermTerminalEngine(TerminalEngine):
    """Thin libvterm-backed engine wrapper."""

    def __init__(self, *, rows: int = 24, cols: int = 80) -> None:
        ffi, lib = load_libvterm()
        self._ffi = ffi
        self._lib = lib
        self._rows = max(1, int(rows))
        self._cols = max(1, int(cols))
        self._alternate_active = False
        self._transcript_engine = FallbackTerminalEngine()
        self._transcript_engine.resize(self._rows, self._cols)
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
        if (
            term is not None
            and ffi is not None
            and lib is not None
            and term != ffi.NULL
        ):
            lib.vterm_free(term)
            self._term = ffi.NULL

    def reset(self) -> None:
        self._lib.vterm_screen_reset(self._screen, 1)
        self._alternate_active = False
        self._transcript_engine.reset()
        self._transcript_engine.resize(self._rows, self._cols)

    def feed(self, chunk: str) -> None:
        if not chunk:
            return
        normalized = self._normalize_linefeeds(chunk)
        self._feed_transcript(normalized)
        payload = normalized.encode("utf-8", errors="ignore")
        self._lib.vterm_input_write(self._term, payload, len(payload))
        self._lib.vterm_screen_flush_damage(self._screen)

    def resize(self, rows: int, cols: int) -> None:
        self._rows = max(1, int(rows))
        self._cols = max(1, int(cols))
        self._transcript_engine.resize(self._rows, self._cols)
        self._lib.vterm_set_size(self._term, self._rows, self._cols)
        self._lib.vterm_screen_flush_damage(self._screen)

    def snapshot(self) -> TerminalEngineSnapshot:
        cell_rows = self._visible_cell_rows()
        lines = tuple(self._line_from_cells(row) for row in cell_rows)
        trimmed_lines = self._trimmed_lines(lines)
        cursor = self._ffi.new("VTermPos *")
        self._lib.vterm_state_get_cursorpos(self._state, cursor)
        transcript_lines = list(self._transcript_engine.snapshot().lines)
        scrollback: tuple[str, ...] = ()
        if transcript_lines:
            if self._alternate_active:
                scrollback = tuple(transcript_lines)
            else:
                cutoff = min(len(trimmed_lines), len(transcript_lines))
                scrollback = (
                    tuple(transcript_lines[:-cutoff])
                    if cutoff
                    else tuple(transcript_lines)
                )
        return TerminalEngineSnapshot(
            rows=self._rows,
            cols=self._cols,
            lines=trimmed_lines,
            scrollback=scrollback,
            cells=tuple(cell_rows),
            scrollback_cells=tuple(self._cells_from_text(line) for line in scrollback),
            cursor=TerminalCursorState(
                row=max(0, int(cursor.row)),
                col=max(0, int(cursor.col)),
                visible=True,
            ),
            alternate_screen_active=self._alternate_active,
        )

    @staticmethod
    def _normalize_linefeeds(chunk: str) -> str:
        return BARE_LF_RE.sub("\r\n", chunk)

    def _feed_transcript(self, chunk: str) -> None:
        for part in ALTSCREEN_SEQUENCE_RE.split(chunk):
            if not part:
                continue
            if part == "\x1b[?1049h":
                self._alternate_active = True
                continue
            if part == "\x1b[?1049l":
                self._alternate_active = False
                continue
            if not self._alternate_active:
                self._transcript_engine.feed(part)

    def _visible_cell_rows(self) -> tuple[tuple[TerminalCell, ...], ...]:
        rows: list[tuple[TerminalCell, ...]] = []
        for row_index in range(self._rows):
            rows.append(
                tuple(
                    self._cell_at(row_index, col_index)
                    for col_index in range(self._cols)
                )
            )
        return tuple(rows)

    def _cell_at(self, row: int, col: int) -> TerminalCell:
        cell = self._ffi.new("VTermScreenCell *")
        pos = self._ffi.new("VTermPos *", {"row": row, "col": col})
        result = self._lib.vterm_screen_get_cell(self._screen, pos[0], cell)
        if result == 0:
            return TerminalCell(text=" ")
        raw_cell = cell[0]
        width = self._byte_to_int(raw_cell.width)
        return TerminalCell(
            text=self._decode_cell_text(raw_cell),
            width=max(0, width),
            fg=self._color_to_hex(raw_cell.fg, default_mask=0x02),
            bg=self._color_to_hex(raw_cell.bg, default_mask=0x04),
            bold=bool(raw_cell.attrs.bold),
            italic=bool(raw_cell.attrs.italic),
            underline=bool(raw_cell.attrs.underline),
            reverse=bool(raw_cell.attrs.reverse),
        )

    def _decode_cell_text(self, raw_cell) -> str:
        codepoints = [
            int(raw_cell.chars[index])
            for index in range(6)
            if int(raw_cell.chars[index])
        ]
        if not codepoints:
            return "" if self._byte_to_int(raw_cell.width) == 0 else " "
        return "".join(chr(codepoint) for codepoint in codepoints)

    def _color_to_hex(self, color, *, default_mask: int) -> str | None:
        converted = self._ffi.new("VTermColor *")
        converted[0] = color
        if self._byte_to_int(converted.type) & default_mask:
            return None
        self._lib.vterm_screen_convert_color_to_rgb(self._screen, converted)
        return "#{:02x}{:02x}{:02x}".format(
            self._byte_to_int(converted.rgb.red),
            self._byte_to_int(converted.rgb.green),
            self._byte_to_int(converted.rgb.blue),
        )

    @staticmethod
    def _byte_to_int(value) -> int:
        if isinstance(value, bytes):
            return value[0] if value else 0
        return int(value)

    @staticmethod
    def _line_from_cells(row: tuple[TerminalCell, ...]) -> str:
        rendered = "".join(cell.text for cell in row if cell.width != 0)
        return rendered.rstrip()

    @staticmethod
    def _trimmed_lines(lines: tuple[str, ...]) -> tuple[str, ...]:
        trimmed = list(lines)
        while trimmed and trimmed[-1] == "":
            trimmed.pop()
        return tuple(trimmed or [""])

    @staticmethod
    def _cells_from_text(text: str) -> tuple[TerminalCell, ...]:
        if not text:
            return tuple()
        return tuple(TerminalCell(text=character) for character in text)
