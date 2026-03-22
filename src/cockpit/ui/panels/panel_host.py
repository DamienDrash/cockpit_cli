"""Workspace panel host."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical

from cockpit.bootstrap import ApplicationContainer
from cockpit.domain.models.panel_state import PanelState
from cockpit.ui.panels.git_panel import GitPanel
from cockpit.ui.panels.logs_panel import LogsPanel
from cockpit.ui.panels.work_panel import WorkPanel

PanelWidget = WorkPanel | GitPanel | LogsPanel


class PanelHost(Vertical):
    """Hosts the reference panel set for the first application slice."""

    def __init__(self, *, container: ApplicationContainer) -> None:
        super().__init__(id="panel-host")
        self._container = container
        self._active_tab_id = "work"
        self._layout_id = "default"
        self._tabs: list[dict[str, str]] = [
            {
                "id": "work",
                "name": "Work",
                "panel_id": WorkPanel.PANEL_ID,
                "panel_type": WorkPanel.PANEL_TYPE,
            }
        ]

    def compose(self) -> ComposeResult:
        yield WorkPanel(
            event_bus=self._container.event_bus,
            pty_manager=self._container.pty_manager,
            stream_router=self._container.stream_router,
        )
        yield GitPanel(
            event_bus=self._container.event_bus,
            git_adapter=self._container.git_adapter,
        )
        yield LogsPanel(
            event_bus=self._container.event_bus,
            activity_log_service=self._container.activity_log_service,
        )

    def load_workspace(self, context: dict[str, object]) -> None:
        work_panel = self.query_one(WorkPanel)
        git_panel = self.query_one(GitPanel)
        logs_panel = self.query_one(LogsPanel)
        layout_id = context.get("layout_id")
        if isinstance(layout_id, str) and layout_id:
            self._layout_id = layout_id
        self._tabs = self._normalize_tabs(context.get("tabs"))
        snapshot = context.get("snapshot")
        panel_snapshots = self._panel_snapshots(snapshot if isinstance(snapshot, dict) else {})

        work_context = dict(context)
        work_context.update(panel_snapshots.get(WorkPanel.PANEL_ID, {}))
        git_context = dict(context)
        git_context.update(panel_snapshots.get(GitPanel.PANEL_ID, {}))
        logs_context = dict(context)
        logs_context.update(panel_snapshots.get(LogsPanel.PANEL_ID, {}))

        work_panel.initialize(work_context)
        git_panel.initialize(git_context)
        logs_panel.initialize(logs_context)
        active_tab_id = context.get("active_tab_id")
        self.set_active_tab(
            str(active_tab_id) if isinstance(active_tab_id, str) and active_tab_id else "work",
            focus=False,
        )

    def focus_terminal(self) -> None:
        self.query_one(WorkPanel).focus_terminal()

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
        work_snapshot = panel_snapshots.get(WorkPanel.PANEL_ID, {})
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

    def _active_panel(self) -> PanelWidget:
        if self._active_tab_id == "git":
            return self.query_one(GitPanel)
        if self._active_tab_id == "logs":
            return self.query_one(LogsPanel)
        return self.query_one(WorkPanel)

    def _panels(self) -> list[PanelWidget]:
        return [self.query_one(WorkPanel), self.query_one(GitPanel), self.query_one(LogsPanel)]

    def _panel_snapshots(self, snapshot: dict[str, object]) -> dict[str, dict[str, object]]:
        raw_panels = snapshot.get("panels", {})
        if not isinstance(raw_panels, dict):
            raw_panels = {}
        panel_snapshots: dict[str, dict[str, object]] = {}
        for panel_id, payload in raw_panels.items():
            if isinstance(panel_id, str) and isinstance(payload, dict):
                panel_snapshots[panel_id] = payload
        if WorkPanel.PANEL_ID not in panel_snapshots:
            panel_snapshots[WorkPanel.PANEL_ID] = {
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

    def _tab_panels(self) -> dict[str, PanelWidget]:
        all_panels = {
            WorkPanel.PANEL_ID: self.query_one(WorkPanel),
            GitPanel.PANEL_ID: self.query_one(GitPanel),
            LogsPanel.PANEL_ID: self.query_one(LogsPanel),
        }
        tabs: dict[str, PanelWidget] = {}
        for tab in self._tabs:
            panel = all_panels.get(tab["panel_id"])
            if panel is not None:
                tabs[tab["id"]] = panel
        if "work" not in tabs:
            tabs["work"] = all_panels[WorkPanel.PANEL_ID]
        return tabs
