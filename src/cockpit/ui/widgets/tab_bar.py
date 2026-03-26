"""Interactive Cyberpunk Tab Bar with robust dispatch."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static, Button

from cockpit.shared.enums import TargetRiskLevel
from cockpit.ui.branding import C_PRIMARY, C_SECONDARY


class TabBar(Horizontal):
    """Stateful tab bar with clickable buttons."""

    def __init__(self) -> None:
        self._workspace_name = "none"
        self._active_tab_id = "work"
        self._tabs: list[tuple[str, str]] = [("work", "Work")]
        super().__init__(id="tab-bar")

    def compose(self) -> ComposeResult:
        with Horizontal(id="tabs-container"):
            for tab_id, name in self._tabs:
                is_active = tab_id == self._active_tab_id
                yield Button(
                    name.upper(),
                    id=f"tab-btn-{tab_id}",
                    variant="primary" if is_active else "default",
                    classes="tab-button" + (" active" if is_active else ""),
                )
        yield Static(f" [ {self._workspace_name} ] ", id="tab-workspace-info")

    def set_tabs(self, tabs: list[tuple[str, str]]) -> None:
        self._tabs = tabs or [("work", "Work")]
        # Only recompose if tabs actually changed to avoid flicker
        self.recompose()

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
        self._active_tab_id = active_tab_id
        self.recompose()

    def set_active_tab(self, tab_id: str) -> None:
        self._active_tab_id = tab_id
        # Update button styles without full recompose for performance
        for btn in self.query(".tab-button"):
            btn_tab_id = btn.id.replace("tab-btn-", "") if btn.id else ""
            if btn_tab_id == tab_id:
                btn.add_class("active")
                btn.variant = "primary"
            else:
                btn.remove_class("active")
                btn.variant = "default"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id and event.button.id.startswith("tab-btn-"):
            tab_id = event.button.id.replace("tab-btn-", "")
            
            from cockpit.domain.commands.command import Command
            from cockpit.shared.enums import CommandSource
            from cockpit.shared.utils import make_id
            
            # Use the app's internal command context
            try:
                context = self.app._command_context()
            except Exception:
                context = {}

            # Execute the focus command
            cmd = Command(
                id=make_id("cmd"),
                source=CommandSource.KEYBINDING,
                name="tab.focus",
                args={"argv": [tab_id]},
                context=context,
            )
            self.app._dispatch_command(cmd)
            event.stop()
