"""Pure-Python fallback terminal engine."""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from cockpit.terminal.engine.models import TerminalCell, TerminalCursorState, TerminalEngineSnapshot


OSC_RE = re.compile(r"\x1b\][^\x07]*(?:\x07|\x1b\\)")


@dataclass
class _ScreenState:
    lines: list[list[str]] = field(default_factory=lambda: [[]])
    row: int = 0
    col: int = 0
    saved_row: int = 0
    saved_col: int = 0


class FallbackTerminalEngine:
    """Maintain a simplified terminal screen with basic CSI support."""

    def __init__(self) -> None:
        self._rows = 24
        self._cols = 80
        self.reset()

    def reset(self) -> None:
        self._primary = _ScreenState()
        self._alternate = _ScreenState()
        self._alternate_active = False

    def feed(self, chunk: str) -> None:
        cleaned = OSC_RE.sub("", chunk)
        index = 0
        while index < len(cleaned):
            character = cleaned[index]
            if character == "\x1b":
                consumed = self._consume_escape(cleaned[index:])
                index += consumed
                continue
            self._consume_character(character)
            index += 1

    def resize(self, rows: int, cols: int) -> None:
        self._rows = max(1, int(rows))
        self._cols = max(1, int(cols))

    def snapshot(self) -> TerminalEngineSnapshot:
        state = self._state()
        lines = ["".join(line).rstrip() for line in state.lines]
        while lines and lines[-1] == "":
            lines.pop()
        if not lines:
            lines = [""]
        cells = tuple(self._cells_from_line(line) for line in lines)
        return TerminalEngineSnapshot(
            rows=self._rows,
            cols=self._cols,
            lines=tuple(lines),
            cells=cells,
            cursor=TerminalCursorState(
                row=max(0, state.row),
                col=max(0, state.col),
                visible=True,
            ),
            alternate_screen_active=self._alternate_active,
        )

    @staticmethod
    def _cells_from_line(line: str) -> tuple[TerminalCell, ...]:
        if not line:
            return tuple()
        return tuple(TerminalCell(text=character) for character in line)

    def _state(self) -> _ScreenState:
        return self._alternate if self._alternate_active else self._primary

    def _consume_escape(self, text: str) -> int:
        if len(text) < 2:
            return len(text)
        if text[1] != "[":
            return 2
        end = 2
        while end < len(text):
            codepoint = text[end]
            if "@" <= codepoint <= "~":
                self._handle_csi(text[2:end], codepoint)
                return end + 1
            end += 1
        return len(text)

    def _consume_character(self, character: str) -> None:
        state = self._state()
        if character == "\r":
            state.col = 0
            return
        if character == "\n":
            state.row += 1
            state.col = 0
            self._ensure_row(state, state.row)
            return
        if character in {"\b", "\x7f"}:
            state.col = max(0, state.col - 1)
            return
        if character == "\t":
            next_tab = 4 - (state.col % 4) or 4
            for _ in range(next_tab):
                self._write_char(state, " ")
            return
        if ord(character) < 32:
            return
        self._write_char(state, character)

    def _write_char(self, state: _ScreenState, character: str) -> None:
        self._ensure_row(state, state.row)
        line = state.lines[state.row]
        while len(line) < state.col:
            line.append(" ")
        if len(line) == state.col:
            line.append(character)
        else:
            line[state.col] = character
        state.col += 1

    def _ensure_row(self, state: _ScreenState, row: int) -> None:
        while len(state.lines) <= row:
            state.lines.append([])

    def _handle_csi(self, raw_params: str, final: str) -> None:
        if raw_params.startswith("?1049"):
            if final == "h":
                self._alternate_active = True
                self._alternate = _ScreenState()
            elif final == "l":
                self._alternate_active = False
            return
        if raw_params.startswith("?"):
            return

        params = [int(part) if part else 0 for part in raw_params.split(";")] if raw_params else [0]
        state = self._state()
        if final == "A":
            state.row = max(0, state.row - max(1, params[0] or 1))
            return
        if final == "B":
            state.row += max(1, params[0] or 1)
            self._ensure_row(state, state.row)
            return
        if final == "C":
            state.col += max(1, params[0] or 1)
            return
        if final == "D":
            state.col = max(0, state.col - max(1, params[0] or 1))
            return
        if final == "G":
            state.col = max(0, (params[0] or 1) - 1)
            return
        if final in {"H", "f"}:
            row = (params[0] or 1) - 1
            col = (params[1] or 1) - 1 if len(params) > 1 else 0
            state.row = max(0, row)
            state.col = max(0, col)
            self._ensure_row(state, state.row)
            return
        if final == "J":
            mode = params[0] if params else 0
            if mode == 2:
                state.lines = [[]]
                state.row = 0
                state.col = 0
                return
            if mode == 0:
                self._clear_to_screen_end(state)
                return
            if mode == 1:
                self._clear_to_screen_start(state)
                return
        if final == "K":
            mode = params[0] if params else 0
            self._ensure_row(state, state.row)
            line = state.lines[state.row]
            if mode == 2:
                state.lines[state.row] = []
                state.col = 0
                return
            if mode == 1:
                for index in range(min(state.col + 1, len(line))):
                    line[index] = " "
                return
            while len(line) > state.col:
                line.pop()
            return
        if final == "s":
            state.saved_row = state.row
            state.saved_col = state.col
            return
        if final == "u":
            state.row = state.saved_row
            state.col = state.saved_col
            self._ensure_row(state, state.row)
            return

    def _clear_to_screen_end(self, state: _ScreenState) -> None:
        self._ensure_row(state, state.row)
        line = state.lines[state.row]
        while len(line) > state.col:
            line.pop()
        if state.row + 1 < len(state.lines):
            state.lines = state.lines[: state.row + 1]

    def _clear_to_screen_start(self, state: _ScreenState) -> None:
        self._ensure_row(state, state.row)
        for row_index in range(state.row):
            state.lines[row_index] = []
        line = state.lines[state.row]
        for index in range(min(state.col + 1, len(line))):
            line[index] = " "
