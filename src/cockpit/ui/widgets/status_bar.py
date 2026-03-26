"""Cyberpunk-themed status bar widget."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from cockpit.shared.enums import StatusLevel, TargetRiskLevel
from cockpit.shared.risk import RiskPresentation, risk_presentation
from cockpit.ui.branding import C_PRIMARY, C_SECONDARY


class StatusBar(Static):
    """Refined status bar with Cyberpunk aesthetics."""

    def __init__(self) -> None:
        self._target_label = "local"
        self._risk_level = TargetRiskLevel.DEV
        self._last_message = "Ready"
        self._last_level = StatusLevel.INFO
        super().__init__("", id="status-bar")
        self._render_state()

    def set_message(self, message: str, level: StatusLevel = StatusLevel.INFO) -> None:
        self._last_message = message
        self._last_level = level
        self._render_state()

    def set_context(
        self,
        *,
        target_label: str,
        risk_level: TargetRiskLevel,
    ) -> None:
        self._target_label = target_label
        self._risk_level = risk_level
        self._render_state()

    def _render_state(self) -> None:
        presentation = risk_presentation(self._risk_level)
        
        status_text = Text()
        
        # Risk & Target Section
        status_text.append(" ◆ ", style=C_PRIMARY)
        status_text.append(f"{self._target_label.upper()}", style="bold white")
        status_text.append(" | ", style="dim white")
        status_text.append(f"{presentation.label}", style=f"bold {presentation.color} on {presentation.background}")
        status_text.append(" ❯ ", style=C_SECONDARY)
        
        # Message Section
        icon = "ℹ"
        color = "white"
        if self._last_level == StatusLevel.ERROR:
            icon = "✖"
            color = "bold #ff0055"
        elif self._last_level == StatusLevel.WARNING:
            icon = "⚠"
            color = "bold #ffff00"
        elif self._last_level == StatusLevel.SUCCESS:
            icon = "✔"
            color = "bold #00ff00"
            
        status_text.append(f"{icon} {self._last_message}", style=color)
        
        self.update(status_text)
        # We don't override self.styles.background here anymore to keep the TCSS look
