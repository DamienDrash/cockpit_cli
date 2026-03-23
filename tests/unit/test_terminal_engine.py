import unittest

from cockpit.terminal.engine.fallback import FallbackTerminalEngine
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


if __name__ == "__main__":
    unittest.main()

