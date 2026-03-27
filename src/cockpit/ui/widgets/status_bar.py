"""Cyberpunk-themed status bar widget."""

from __future__ import annotations

import random
from collections import deque

from rich.text import Text
from textual.widgets import Static

from cockpit.core.enums import StatusLevel, TargetRiskLevel
from cockpit.core.risk import risk_presentation
from cockpit.ui.branding import C_PRIMARY, C_SECONDARY


class StatusBar(Static):
    """Refined status bar with Cyberpunk aesthetics and resource sparklines."""

    def __init__(self) -> None:
        self._target_label = "local"
        self._risk_level = TargetRiskLevel.DEV
        self._last_message = "Ready"
        self._last_level = StatusLevel.INFO
        
        # Resource history for sparklines
        self._cpu_history: deque[float] = deque([0.0] * 10, maxlen=10)
        self._mem_history: deque[float] = deque([0.0] * 10, maxlen=10)
        
        super().__init__("", id="status-bar")
        self._render_state()

    def on_mount(self) -> None:
        """Start resource monitoring timer."""
        self.set_interval(2.0, self._update_resources)

    def _update_resource_usage(self) -> None:
        # Mock resource usage for now since psutil is not a dependency
        # In a real scenario, we'd use psutil.cpu_percent() etc.
        self._cpu_history.append(random.uniform(5.0, 45.0))
        self._mem_history.append(random.uniform(20.0, 60.0))
        self._render_state()

    def _update_resources(self) -> None:
        self._update_resource_usage()

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

    def _get_sparkline(self, data: deque[float]) -> Text:
        """Generate a minimalist block-based sparkline."""
        chars = " ▂▃▄▅▆▇█"
        spark = Text()
        for val in data:
            # Map 0-100 to 0-7
            idx = int(min(val, 99.0) / 12.5)
            color = "#00ff00" # default green
            if val > 80: color = "#ff0055" # red
            elif val > 50: color = "#ffff00" # yellow
            spark.append(chars[idx], style=color)
        return spark

    def _render_state(self) -> None:
        presentation = risk_presentation(self._risk_level)

        status_text = Text()

        # Risk & Target Section
        status_text.append(" ◆ ", style=C_PRIMARY)
        status_text.append(f"{self._target_label.upper()}", style="bold white")
        status_text.append(" | ", style="dim white")
        status_text.append(
            f"{presentation.label}",
            style=f"bold {presentation.color} on {presentation.background}",
        )
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

        # Resource Section (Right aligned)
        res = Text()
        res.append(" CPU ", style="dim")
        res.append(self._get_sparkline(self._cpu_history))
        res.append(" MEM ", style="dim")
        res.append(self._get_sparkline(self._mem_history))
        res.append(" ")

        available_space = self.app.size.width - len(status_text.plain) - len(res.plain) - 1
        if available_space > 0:
            status_text.append(" " * available_space)
            status_text.extend(res)

        self.update(status_text)
