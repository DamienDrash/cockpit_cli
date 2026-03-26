"""Professional Curl/HTTP panel with history and request builder."""

from __future__ import annotations

import json
from rich.text import Text
from rich.syntax import Syntax
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, Label, Input, Button, Select

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.domain.events.runtime_events import PanelMounted
from cockpit.domain.models.panel_state import PanelState
from cockpit.shared.enums import SessionTargetKind
from cockpit.ui.panels.base_panel import BasePanel
from cockpit.ui.branding import C_PRIMARY, C_SECONDARY


class CurlPanel(BasePanel):
    """Professional HTTP TUI with history sidebar and request builder."""

    PANEL_ID = "curl-panel"
    PANEL_TYPE = "curl"
    can_focus = True

    def __init__(self, *, event_bus: EventBus) -> None:
        super().__init__(id=self.PANEL_ID)
        self._event_bus = event_bus
        self._workspace_root = ""
        self._target_kind = SessionTargetKind.LOCAL
        self._target_ref: str | None = None
        self._history: list[dict[str, object]] = []
        self._last_response: dict[str, object] | None = None

    def compose(self) -> ComposeResult:
        with Horizontal():
            # Sidebar: History
            with Vertical(id="curl-sidebar", classes="sidebar"):
                yield Label(" [ HISTORY ] ", classes="section-title")
                yield Static("No history yet.", id="curl-history-list", classes="list-view")
                yield Label(" [ ACTIONS ] ", classes="section-title")
                yield Static(
                    " Enter: Send Request\n"
                    " r: Refresh\n"
                    " c: Copy as curl",
                    id="curl-legend"
                )
            
            # Main: Builder & Response
            with Vertical(id="curl-main"):
                with Vertical(id="curl-builder-pane"):
                    yield Label("HTTP REQUEST BUILDER", classes="pane-title")
                    with Horizontal(id="curl-method-url-row"):
                        yield Select(
                            [("GET", "GET"), ("POST", "POST"), ("PUT", "PUT"), ("DELETE", "DELETE")],
                            value="GET",
                            id="curl-method-select"
                        )
                        yield Input(placeholder="https://api.example.com", id="curl-url-input")
                    
                    yield Label("Headers (Key:Value|...):")
                    yield Input(placeholder="Content-Type: application/json", id="curl-headers-input")
                    
                    yield Label("Body:")
                    yield Input(placeholder='{"key": "value"}', id="curl-body-input")
                    
                    with Horizontal(id="curl-builder-actions"):
                        yield Button("SEND", id="curl-btn-send", variant="primary")
                
                with Vertical(id="curl-response-pane"):
                    yield Label("RESPONSE", classes="pane-title")
                    yield Static("", id="curl-response-status")
                    yield Static("Response will appear here.", id="curl-response-view", classes="detail-view")

    def on_mount(self) -> None:
        self._event_bus.publish(PanelMounted(panel_id=self.PANEL_ID, panel_type=self.PANEL_TYPE))

    def initialize(self, context: dict[str, object]) -> None:
        self._workspace_root = str(context.get("workspace_root", ""))
        self._target_kind = SessionTargetKind(str(context.get("target_kind", "local")))
        self.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "curl-btn-send":
            self._handle_send()

    def _handle_send(self) -> None:
        method = str(self.query_one("#curl-method-select", Select).value)
        url = self.query_one("#curl-url-input", Input).value
        headers = self.query_one("#curl-headers-input", Input).value
        body = self.query_one("#curl-body-input", Input).value
        
        if not url:
            self.app.notify("URL is required!", severity="error")
            return
            
        from cockpit.domain.commands.command import Command
        from cockpit.shared.enums import CommandSource
        from cockpit.shared.utils import make_id
        
        self.app._dispatch_command(Command(
            id=make_id("cmd"),
            source=CommandSource.KEYBINDING,
            name="curl.send",
            args={"argv": [method, url], "headers": headers, "body": body},
            context=self.command_context()
        ))

    def apply_command_result(self, payload: dict[str, object]) -> None:
        res = payload.get("response")
        if isinstance(res, dict):
            self._last_response = res
            status = res.get("status_code", "???")
            duration = res.get("duration_ms", 0)
            self.query_one("#curl-response-status", Static).update(f"Status: {status} | Time: {duration}ms")
            
            body = res.get("body_preview", "")
            try:
                parsed = json.loads(body)
                body = json.dumps(parsed, indent=2)
            except Exception: pass
            
            self.query_one("#curl-response-view", Static).update(Syntax(body, "json", theme="monokai"))
            
            # Update history
            self._history.insert(0, {"method": payload.get("draft_method"), "url": payload.get("draft_url"), "status": status})
            self._history = self._history[:10]
            self._render_history()

    def _render_history(self) -> None:
        txt = Text()
        for h in self._history:
            txt.append(f"{h['status']} ", style="green" if str(h['status']).startswith("2") else "red")
            txt.append(f"{h['method']} {str(h['url'])[-20:]}\n", style="dim")
        self.query_one("#curl-history-list", Static).update(txt)

    def resume(self) -> None:
        self.focus()

    def command_context(self) -> dict[str, object]:
        return {"panel_id": self.PANEL_ID, "workspace_root": self._workspace_root}

    def snapshot_state(self) -> PanelState:
        return PanelState(panel_id=self.PANEL_ID, panel_type=self.PANEL_TYPE)
