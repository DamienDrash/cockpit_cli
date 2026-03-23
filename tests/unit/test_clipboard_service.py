from types import SimpleNamespace
import unittest

from cockpit.infrastructure.system.clipboard import ClipboardError, ClipboardService


class ClipboardServiceTests(unittest.TestCase):
    def test_uses_first_available_clipboard_backend(self) -> None:
        calls: list[list[str]] = []

        def runner(argv: list[str], **kwargs: object) -> SimpleNamespace:
            del kwargs
            calls.append(list(argv))
            if argv[0] == "wl-copy":
                raise FileNotFoundError(argv[0])
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        service = ClipboardService(runner=runner)

        backend = service.copy_text("hello")

        self.assertEqual(backend, "xclip -selection clipboard")
        self.assertEqual(calls[1], ["xclip", "-selection", "clipboard"])

    def test_raises_when_no_clipboard_backend_succeeds(self) -> None:
        def runner(argv: list[str], **kwargs: object) -> SimpleNamespace:
            del argv, kwargs
            return SimpleNamespace(returncode=1, stdout="", stderr="failed")

        service = ClipboardService(runner=runner, candidates=(("xclip",),))

        with self.assertRaises(ClipboardError):
            service.copy_text("hello")

    def test_reads_clipboard_from_first_available_backend(self) -> None:
        calls: list[list[str]] = []

        def runner(argv: list[str], **kwargs: object) -> SimpleNamespace:
            del kwargs
            calls.append(list(argv))
            if argv[0] == "wl-paste":
                raise FileNotFoundError(argv[0])
            return SimpleNamespace(returncode=0, stdout="pasted text", stderr="")

        service = ClipboardService(runner=runner)

        text, backend = service.read_text()

        self.assertEqual(text, "pasted text")
        self.assertEqual(backend, "xclip -selection clipboard -o")
        self.assertEqual(calls[1], ["xclip", "-selection", "clipboard", "-o"])
