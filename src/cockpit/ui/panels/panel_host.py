"""Workspace panel host using ContentSwitcher (Gold Standard)."""

from __future__ import annotations

import copy
from collections.abc import Iterable

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import ContentSwitcher

from cockpit.bootstrap import ApplicationContainer
from cockpit.domain.models.panel_state import PanelState
from cockpit.ui.panels.registry import PanelContract


class PanelHost(Vertical):
    """Hosts all reference panels and switches between them using ContentSwitcher."""

    def __init__(self, *, container: ApplicationContainer) -> None:
        super().__init__(id="panel-host")
        self._container = container
        self._panels_by_id = self._container.panel_registry.create_panels(container)
        self._active_tab_id = "work"
        self._tabs: list[dict[str, object]] = []

    def compose(self) -> ComposeResult:
        with ContentSwitcher(initial="work-panel", id="panel-switcher"):
            # Yield all registered panels into the switcher
            for panel in self._panels_by_id.values():
                yield panel

    def on_mount(self) -> None:
        # Initial status update
        self._update_switcher()

    def load_workspace(self, context: dict[str, object]) -> None:
        self._tabs = self._normalize_tabs(context.get("tabs"))
        
        # Initialize all panels with context
        for panel_id, panel in self._panels_by_id.items():
            panel.initialize(dict(context))
            
        active_tab_id = context.get("active_tab_id") or "work"
        self.set_active_tab(str(active_tab_id), focus=False)

    def set_active_tab(self, tab_id: str, *, focus: bool = True) -> str:
        self._active_tab_id = tab_id
        self._update_switcher()
        
        if focus:
            active_panel = self._active_panel()
            if active_panel:
                active_panel.focus()
        
        return self._active_tab_id

    def _update_switcher(self) -> None:
        try:
            switcher = self.query_one("#panel-switcher", ContentSwitcher)
            # Map tab_id to panel_id (e.g., 'work' -> 'work-panel')
            target_panel_id = self._tab_panel_id(self._active_tab_id)
            if target_panel_id in self._panels_by_id:
                switcher.current = target_panel_id
                # Trigger resume on the now visible panel
                self._panels_by_id[target_panel_id].resume()
        except Exception:
            pass

    def _tab_panel_id(self, tab_id: str) -> str:
        # Check tabs list for mapping
        for tab in self._tabs:
            if tab["id"] == tab_id:
                return str(tab.get("panel_id", f"{tab_id}-panel"))
        # Fallback naming convention
        return f"{tab_id}-panel"

    def _active_panel(self) -> PanelContract | None:
        target_id = self._tab_panel_id(self._active_tab_id)
        return self._panels_by_id.get(target_id)

    def focus_terminal(self) -> None:
        panel = self._panels_by_id.get("work-panel")
        if hasattr(panel, "focus_terminal"):
            panel.focus_terminal()

    def command_context(self) -> dict[str, object]:
        active = self._active_panel()
        ctx = active.command_context() if active else {}
        ctx.update({
            "active_tab_id": self._active_tab_id,
            "available_tab_ids": [str(t["id"]) for t in self._tabs],
        })
        return ctx

    def snapshot_state(self) -> PanelState:
        active = self._active_panel()
        return active.snapshot_state() if active else PanelState(panel_id="none", panel_type="none")

    def active_tab_id(self) -> str:
        return self._active_tab_id

    def available_tabs(self) -> list[tuple[str, str]]:
        return [(str(tab["id"]), str(tab["name"])) for tab in self._tabs]

    def apply_tabs(self, tabs: list[dict[str, object]], **kwargs) -> None:
        self._tabs = self._normalize_tabs(tabs)
        self._update_switcher()

    def refresh_panel(self, panel_id: str) -> None:
        panel = self._panels_by_id.get(panel_id)
        if panel: panel.resume()

    def deliver_panel_result(self, panel_id: str, payload: dict[str, object]) -> None:
        panel = self._panels_by_id.get(panel_id)
        if panel: panel.apply_command_result(payload)

    def focus_panel(self, panel_id: str) -> None:
        panel = self._panels_by_id.get(panel_id)
        if panel: panel.focus()

    def _normalize_tabs(self, raw_tabs: object) -> list[dict[str, object]]:
        if not isinstance(raw_tabs, list): return []
        return [t for t in raw_tabs if isinstance(t, dict) and "id" in t]

    def shutdown(self) -> None:
        for panel in self._panels_by_id.values():
            panel.dispose()
