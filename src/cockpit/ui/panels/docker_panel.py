"""Professional DockerPanel implementation with Sidebar and Multi-View Detail."""

from __future__ import annotations

from pathlib import Path
from rich.text import Text
from rich.syntax import Syntax
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, Label, Button, ContentSwitcher

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.domain.events.runtime_events import PanelMounted, PanelStateChanged
from cockpit.domain.models.panel_state import PanelState
from cockpit.infrastructure.docker.docker_adapter import (
    DockerAdapter,
    DockerContainerSummary,
    DockerRuntimeSnapshot,
)
from cockpit.shared.enums import SessionTargetKind, StatusLevel
from cockpit.ui.panels.base_panel import BasePanel
from cockpit.ui.branding import C_PRIMARY, C_SECONDARY


class DockerPanel(BasePanel):
    """Professional Docker TUI with sidebar navigation and multi-view detail."""

    PANEL_ID = "docker-panel"
    PANEL_TYPE = "docker"
    can_focus = True

    def __init__(self, *, event_bus: EventBus, docker_adapter: DockerAdapter) -> None:
        super().__init__(id=self.PANEL_ID)
        self._event_bus = event_bus
        self._docker_adapter = docker_adapter
        self._workspace_root = ""
        self._target_kind = SessionTargetKind.LOCAL
        self._target_ref: str | None = None
        self._containers: list[DockerContainerSummary] = []
        self._selected_index = 0
        self._active_detail_tab = "logs"
        self._session_id: str | None = None
        self._workspace_id: str | None = None

    def compose(self) -> ComposeResult:
        with Horizontal():
            # Sidebar
            with Vertical(id="docker-sidebar", classes="sidebar"):
                yield Label(" [ CONTAINERS ] ", classes="section-title")
                yield Static("loading...", id="docker-container-list", classes="list-view")
                yield Label(" [ ACTIONS ] ", classes="section-title")
                yield Static(
                    " r: Restart\n"
                    " s: Stop\n"
                    " u: Start\n"
                    " Enter: Exec",
                    id="docker-legend"
                )
            
            # Main Detail Area
            with Vertical(id="docker-main"):
                with Horizontal(id="docker-detail-tabs"):
                    yield Button("LOGS", id="docker-tab-logs", variant="primary", classes="mini-tab")
                    yield Button("STATS", id="docker-tab-stats", classes="mini-tab")
                    yield Button("INSPECT", id="docker-tab-inspect", classes="mini-tab")
                
                with ContentSwitcher(initial="logs", id="docker-detail-switcher"):
                    yield Static("Loading logs...", id="docker-logs-view", classes="detail-view")
                    yield Static("Loading stats...", id="docker-stats-view", classes="detail-view")
                    yield Static("Loading config...", id="docker-inspect-view", classes="detail-view")

    def on_mount(self) -> None:
        self._event_bus.publish(PanelMounted(panel_id=self.PANEL_ID, panel_type=self.PANEL_TYPE))
        self.refresh_runtime()

    def initialize(self, context: dict[str, object]) -> None:
        self._workspace_root = str(context.get("workspace_root", ""))
        self._target_kind = SessionTargetKind(str(context.get("target_kind", "local")))
        self._target_ref = context.get("target_ref")
        self._session_id = context.get("session_id")
        self._workspace_id = context.get("workspace_id")
        self.refresh_runtime()
        self.focus()

    def command_context(self) -> dict[str, object]:
        selected = self._selected_container()
        return {
            "panel_id": self.PANEL_ID,
            "workspace_id": self._workspace_id,
            "session_id": self._session_id,
            "target_kind": self._target_kind.value,
            "target_ref": self._target_ref,
            "selected_container_id": selected.container_id if selected else None,
            "selected_container_name": selected.name if selected else None,
        }

    def on_key(self, event: events.Key) -> None:
        if event.key == "up":
            self._move_selection(-1)
            event.stop()
        elif event.key == "down":
            self._move_selection(1)
            event.stop()
        elif event.key == "r":
            self._restart_selected()
            event.stop()
        elif event.key == "s":
            self._stop_selected()
            event.stop()
        elif event.key == "u":
            self._start_selected()
            event.stop()
        elif event.key == "enter":
            self._exec_selected()
            event.stop()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id and event.button.id.startswith("docker-tab-"):
            tab_id = event.button.id.replace("docker-tab-", "")
            self._switch_detail_tab(tab_id)

    def refresh_runtime(self) -> None:
        try:
            snapshot = self._docker_adapter.list_containers(
                target_kind=self._target_kind,
                target_ref=self._target_ref,
            )
            self._containers = snapshot.containers
            self._render_all()
        except Exception:
            pass

    def _render_all(self) -> None:
        # 1. Sidebar List
        list_text = Text()
        if not self._containers:
            list_text.append("  No containers found.", style="dim")
        else:
            for i, c in enumerate(self._containers):
                is_selected = i == self._selected_index
                marker = "▶ " if is_selected else "  "
                style = f"{C_SECONDARY} bold" if is_selected else ""
                
                state_color = "green" if c.state == "running" else "red"
                if c.state == "restarting": state_color = "yellow"
                
                list_text.append(marker, style=C_PRIMARY if is_selected else "dim")
                list_text.append("● ", style=state_color)
                list_text.append(f"{c.name.ljust(20)}", style=style)
                list_text.append(f" {c.image[:15]}...\n", style="dim")
        
        self.query_one("#docker-container-list", Static).update(list_text)
        
        # 2. Detail View
        self._update_detail()

    def _update_detail(self) -> None:
        selected = self._selected_container()
        if not selected:
            for vid in ["logs", "stats", "inspect"]:
                self.query_one(f"#docker-{vid}-view", Static).update("No container selected.")
            return

        # Fetch logs
        try:
            diag = self._docker_adapter.collect_diagnostics(
                target_kind=self._target_kind,
                target_ref=self._target_ref,
                log_tail=100
            )
            # Find current container in diagnostics
            current_diag = next((d for d in diag if d.container_id == selected.container_id), None)
            
            if current_diag:
                log_text = "\n".join(current_diag.recent_logs) or "No logs available."
                self.query_one("#docker-logs-view", Static).update(log_text)
                
                # Mock Stats for now (Gold Standard placeholder)
                stats_text = f"Container: {selected.name}\nID: {selected.container_id}\n\nCPU: 0.5%\nMEM: 120MB / 2GB\nNET I/O: 1KB / 2KB"
                self.query_one("#docker-stats-view", Static).update(stats_text)
                
                # For Inspect, we'd normally call docker inspect
                self.query_one("#docker-inspect-view", Static).update(f"Config for {selected.name} (ID {selected.container_id})")
        except Exception as exc:
            self.query_one("#docker-logs-view", Static).update(f"Error loading detail: {exc}")

    def _move_selection(self, delta: int) -> None:
        if not self._containers: return
        self._selected_index = max(0, min(len(self._containers) - 1, self._selected_index + delta))
        self._render_all()

    def _switch_detail_tab(self, tab_id: str) -> None:
        self._active_detail_tab = tab_id
        self.query_one("#docker-detail-switcher", ContentSwitcher).current = tab_id
        for btn in self.query(".mini-tab"):
            btn.variant = "primary" if btn.id == f"docker-tab-{tab_id}" else "default"

    def _selected_container(self) -> DockerContainerSummary | None:
        if not self._containers: return None
        return self._containers[self._selected_index]

    def _restart_selected(self) -> None:
        selected = self._selected_container()
        if selected:
            self._docker_adapter.restart_container(selected.container_id, target_kind=self._target_kind, target_ref=self._target_ref)
            self.refresh_runtime()

    def _stop_selected(self) -> None:
        selected = self._selected_container()
        if selected:
            self._docker_adapter.stop_container(selected.container_id, target_kind=self._target_kind, target_ref=self._target_ref)
            self.refresh_runtime()

    def _start_selected(self) -> None:
        selected = self._selected_container()
        if selected:
            # Note: start is usually 'docker start'
            self._docker_adapter._run_container_action("start", selected.container_id, target_kind=self._target_kind, target_ref=self._target_ref)
            self.refresh_runtime()

    def _exec_selected(self) -> None:
        selected = self._selected_container()
        if selected:
            from cockpit.shared.utils import make_id
            from cockpit.shared.enums import CommandSource
            from cockpit.domain.commands.command import Command
            
            # Send exec command to terminal tab
            cmd_text = f"docker exec -it {selected.container_id} sh"
            # In a real implementation, we would switch to terminal and send input
            self.app.notify(f"Exec: {cmd_text}")

    def resume(self) -> None:
        self.refresh_runtime()
        self.focus()

    def snapshot_state(self) -> PanelState:
        return PanelState(panel_id=self.PANEL_ID, panel_type=self.PANEL_TYPE)
