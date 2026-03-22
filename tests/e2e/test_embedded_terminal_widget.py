import importlib.util
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

    @staticmethod
    def _rendered_text(widget: object) -> str:
        renderable = getattr(widget, "renderable", None)
        if renderable is not None:
            return str(renderable)
        return str(getattr(widget, "render")())


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
