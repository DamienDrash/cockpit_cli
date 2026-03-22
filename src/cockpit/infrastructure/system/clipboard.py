"""Clipboard integration for Linux desktop environments."""

from __future__ import annotations

from collections.abc import Sequence
import subprocess


class ClipboardError(RuntimeError):
    """Raised when no clipboard backend could be used."""


class ClipboardService:
    """Copy text into the system clipboard using common Linux tools."""

    def __init__(
        self,
        runner: object | None = None,
        candidates: Sequence[Sequence[str]] | None = None,
    ) -> None:
        self._runner = runner or subprocess.run
        self._candidates = tuple(
            candidates
            or (
                ("wl-copy",),
                ("xclip", "-selection", "clipboard"),
                ("xsel", "--clipboard", "--input"),
            )
        )

    def copy_text(self, text: str) -> str:
        for command in self._candidates:
            try:
                result = self._runner(
                    list(command),
                    input=text,
                    check=False,
                    capture_output=True,
                    text=True,
                )
            except FileNotFoundError:
                continue
            if getattr(result, "returncode", 1) == 0:
                return " ".join(command)
        raise ClipboardError(
            "No clipboard backend succeeded. Install wl-copy, xclip, or xsel."
        )
