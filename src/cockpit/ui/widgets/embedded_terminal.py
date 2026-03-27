"""Embedded terminal output widget."""

from __future__ import annotations

from pathlib import Path
from collections.abc import Callable

from rich.highlighter import RegexHighlighter
from rich.text import Text
from textual import events
from textual.widgets import Static

from cockpit.terminal.engine.models import TerminalCell, TerminalSearchMatch
from cockpit.ui.widgets.terminal_buffer import TerminalBuffer


Position = tuple[int, int]


class SemanticOutputHighlighter(RegexHighlighter):
    """Semantic highlighter for terminal output monitoring."""

    base_style = ""
    highlights = [
        r"(?P<error>ERROR|CRITICAL|FATAL|Exception|Traceback)",
        r"(?P<warning>WARNING|WARN)",
        r"(?P<url>https?://[^\s]+)",
        r"(?P<path>/(?:[a-zA-Z0-9._-]+/)+[a-zA-Z0-9._-]+)",
        r"(?P<json>\{.*\}|\[.*\])",
    ]


class EmbeddedTerminal(Static):
    """Focusable terminal output surface backed by the runtime PTY stream."""

    can_focus = True

    def __init__(self, on_input: Callable[[str], None] | None = None) -> None:
        super().__init__(
            "Terminal idle. Focus here and type to send input.", id="embedded-terminal"
        )
        self._buffer = TerminalBuffer(on_input=on_input)
        self._highlighter = SemanticOutputHighlighter()
        # Explicit styles for highlighter groups
        self._highlighter.styles["error"] = "bold #ff0055"
        self._highlighter.styles["warning"] = "bold #ffff00"
        self._highlighter.styles["url"] = "underline #00ffff"
        self._highlighter.styles["path"] = "#00ffff italic"
        self._highlighter.styles["json"] = "#00ff00"
        self._max_chars = 32_000  # Increased buffer
        self._placeholder = "Terminal idle. Focus here and type to send input."
        self._viewport_offset = 0
        self._search_query: str | None = None
        self._search_matches: list[TerminalSearchMatch] = []
        self._active_match_index = -1
        self._selection_anchor: Position | None = None
        self._selection_focus: Position | None = None
        self._drag_selection_active = False
        self._row_base_offset = 0
        self._pending_chunks: list[str] = []
        self._render_scheduled = False

    def clear(self, message: str = "Launching terminal...") -> None:
        self._buffer.reset()
        self._placeholder = message
        self._viewport_offset = 0
        self._search_query = None
        self._search_matches = []
        self._active_match_index = -1
        self._selection_anchor = None
        self._selection_focus = None
        self._drag_selection_active = False
        self._row_base_offset = 0
        self._pending_chunks = []
        self._render_scheduled = False
        self.update(message)

    def append_output(self, chunk: str) -> None:
        if not chunk:
            return
        self._pending_chunks.append(chunk)
        if not self._render_scheduled:
            self._render_scheduled = True
            # Throttled update: bundle all chunks arriving in the next 50ms
            self.call_later(self._process_pending_output)

    def _process_pending_output(self) -> None:
        if not self._pending_chunks:
            self._render_scheduled = False
            return

        combined_chunk = "".join(self._pending_chunks)
        self._pending_chunks = []
        self._render_scheduled = False

        follow_output = self._viewport_offset == 0
        previous_base_offset = self._row_base_offset
        self._buffer.feed(combined_chunk)
        self._refresh_search_matches()
        base_delta = self._row_base_offset - previous_base_offset
        if base_delta > 0:
            self._selection_anchor = self._shift_position(
                self._selection_anchor, -base_delta
            )
            self._selection_focus = self._shift_position(
                self._selection_focus, -base_delta
            )
        self._clamp_selection()
        if follow_output:
            self._viewport_offset = 0
        self._refresh_view()

    def set_status(self, message: str) -> None:
        self.append_output(message)

    def current_output(self) -> str:
        return "\n".join(self._trimmed_row_texts())

    def on_resize(self, event: events.Resize) -> None:
        self._buffer.resize(event.size.height, event.size.width)
        self._refresh_view()

    def page_up(self) -> None:
        rows = self._rows()
        if not rows:
            return
        step = self._viewport_step()
        max_offset = max(0, len(rows) - step)
        self._viewport_offset = min(max_offset, self._viewport_offset + step)
        self._refresh_view()

    def page_down(self) -> None:
        if self._viewport_offset == 0:
            return
        step = self._viewport_step()
        self._viewport_offset = max(0, self._viewport_offset - step)
        self._refresh_view()

    def scroll_to_end(self) -> None:
        if self._viewport_offset == 0 and self._rows():
            return
        self._viewport_offset = 0
        self._refresh_view()

    def viewport_offset(self) -> int:
        return self._viewport_offset

    def search(self, query: str) -> bool:
        normalized = query.strip()
        if not normalized:
            self._search_query = None
            self._search_matches = []
            self._active_match_index = -1
            self._refresh_view()
            return False
        self._search_query = normalized
        self._refresh_search_matches()
        if not self._search_matches:
            self._active_match_index = -1
            self._refresh_view()
            return False
        self._active_match_index = 0
        self._scroll_to_match(self._search_matches[0].row)
        self._refresh_view()
        return True

    def search_next(self) -> bool:
        if not self._search_matches:
            return False
        self._active_match_index = (self._active_match_index + 1) % len(
            self._search_matches
        )
        self._scroll_to_match(self._search_matches[self._active_match_index].row)
        self._refresh_view()
        return True

    def search_previous(self) -> bool:
        if not self._search_matches:
            return False
        self._active_match_index = (self._active_match_index - 1) % len(
            self._search_matches
        )
        self._scroll_to_match(self._search_matches[self._active_match_index].row)
        self._refresh_view()
        return True

    def export_text(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.current_output(), encoding="utf-8")
        return path

    def toggle_selection(self) -> bool:
        if self._selection_anchor is None:
            target_line = self._default_selection_line()
            self._select_line_range(target_line, extend=False)
            return True
        self.clear_selection()
        return False

    def clear_selection(self) -> None:
        self._selection_anchor = None
        self._selection_focus = None
        self._refresh_view()

    def has_selection(self) -> bool:
        return self._selection_anchor is not None and self._selection_focus is not None

    def expand_selection(self, delta: int) -> bool:
        rows = self._rows()
        if not rows:
            return False
        if self._selection_focus is None:
            target_line = self._default_selection_line()
            self._select_line_range(target_line, extend=False)
        assert self._selection_focus is not None
        next_line = max(0, min(len(rows) - 1, self._selection_focus[0] + delta))
        self._select_line_range(next_line, extend=True)
        return True

    def selected_text(self) -> str:
        selection = self._selection_range()
        if selection is None:
            return ""
        start, end = selection
        texts = self._trimmed_row_texts()
        selected_lines: list[str] = []
        for row_index in range(start[0], end[0] + 1):
            text = texts[row_index] if row_index < len(texts) else ""
            if row_index == start[0] == end[0]:
                selected_lines.append(self._slice_text(text, start[1], end[1]))
                continue
            if row_index == start[0]:
                selected_lines.append(self._slice_text(text, start[1], None))
                continue
            if row_index == end[0]:
                selected_lines.append(self._slice_text(text, 0, end[1]))
                continue
            selected_lines.append(text)
        return "\n".join(selected_lines)

    def scroll_up_lines(self, count: int = 1) -> None:
        rows = self._rows()
        if not rows:
            return
        max_offset = max(0, len(rows) - self._viewport_step())
        self._viewport_offset = min(
            max_offset, self._viewport_offset + max(1, int(count))
        )
        self._refresh_view()

    def scroll_down_lines(self, count: int = 1) -> None:
        if self._viewport_offset == 0:
            return
        self._viewport_offset = max(0, self._viewport_offset - max(1, int(count)))
        self._refresh_view()

    def select_line(self, line_index: int, *, extend: bool = False) -> bool:
        rows = self._rows()
        if not rows:
            return False
        normalized_line = max(0, min(len(rows) - 1, int(line_index)))
        self._select_line_range(normalized_line, extend=extend)
        return True

    def _select_line_range(self, line_index: int, *, extend: bool) -> None:
        rows = self._rows()
        if not rows:
            return
        normalized_line = max(0, min(len(rows) - 1, int(line_index)))
        end_col = self._line_selection_end_col(rows[normalized_line])
        if not extend or self._selection_anchor is None:
            self._selection_anchor = (normalized_line, 0)
            self._selection_focus = (normalized_line, end_col)
        else:
            anchor_row = max(0, min(len(rows) - 1, self._selection_anchor[0]))
            anchor_end_col = self._line_selection_end_col(rows[anchor_row])
            if normalized_line < anchor_row:
                self._selection_anchor = (anchor_row, anchor_end_col)
                self._selection_focus = (normalized_line, 0)
            else:
                self._selection_anchor = (anchor_row, 0)
                self._selection_focus = (normalized_line, end_col)
        self._scroll_to_line(normalized_line)
        self._refresh_view()

    def _refresh_view(self) -> None:
        rows = self._rows()
        if not rows:
            self.update(self._placeholder)
            return
        start, end = self._visible_window(rows)
        visible_rows = rows[start:end]
        renderable = Text()
        row_offsets: list[tuple[int, tuple[TerminalCell, ...]]] = []
        for index, row in enumerate(visible_rows):
            row_offsets.append((len(renderable.plain), row))
            self._append_row(renderable, row)
            if index < len(visible_rows) - 1:
                renderable.append("\n")
        self._highlighter.highlight(renderable)
        self._apply_search_highlights(renderable, row_offsets, start)
        self._apply_selection_highlights(renderable, row_offsets, start)
        self._apply_cursor_highlight(renderable, row_offsets, start)
        self.update(renderable)

    def _rows(self) -> list[tuple[TerminalCell, ...]]:
        snapshot = self._buffer.snapshot()
        rows = list(snapshot.render_rows())
        if not rows:
            rows = [tuple()]
        texts = [self._row_text(row) for row in rows]
        trimmed_rows: list[tuple[TerminalCell, ...]] = []
        total = 0
        for row, text in zip(reversed(rows), reversed(texts)):
            contribution = max(1, len(text)) + 1
            if trimmed_rows and total + contribution > self._max_chars:
                break
            trimmed_rows.append(row)
            total += contribution
        trimmed_rows.reverse()
        self._row_base_offset = max(0, len(rows) - len(trimmed_rows))
        return trimmed_rows or [tuple()]

    def _row_texts(self) -> list[str]:
        return [self._row_text(row) for row in self._rows()]

    def _trimmed_row_texts(self) -> list[str]:
        texts = self._row_texts()
        while texts and texts[-1] == "":
            texts.pop()
        return texts or [""]

    @staticmethod
    def _row_text(row: tuple[TerminalCell, ...]) -> str:
        return "".join(cell.text for cell in row if cell.width != 0).rstrip()

    def _viewport_step(self) -> int:
        size = getattr(self, "size", None)
        height = getattr(size, "height", 0) if size is not None else 0
        if height <= 0:
            content_size = getattr(self, "content_size", None)
            height = (
                getattr(content_size, "height", 0) if content_size is not None else 0
            )
        return max(1, int(height) if height else 10)

    def _visible_window(
        self, rows: list[tuple[TerminalCell, ...]] | None = None
    ) -> tuple[int, int]:
        if rows is None:
            rows = self._rows()
        end = len(rows) - self._viewport_offset if self._viewport_offset else len(rows)
        start = max(0, end - self._viewport_step())
        return start, end

    def _refresh_search_matches(self) -> None:
        query = self._search_query
        if not isinstance(query, str) or not query:
            self._search_matches = []
            self._active_match_index = -1
            return
        lowered_query = query.lower()
        matches: list[TerminalSearchMatch] = []
        for row_index, text in enumerate(self._trimmed_row_texts()):
            lowered = text.lower()
            start = 0
            while True:
                match_start = lowered.find(lowered_query, start)
                if match_start < 0:
                    break
                matches.append(
                    TerminalSearchMatch(
                        row=row_index,
                        start_col=match_start,
                        end_col=match_start + len(query),
                        query=query,
                    )
                )
                start = match_start + max(1, len(query))
        self._search_matches = matches
        if not self._search_matches:
            self._active_match_index = -1
            return
        if self._active_match_index < 0:
            self._active_match_index = 0
            return
        self._active_match_index = min(
            self._active_match_index, len(self._search_matches) - 1
        )

    def _active_match(self) -> TerminalSearchMatch | None:
        if self._active_match_index < 0 or self._active_match_index >= len(
            self._search_matches
        ):
            return None
        return self._search_matches[self._active_match_index]

    def _scroll_to_match(self, line_index: int) -> None:
        rows = self._rows()
        if not rows:
            self._viewport_offset = 0
            return
        self._scroll_to_line(line_index)

    def _scroll_to_line(self, line_index: int) -> None:
        rows = self._rows()
        if not rows:
            self._viewport_offset = 0
            return
        step = self._viewport_step()
        end = min(len(rows), max(step, line_index + 1))
        start = max(0, end - step)
        self._viewport_offset = max(0, len(rows) - (start + step))

    def _default_selection_line(self) -> int:
        active_match = self._active_match()
        if active_match is not None:
            return active_match.row
        rows = self._rows()
        texts = self._trimmed_row_texts()
        if not rows:
            return 0
        end = len(rows) - self._viewport_offset if self._viewport_offset else len(rows)
        candidate = max(0, min(len(texts), end) - 1)
        while candidate > 0 and texts[candidate] == "":
            candidate -= 1
        return candidate

    def _selection_range(self) -> tuple[Position, Position] | None:
        if self._selection_anchor is None or self._selection_focus is None:
            return None
        if self._selection_anchor <= self._selection_focus:
            return self._selection_anchor, self._selection_focus
        return self._selection_focus, self._selection_anchor

    def _clamp_selection(self) -> None:
        rows = self._rows()
        if not rows:
            self._selection_anchor = None
            self._selection_focus = None
            return
        row_limit = len(rows) - 1
        self._selection_anchor = self._clamp_position(
            self._selection_anchor, rows, row_limit
        )
        self._selection_focus = self._clamp_position(
            self._selection_focus, rows, row_limit
        )

    def _clamp_position(
        self,
        position: Position | None,
        rows: list[tuple[TerminalCell, ...]],
        row_limit: int,
    ) -> Position | None:
        if position is None:
            return None
        row = max(0, min(row_limit, position[0]))
        col_limit = self._line_selection_end_col(rows[row])
        col = max(0, min(col_limit, position[1]))
        return row, col

    @staticmethod
    def _shift_position(position: Position | None, delta_rows: int) -> Position | None:
        if position is None:
            return None
        return position[0] + delta_rows, position[1]

    @staticmethod
    def _line_selection_end_col(row: tuple[TerminalCell, ...]) -> int:
        last_content_column = 0
        found_content = False
        for index, cell in enumerate(row):
            if cell.width == 0:
                continue
            if (cell.text or " ").strip():
                last_content_column = index
                found_content = True
        return last_content_column if found_content else 0

    def _line_from_y(self, y: int) -> int | None:
        rows = self._rows()
        if not rows:
            return None
        start, end = self._visible_window(rows)
        visible_count = max(0, end - start)
        if visible_count <= 0:
            return None
        normalized_y = max(0, min(visible_count - 1, int(y)))
        return start + normalized_y

    def _position_from_pointer(self, x: int, y: int) -> Position | None:
        line_index = self._line_from_y(y)
        if line_index is None:
            return None
        rows = self._rows()
        row = rows[line_index]
        visible_columns = [index for index, cell in enumerate(row) if cell.width != 0]
        if not visible_columns:
            return line_index, 0
        normalized_x = max(0, min(len(visible_columns) - 1, int(x)))
        return line_index, visible_columns[normalized_x]

    @staticmethod
    def _slice_text(text: str, start: int, end: int | None) -> str:
        if not text:
            return ""
        normalized_start = max(0, min(len(text), start))
        if end is None:
            return text[normalized_start:]
        normalized_end = max(normalized_start, min(len(text) - 1, end))
        return text[normalized_start : normalized_end + 1]

    def _append_row(self, renderable: Text, row: tuple[TerminalCell, ...]) -> None:
        if not row:
            return
        for cell in row:
            if cell.width == 0 and not cell.text:
                continue
            renderable.append(cell.text or " ", style=self._style_for_cell(cell))

    @staticmethod
    def _style_for_cell(cell: TerminalCell) -> str:
        tokens: list[str] = []
        if cell.bold:
            tokens.append("bold")
        if cell.italic:
            tokens.append("italic")
        if cell.underline:
            tokens.append("underline")
        if cell.reverse:
            tokens.append("reverse")
        if cell.fg:
            tokens.append(cell.fg)
        if cell.bg:
            tokens.append(f"on {cell.bg}")
        return " ".join(tokens)

    def _apply_search_highlights(
        self,
        renderable: Text,
        row_offsets: list[tuple[int, tuple[TerminalCell, ...]]],
        start_row: int,
    ) -> None:
        if not self._search_matches:
            return
        active_match = self._active_match()
        for match in self._search_matches:
            local_row = match.row - start_row
            if local_row < 0 or local_row >= len(row_offsets):
                continue
            row_start, row = row_offsets[local_row]
            start = row_start + self._text_offset_for_col(row, match.start_col)
            end = row_start + self._text_offset_for_col(row, match.end_col)
            style = (
                "bold #071219 on #ffcf8c"
                if active_match == match
                else "#071219 on #f5aa67"
            )
            if end > start:
                renderable.stylize(style, start, end)

    def _apply_selection_highlights(
        self,
        renderable: Text,
        row_offsets: list[tuple[int, tuple[TerminalCell, ...]]],
        start_row: int,
    ) -> None:
        selection = self._selection_range()
        if selection is None:
            return
        start, end = selection
        for absolute_row in range(start[0], end[0] + 1):
            local_row = absolute_row - start_row
            if local_row < 0 or local_row >= len(row_offsets):
                continue
            row_start, row = row_offsets[local_row]
            row_end_col = self._line_selection_end_col(row)
            segment_start = start[1] if absolute_row == start[0] else 0
            segment_end = end[1] if absolute_row == end[0] else row_end_col
            segment_start = max(0, min(row_end_col, segment_start))
            segment_end = max(segment_start, min(row_end_col, segment_end))
            span_start = row_start + self._text_offset_for_col(row, segment_start)
            span_end = row_start + self._text_offset_for_col(row, segment_end + 1)
            if span_end > span_start:
                renderable.stylize("#061117 on #8ef2d1", span_start, span_end)

    def _apply_cursor_highlight(
        self,
        renderable: Text,
        row_offsets: list[tuple[int, tuple[TerminalCell, ...]]],
        start_row: int,
    ) -> None:
        snapshot = self._buffer.snapshot()
        if not snapshot.cursor.visible:
            return
        absolute_cursor_row = (
            len(snapshot.scrollback_cells)
            + max(0, snapshot.cursor.row)
            - self._row_base_offset
        )
        local_row = absolute_cursor_row - start_row
        if local_row < 0 or local_row >= len(row_offsets):
            return
        row_start, row = row_offsets[local_row]
        if not row:
            return
        col = max(0, min(len(row) - 1, snapshot.cursor.col))
        span_start = row_start + self._text_offset_for_col(row, col)
        span_end = row_start + self._text_offset_for_col(row, col + 1)
        if span_end <= span_start:
            span_end = span_start + 1
        renderable.stylize("reverse", span_start, span_end)

    @staticmethod
    def _text_offset_for_col(row: tuple[TerminalCell, ...], col: int) -> int:
        if col <= 0:
            return 0
        offset = 0
        limit = min(len(row), col)
        for cell in row[:limit]:
            if cell.width == 0 and not cell.text:
                continue
            offset += len(cell.text or " ")
        return offset

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        self.scroll_up_lines()
        event.stop()

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        self.scroll_down_lines()
        event.stop()

    def on_mouse_down(self, event: events.MouseDown) -> None:
        position = self._position_from_pointer(event.x, event.y)
        if position is None:
            return
        self._drag_selection_active = True
        if not getattr(event, "shift", False):
            self._selection_anchor = position
        elif self._selection_anchor is None:
            self._selection_anchor = position
        self._selection_focus = position
        self._scroll_to_line(position[0])
        self._refresh_view()
        event.stop()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if not self._drag_selection_active:
            return
        position = self._position_from_pointer(event.x, event.y)
        if position is None:
            return
        self._selection_focus = position
        self._scroll_to_line(position[0])
        self._refresh_view()
        event.stop()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        self._drag_selection_active = False
        event.stop()
