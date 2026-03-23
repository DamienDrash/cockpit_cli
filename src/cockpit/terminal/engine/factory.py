"""Terminal engine factory."""

from __future__ import annotations

import os

from cockpit.terminal.bindings.libvterm_ffi import libvterm_available
from cockpit.terminal.engine.base import TerminalEngine
from cockpit.terminal.engine.fallback import FallbackTerminalEngine


def create_terminal_engine() -> TerminalEngine:
    """Create the active engine for the current runtime.

    libvterm stays opt-in until the richer engine reaches feature parity with
    the existing scrollback and selection UX. Set
    ``COCKPIT_ENABLE_LIBVTERM=1`` to exercise the new backend locally.
    """
    enable_libvterm = os.environ.get("COCKPIT_ENABLE_LIBVTERM", "").strip().lower()
    if enable_libvterm in {"1", "true", "yes", "on"} and libvterm_available():
        from cockpit.terminal.engine.libvterm_engine import LibVTermTerminalEngine

        return LibVTermTerminalEngine()
    return FallbackTerminalEngine()
