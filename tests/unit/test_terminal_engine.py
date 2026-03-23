import unittest

from cockpit.terminal.bindings.libvterm_ffi import libvterm_available
from cockpit.terminal.engine.fallback import FallbackTerminalEngine
from cockpit.terminal.engine.libvterm_engine import LibVTermTerminalEngine
from cockpit.ui.widgets.terminal_buffer import TerminalBuffer


class FallbackTerminalEngineTests(unittest.TestCase):
    def test_snapshot_tracks_screen_text_and_cursor(self) -> None:
        engine = FallbackTerminalEngine()

        engine.feed("alpha\nbeta")
        snapshot = engine.snapshot()

        self.assertEqual(snapshot.lines, ("alpha", "beta"))
        self.assertEqual(snapshot.cursor.row, 1)
        self.assertEqual(snapshot.cursor.col, 4)

    def test_alternate_screen_is_reflected_in_snapshot(self) -> None:
        engine = FallbackTerminalEngine()

        engine.feed("primary\n")
        engine.feed("\x1b[?1049h")
        engine.feed("alternate")

        alternate_snapshot = engine.snapshot()
        self.assertTrue(alternate_snapshot.alternate_screen_active)
        self.assertIn("alternate", alternate_snapshot.render_text())

        engine.feed("\x1b[?1049l")
        restored_snapshot = engine.snapshot()
        self.assertFalse(restored_snapshot.alternate_screen_active)
        self.assertIn("primary", restored_snapshot.render_text())


class TerminalBufferCompatibilityTests(unittest.TestCase):
    def test_wrapper_exposes_engine_snapshot_and_render_text(self) -> None:
        buffer = TerminalBuffer()

        buffer.feed("hello\rworld\n")

        self.assertIn("world", buffer.render_text())
        self.assertEqual(buffer.snapshot().cursor.row, 1)


@unittest.skipUnless(libvterm_available(), "compiled libvterm module is required")
class LibVTermTerminalEngineTests(unittest.TestCase):
    def test_transcript_scrollback_tracks_normal_shell_output(self) -> None:
        engine = LibVTermTerminalEngine(rows=4, cols=40)

        engine.feed("".join(f"line {index}\n" for index in range(1, 8)))
        snapshot = engine.snapshot()

        self.assertEqual(snapshot.scrollback, ("line 1", "line 2", "line 3", "line 4"))
        self.assertEqual(snapshot.lines[-1], "line 7")

    def test_alternate_screen_keeps_normal_scrollback(self) -> None:
        engine = LibVTermTerminalEngine(rows=4, cols=40)

        engine.feed("alpha\nbeta\n")
        engine.feed("\x1b[?1049h")
        engine.feed("top\nview\n")
        snapshot = engine.snapshot()

        self.assertTrue(snapshot.alternate_screen_active)
        self.assertIn("alpha", "\n".join(snapshot.scrollback))
        self.assertIn("top", "\n".join(snapshot.lines))


if __name__ == "__main__":
    unittest.main()
