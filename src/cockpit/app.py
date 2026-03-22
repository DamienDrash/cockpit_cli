"""Top-level application entrypoint."""

from __future__ import annotations

from cockpit.ui.screens.app_shell import CockpitApp


def main() -> int:
    """Run the Cockpit application."""
    app = CockpitApp()
    app.run()
    return 0

