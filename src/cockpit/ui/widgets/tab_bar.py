"""Tab bar widget."""

from __future__ import annotations

from textual.widgets import Static

from cockpit.shared.enums import TargetRiskLevel
from cockpit.shared.risk import RiskPresentation, risk_presentation


class TabBar(Static):
    """Simple stateful tab bar for the first multi-tab slice."""

    def __init__(self) -> None:
        self._workspace_name = "none"
        self._restored = False
        self._active_tab_id = "work"
        self._target_label = "local"
        self._risk_level = TargetRiskLevel.DEV
        self._tabs: list[tuple[str, str]] = [("work", "Work")]
        super().__init__("", id="tab-bar", markup=False)
        self._apply_risk_style()
        self._render_state()

    def set_tabs(self, tabs: list[tuple[str, str]]) -> None:
        self._tabs = tabs or [("work", "Work")]
        if self._active_tab_id not in {tab_id for tab_id, _name in self._tabs}:
            self._active_tab_id = self._tabs[0][0]
        self._render_state()

    def set_workspace(
        self,
        workspace_name: str,
        *,
        restored: bool,
        active_tab_id: str = "work",
        target_label: str = "local",
        risk_level: TargetRiskLevel = TargetRiskLevel.DEV,
    ) -> None:
        self._workspace_name = workspace_name
        self._restored = restored
        self._active_tab_id = active_tab_id
        self._target_label = target_label
        self._risk_level = risk_level
        self._apply_risk_style()
        self._render_state()

    def set_active_tab(self, tab_id: str) -> None:
        self._active_tab_id = tab_id
        self._render_state()

    def _render_state(self) -> None:
        tabs = " ".join(
            f"[{name}]" if tab_id == self._active_tab_id else name
            for tab_id, name in self._tabs
        )
        state = "restored" if self._restored else "fresh"
        presentation = risk_presentation(self._risk_level)
        self.update(
            " | ".join(
                (
                    f"Tabs: {tabs}",
                    f"Workspace: {self._workspace_name}",
                    f"Target: {self._target_label}",
                    f"Risk: {presentation.label}",
                    f"Session: {state}",
                )
            )
        )

    def _apply_risk_style(self) -> None:
        presentation: RiskPresentation = risk_presentation(self._risk_level)
        self.styles.background = presentation.background
        self.styles.color = presentation.color
