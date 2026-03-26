"""Cyberpunk-themed header for Cockpit."""

from __future__ import annotations

from rich.text import Text
from textual.app import RenderResult
from textual.widgets import Header

from cockpit.ui.branding import LOGO, C_PRIMARY, C_SECONDARY


class CockpitHeader(Header):
    """Custom header with Cyberpunk branding."""

    def render(self) -> RenderResult:
        """Render the header with ASCII logo and cyberpunk colors."""
        # Use a simplified version of the logo for the header to save space
        # or just use the full logo if height allows.
        # For now, let's use a stylized text and the version.
        
        header_text = Text()
        header_text.append(" COCKPIT ", style=f"{C_PRIMARY} reverse")
        header_text.append(" v0.1.8 ", style=C_SECONDARY)
        header_text.append(" ❯ ", style="white")
        header_text.append(self.app.title, style="bold white")
        if self.app.sub_title:
            header_text.append(f" — {self.app.sub_title}", style="dim white")
            
        return header_text
