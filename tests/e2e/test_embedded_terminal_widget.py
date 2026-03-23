import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

TEXTUAL_AVAILABLE = importlib.util.find_spec("textual") is not None

if TEXTUAL_AVAILABLE:
    from textual.app import App, ComposeResult

    from cockpit.ui.widgets.embedded_terminal import EmbeddedTerminal


@unittest.skipUnless(TEXTUAL_AVAILABLE, "textual must be installed for embedded terminal tests")
class EmbeddedTerminalWidgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_viewport_navigation_preserves_scrollback_until_scrolled_to_end(self) -> None:
        app = TerminalWidgetTestApp()

        async with app.run_test(size=(80, 8)) as pilot:
            terminal = app.query_one(EmbeddedTerminal)
            terminal.clear("ready")
            terminal.append_output("".join(f"line {index}\n" for index in range(1, 31)))
            await pilot.pause()

            latest_render = self._rendered_text(terminal)
            self.assertIn("line 30", latest_render)
            self.assertNotIn("line 1", latest_render)

            terminal.page_up()
            await pilot.pause()

            paged_render = self._rendered_text(terminal)
            self.assertGreater(terminal.viewport_offset(), 0)
            self.assertIn("line 16", paged_render)
            self.assertNotIn("line 30", paged_render)

            terminal.append_output("tail line\n")
            await pilot.pause()

            frozen_render = self._rendered_text(terminal)
            self.assertNotIn("tail line", frozen_render)

            terminal.scroll_to_end()
            await pilot.pause()

            resumed_render = self._rendered_text(terminal)
            self.assertEqual(terminal.viewport_offset(), 0)
            self.assertIn("tail line", resumed_render)

    async def test_status_message_is_appended_into_terminal_buffer(self) -> None:
        app = TerminalWidgetTestApp()

        async with app.run_test(size=(80, 8)) as pilot:
            terminal = app.query_one(EmbeddedTerminal)
            terminal.clear("ready")
            terminal.append_output("alpha\nbeta\n")
            terminal.set_status("\n[terminal exited with 0]")
            await pilot.pause()

            self.assertIn("[terminal exited with 0]", terminal.current_output())
            self.assertIn("[terminal exited with 0]", self._rendered_text(terminal))

    async def test_carriage_return_rewrites_the_current_line(self) -> None:
        app = TerminalWidgetTestApp()

        async with app.run_test(size=(80, 8)) as pilot:
            terminal = app.query_one(EmbeddedTerminal)
            terminal.clear("ready")
            terminal.append_output("progress 10%\rprogress 90%\n")
            await pilot.pause()

            self.assertIn("progress 90%", terminal.current_output())
            self.assertNotIn("progress 10%", self._rendered_text(terminal))

    async def test_backspace_updates_the_current_line(self) -> None:
        app = TerminalWidgetTestApp()

        async with app.run_test(size=(80, 8)) as pilot:
            terminal = app.query_one(EmbeddedTerminal)
            terminal.clear("ready")
            terminal.append_output("helo\blo\n")
            await pilot.pause()

            self.assertIn("hello", terminal.current_output())
            self.assertIn("hello", self._rendered_text(terminal))

    async def test_csi_clear_line_erases_the_previous_tail(self) -> None:
        app = TerminalWidgetTestApp()

        async with app.run_test(size=(80, 8)) as pilot:
            terminal = app.query_one(EmbeddedTerminal)
            terminal.clear("ready")
            terminal.append_output("alpha beta\x1b[1G\x1b[0Komega\n")
            await pilot.pause()

            self.assertIn("omega", terminal.current_output())
            self.assertNotIn("alpha beta", terminal.current_output())

    async def test_alternate_screen_restores_primary_buffer(self) -> None:
        app = TerminalWidgetTestApp()

        async with app.run_test(size=(80, 8)) as pilot:
            terminal = app.query_one(EmbeddedTerminal)
            terminal.clear("ready")
            terminal.append_output("primary\n")
            terminal.append_output("\x1b[?1049h")
            terminal.append_output("alternate\n")
            terminal.append_output("\x1b[?1049l")
            await pilot.pause()

            rendered = terminal.current_output()
            self.assertIn("primary", rendered)
            self.assertNotIn("alternate", rendered)

    async def test_search_moves_view_to_matching_line(self) -> None:
        app = TerminalWidgetTestApp()

        async with app.run_test(size=(80, 8)) as pilot:
            terminal = app.query_one(EmbeddedTerminal)
            terminal.clear("ready")
            terminal.append_output("alpha\nbeta\nerror: failed\nomega\n")
            await pilot.pause()

            found = terminal.search("error")
            await pilot.pause()

            self.assertTrue(found)
            self.assertIn("error: failed", self._rendered_text(terminal))
            self.assertFalse(self._rendered_text(terminal).startswith("> "))
            self.assertGreater(len(self._rendered_spans(terminal)), 0)

    async def test_export_writes_terminal_buffer_to_file(self) -> None:
        app = TerminalWidgetTestApp()

        async with app.run_test(size=(80, 8)) as pilot:
            terminal = app.query_one(EmbeddedTerminal)
            terminal.clear("ready")
            terminal.append_output("alpha\nbeta\n")
            await pilot.pause()

            with TemporaryDirectory() as temp_dir:
                target = Path(temp_dir) / "terminal.txt"
                terminal.export_text(target)
                self.assertEqual(target.read_text(encoding="utf-8"), "alpha\nbeta")

    async def test_selection_marks_lines_and_returns_selected_text(self) -> None:
        app = TerminalWidgetTestApp()

        async with app.run_test(size=(80, 8)) as pilot:
            terminal = app.query_one(EmbeddedTerminal)
            terminal.clear("ready")
            terminal.append_output("alpha\nbeta\ngamma\ndelta\n")
            await pilot.pause()

            self.assertTrue(terminal.toggle_selection())
            self.assertTrue(terminal.expand_selection(-2))
            await pilot.pause()

            rendered = self._rendered_text(terminal)
            self.assertIn("delta", rendered)
            self.assertIn("gamma", rendered)
            self.assertNotIn("* delta", rendered)
            self.assertEqual(terminal.selected_text(), "beta\ngamma\ndelta")
            self.assertGreater(len(self._rendered_spans(terminal)), 0)

    async def test_direct_selection_and_scroll_helpers_update_view(self) -> None:
        app = TerminalWidgetTestApp()

        async with app.run_test(size=(80, 8)) as pilot:
            terminal = app.query_one(EmbeddedTerminal)
            terminal.clear("ready")
            terminal.append_output("".join(f"line {index}\n" for index in range(1, 21)))
            await pilot.pause()

            terminal.scroll_up_lines(3)
            terminal.select_line(10)
            terminal.select_line(12, extend=True)
            await pilot.pause()

            self.assertGreater(terminal.viewport_offset(), 0)
            self.assertEqual(terminal.selected_text(), "line 11\nline 12\nline 13")

    @staticmethod
    def _rendered_text(widget: object) -> str:
        renderable = getattr(widget, "renderable", None)
        if renderable is not None and hasattr(renderable, "plain"):
            return str(getattr(renderable, "plain"))
        rendered = getattr(widget, "render")()
        if hasattr(rendered, "plain"):
            return str(getattr(rendered, "plain"))
        return str(rendered)

    @staticmethod
    def _rendered_spans(widget: object) -> list[object]:
        renderable = getattr(widget, "renderable", None)
        if renderable is not None and hasattr(renderable, "spans"):
            return list(getattr(renderable, "spans"))
        rendered = getattr(widget, "render")()
        if hasattr(rendered, "spans"):
            return list(getattr(rendered, "spans"))
        return []


if TEXTUAL_AVAILABLE:
    class TerminalWidgetTestApp(App[None]):
        CSS = """
        Screen {
            layout: vertical;
        }

        #embedded-terminal {
            height: 1fr;
        }
        """

        def compose(self) -> ComposeResult:
            yield EmbeddedTerminal()


if __name__ == "__main__":
    unittest.main()
