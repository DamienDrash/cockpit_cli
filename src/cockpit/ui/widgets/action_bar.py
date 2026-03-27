"""Kontextsensitive Action-Bar widget for F-key shortcuts."""

from rich.text import Text
from textual.app import RenderResult
from textual.widgets import Static

from cockpit.ui.branding import C_PRIMARY, C_SECONDARY


class ActionBar(Static):
    """Context-aware F-key shortcut bar."""

    def __init__(self) -> None:
        super().__init__(id="action-bar")
        self._panel_id: str = ""
        self._panel_type: str = ""

    def set_context(self, panel_id: str, panel_type: str) -> None:
        """Update action bar based on current focused panel."""
        self._panel_id = panel_id
        self._panel_type = panel_type
        self.refresh()

    def render(self) -> RenderResult:
        """Render the F-key bar with cyberpunk styling."""
        actions = self._get_actions_for_panel()
        
        renderable = Text()
        for i, (key, label) in enumerate(actions):
            renderable.append(f" {key} ", style=f"bold black on {C_PRIMARY}")
            renderable.append(f" {label} ", style=f"bold {C_PRIMARY} on #1a1a2e")
            if i < len(actions) - 1:
                renderable.append("  ")
        
        return renderable

    def _get_actions_for_panel(self) -> list[tuple[str, str]]:
        """Map panel types to specific F-key actions."""
        # Common actions
        common = [("F1", "Help"), ("F12", "Settings")]
        
        panel_specific: list[tuple[str, str]] = []
        
        if self._panel_type == "db":
            panel_specific = [("F5", "Execute"), ("F6", "Clear"), ("F7", "Snippets")]
        elif self._panel_type == "curl":
            panel_specific = [("F5", "Send"), ("F6", "Headers"), ("F7", "Export")]
        elif self._panel_type == "ops":
            panel_specific = [("F5", "Analyze"), ("F6", "Escalate"), ("F7", "Policies")]
        elif self._panel_type == "docker":
            panel_specific = [("F8", "Restart"), ("F9", "Stop"), ("F10", "Remove")]
        elif self._panel_type == "response":
            panel_specific = [("F5", "Start"), ("F6", "Retry"), ("F7", "Abort")]
        
        return panel_specific or common
