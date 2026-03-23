"""Terminal engine factory."""

from __future__ import annotations

from cockpit.terminal.bindings.libvterm_ffi import libvterm_available
from cockpit.terminal.engine.base import TerminalEngine
from cockpit.terminal.engine.fallback import FallbackTerminalEngine


def create_terminal_engine() -> TerminalEngine:
    """Create the active engine for the current runtime."""
    if libvterm_available():
        from cockpit.terminal.engine.libvterm_engine import LibVTermTerminalEngine

        return LibVTermTerminalEngine()
    return FallbackTerminalEngine()
