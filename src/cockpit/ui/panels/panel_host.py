"""Workspace panel host."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical

from cockpit.bootstrap import ApplicationContainer
from cockpit.domain.models.panel_state import PanelState
from cockpit.ui.panels.registry import PanelContract


class PanelHost(Vertical):
    """Hosts the reference panel set for the first application slice."""

    def __init__(self, *, container: ApplicationContainer) -> None:
        super().__init__(id="panel-host")
        self._container = container
        self._panels_by_id = self._container.panel_registry.create_panels(container)
        self._active_tab_id = "work"
        self._layout_id = "default"
        self._tabs: list[dict[str, str]] = [
            {
                "id": "work",
                "name": "Work",
                "panel_id": "work-panel",
                "panel_type": "work",
            }
        ]

    def compose(self) -> ComposeResult:
        for panel in self._panels_by_id.values():
            yield panel

    def load_workspace(self, context: dict[str, object]) -> None:
        layout_id = context.get("layout_id")
        if isinstance(layout_id, str) and layout_id:
            self._layout_id = layout_id
        self._tabs = self._normalize_tabs(context.get("tabs"))
        snapshot = context.get("snapshot")
        panel_snapshots = self._panel_snapshots(snapshot if isinstance(snapshot, dict) else {})
        for panel_id, panel in self._panels_by_id.items():
            panel_context = dict(context)
            panel_context.update(panel_snapshots.get(panel_id, {}))
            panel.initialize(panel_context)
        active_tab_id = context.get("active_tab_id")
        self.set_active_tab(
            str(active_tab_id) if isinstance(active_tab_id, str) and active_tab_id else "work",
            focus=False,
        )

    def focus_terminal(self) -> None:
        panel = self._panels_by_id.get("work-panel")
        focus_terminal = getattr(panel, "focus_terminal", None)
        if callable(focus_terminal):
            focus_terminal()

    def command_context(self) -> dict[str, object]:
        context = self._active_panel().command_context()
        context["layout_id"] = self._layout_id
        context["active_tab_id"] = self._active_tab_id
        context["available_tab_ids"] = [tab["id"] for tab in self._tabs]
        return context

    def snapshot_state(self) -> PanelState:
        panels = self._panels()
        active_state = self._active_panel().snapshot_state()
        panel_snapshots = {
            panel.PANEL_ID: panel.snapshot_state().snapshot
            for panel in panels
        }
        work_snapshot = panel_snapshots.get("work-panel", {})
        snapshot = dict(active_state.snapshot)
        if "cwd" in work_snapshot:
            snapshot["cwd"] = work_snapshot["cwd"]
        if "browser_path" in work_snapshot:
            snapshot["browser_path"] = work_snapshot["browser_path"]
        snapshot["panels"] = panel_snapshots
        snapshot["active_tab_id"] = self._active_tab_id
        return PanelState(
            panel_id=active_state.panel_id,
            panel_type=active_state.panel_type,
            snapshot=snapshot,
            config=dict(active_state.config),
            persist_policy=active_state.persist_policy,
        )

    def set_active_tab(self, tab_id: str, *, focus: bool = True) -> str:
        panels = self._tab_panels()
        next_tab = tab_id if tab_id in panels else self._tabs[0]["id"]
        self._active_tab_id = next_tab
        active_panel = panels[next_tab]
        for panel in self._panels():
            panel.display = panel is active_panel
        panels[next_tab].resume()
        if focus:
            panels[next_tab].focus()
        return next_tab

    def active_tab_id(self) -> str:
        return self._active_tab_id

    def shutdown(self) -> None:
        for panel in self._panels():
            panel.dispose()

    def available_tabs(self) -> list[tuple[str, str]]:
        return [(tab["id"], tab["name"]) for tab in self._tabs]

    def refresh_panel(self, panel_id: str) -> None:
        panel = self._panels_by_id.get(panel_id)
        if panel is not None:
            panel.resume()

    def _active_panel(self) -> PanelContract:
        active_panel_id = self._tab_panel_id(self._active_tab_id)
        panel = self._panels_by_id.get(active_panel_id)
        if panel is not None:
            return panel
        return next(iter(self._panels_by_id.values()))

    def _panels(self) -> list[PanelContract]:
        return list(self._panels_by_id.values())

    def _panel_snapshots(self, snapshot: dict[str, object]) -> dict[str, dict[str, object]]:
        raw_panels = snapshot.get("panels", {})
        if not isinstance(raw_panels, dict):
            raw_panels = {}
        panel_snapshots: dict[str, dict[str, object]] = {}
        for panel_id, payload in raw_panels.items():
            if isinstance(panel_id, str) and isinstance(payload, dict):
                panel_snapshots[panel_id] = payload
        if "work-panel" not in panel_snapshots:
            panel_snapshots["work-panel"] = {
                key: value
                for key, value in snapshot.items()
                if key in {"cwd", "browser_path", "selected_path"}
            }
        return panel_snapshots

    def _normalize_tabs(self, raw_tabs: object) -> list[dict[str, str]]:
        if not isinstance(raw_tabs, list):
            return list(self._tabs)
        tabs: list[dict[str, str]] = []
        for raw_tab in raw_tabs:
            if not isinstance(raw_tab, dict):
                continue
            tab_id = raw_tab.get("id")
            panel_id = raw_tab.get("panel_id")
            panel_type = raw_tab.get("panel_type")
            if not isinstance(tab_id, str) or not isinstance(panel_id, str):
                continue
            tabs.append(
                {
                    "id": tab_id,
                    "name": str(raw_tab.get("name", tab_id.title())),
                    "panel_id": panel_id,
                    "panel_type": str(panel_type or tab_id),
                }
            )
        return tabs or list(self._tabs)

    def _tab_panels(self) -> dict[str, PanelContract]:
        tabs: dict[str, PanelContract] = {}
        for tab in self._tabs:
            panel = self._panels_by_id.get(tab["panel_id"])
            if panel is not None:
                tabs[tab["id"]] = panel
        if "work" not in tabs:
            work_panel = self._panels_by_id.get("work-panel")
            if work_panel is not None:
                tabs["work"] = work_panel
        return tabs

    def _tab_panel_id(self, tab_id: str) -> str:
        for tab in self._tabs:
            if tab["id"] == tab_id:
                return tab["panel_id"]
        return "work-panel"
