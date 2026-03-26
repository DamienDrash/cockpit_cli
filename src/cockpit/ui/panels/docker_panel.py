"""Professional DockerPanel implementation with Sidebar and Multi-View Detail."""

from __future__ import annotations

from rich.text import Text
from rich.syntax import Syntax
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, Label, Button, ContentSwitcher

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.domain.events.runtime_events import PanelMounted
from cockpit.domain.models.panel_state import PanelState
from cockpit.infrastructure.docker.docker_adapter import (
    DockerAdapter,
    DockerContainerSummary,
)
from cockpit.shared.enums import SessionTargetKind
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
                    yield Button("LOGS", id="docker-tab-logs", classes="mini-tab")
                    yield Button("STATS", id="docker-tab-stats", classes="mini-tab")
                    yield Button("INSPECT", id="docker-tab-inspect", classes="mini-tab")
                
                with ContentSwitcher(initial="logs", id="docker-detail-switcher"):
                    yield Static("Loading logs...", id="logs", classes="detail-view")
                    yield Static("Loading stats...", id="stats", classes="detail-view")
                    yield Static("Loading config...", id="inspect", classes="detail-view")

    def on_mount(self) -> None:
        self._event_bus.publish(PanelMounted(panel_id=self.PANEL_ID, panel_type=self.PANEL_TYPE))
        self.refresh_runtime()

    def initialize(self, context: dict[str, object]) -> None:
        self._workspace_root = str(context.get("workspace_root", ""))
        self._target_kind = SessionTargetKind(str(context.get("target_kind", "local")))
        self.refresh_runtime()
        self.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id and event.button.id.startswith("docker-tab-"):
            self._switch_detail_tab(event.button.id.replace("docker-tab-", ""))

    def _switch_detail_tab(self, tab_id: str) -> None:
        self._active_detail_tab = tab_id
        self.query_one("#docker-detail-switcher", ContentSwitcher).current = tab_id
        for btn in self.query(".mini-tab"):
            btn.remove_class("-active")
            if btn.id == f"docker-tab-{tab_id}":
                btn.add_class("-active")
        self._update_detail()

    def refresh_runtime(self) -> None:
        try:
            snapshot = self._docker_adapter.list_containers(
                target_kind=self._target_kind,
                target_ref=self._target_ref,
            )
            self._containers = snapshot.containers
            self._render_list()
            self._update_detail()
        except Exception: pass

    def _render_list(self) -> None:
        txt = Text()
        if not self._containers:
            txt.append("  No containers.", style="dim")
        else:
            for i, c in enumerate(self._containers):
                marker = "▶ " if i == self._selected_index else "  "
                color = "green" if c.state == "running" else "red"
                txt.append(marker, style=C_PRIMARY if i == self._selected_index else "dim")
                txt.append("● ", style=color)
                txt.append(f"{c.name[:25]}\n", style="bold" if i == self._selected_index else "")
        self.query_one("#docker-container-list", Static).update(txt)

    def _update_detail(self) -> None:
        if not self._containers: return
        container = self._containers[self._selected_index]
        
        try:
            # We use collect_diagnostics to get logs and details
            diags = self._docker_adapter.collect_diagnostics(
                target_kind=self._target_kind,
                target_ref=self._target_ref,
                log_tail=100
            )
            # Find the diagnostic for the currently selected container
            diag = next((d for d in diags if d.container_id == container.container_id), None)
            
            if not diag:
                self.query_one(f"#{self._active_detail_tab}", Static).update("No detail data found.")
                return

            if self._active_detail_tab == "logs":
                log_text = "\n".join(diag.recent_logs) if diag.recent_logs else "No logs available."
                self.query_one("#logs", Static).update(log_text)
            elif self._active_detail_tab == "stats":
                self.query_one("#stats", Static).update(f"Container: {diag.name}\nState: {diag.state}\nHealth: {diag.health or 'N/A'}")
            elif self._active_detail_tab == "inspect":
                self.query_one("#inspect", Static).update(f"ID: {diag.container_id}\nImage: {diag.image}\nStatus: {diag.status}\nPorts: {diag.ports}")
        except Exception as exc:
            self.query_one(f"#{self._active_detail_tab}", Static).update(f"Error: {exc}")

    def on_key(self, event: events.Key) -> None:
        if event.key == "up":
            self._selected_index = max(0, self._selected_index - 1)
            self._render_list()
            self._update_detail()
            event.stop()
        elif event.key == "down":
            self._selected_index = min(len(self._containers) - 1, self._selected_index + 1)
            self._render_list()
            self._update_detail()
            event.stop()
        elif event.key == "r":
            self.refresh_runtime()
            event.stop()

    def resume(self) -> None:
        self.refresh_runtime()
        self.focus()

    def command_context(self) -> dict[str, object]:
        return {"panel_id": self.PANEL_ID}

    def snapshot_state(self) -> PanelState:
        return PanelState(panel_id=self.PANEL_ID, panel_type=self.PANEL_TYPE)
