"""Status bar widget."""

from __future__ import annotations

from textual.widgets import Static

from cockpit.shared.enums import StatusLevel, TargetRiskLevel
from cockpit.shared.risk import RiskPresentation, risk_presentation


class StatusBar(Static):
    """Simple status bar for bootstrap feedback."""

    def __init__(self) -> None:
        self._target_label = "local"
        self._risk_level = TargetRiskLevel.DEV
        super().__init__("Ready", id="status-bar")
        self._apply_risk_style()

    def set_message(self, message: str, level: StatusLevel = StatusLevel.INFO) -> None:
        presentation = risk_presentation(self._risk_level)
        self.update(
            f"Target: {self._target_label} | Risk: {presentation.label} | [{level.value}] {message}"
        )

    def set_context(
        self,
        *,
        target_label: str,
        risk_level: TargetRiskLevel,
    ) -> None:
        self._target_label = target_label
        self._risk_level = risk_level
        self._apply_risk_style()

    def _apply_risk_style(self) -> None:
        presentation: RiskPresentation = risk_presentation(self._risk_level)
        self.styles.background = presentation.background
        self.styles.color = presentation.color
