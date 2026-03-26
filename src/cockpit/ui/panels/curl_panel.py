"""Professional Curl/HTTP panel with history and request builder."""

from __future__ import annotations

import json
from rich.text import Text
from rich.syntax import Syntax
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, Label, Input, Button, Select, ContentSwitcher

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.domain.events.runtime_events import PanelMounted, PanelStateChanged
from cockpit.domain.models.panel_state import PanelState
from cockpit.shared.enums import SessionTargetKind, StatusLevel
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
        self._draft_method = "GET"
        self._draft_url = ""
        self._draft_headers = ""
        self._draft_body = ""
        self._last_response: dict[str, object] | None = None
        self._history: list[dict[str, object]] = []
        self._selected_history_index = -1

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
                    " h: Focus History",
                    id="curl-legend"
                )
            
            # Main: Builder & Response
            with Vertical(id="curl-main"):
                # Request Builder
                with Vertical(id="curl-builder-pane"):
                    yield Label("HTTP REQUEST BUILDER", classes="pane-title")
                    with Horizontal(id="curl-method-url-row"):
                        yield Select(
                            [("GET", "GET"), ("POST", "POST"), ("PUT", "PUT"), ("DELETE", "DELETE"), ("PATCH", "PATCH")],
                            value="GET",
                            id="curl-method-select"
                        )
                        yield Input(placeholder="https://api.example.com/v1/resource", id="curl-url-input")
                    
                    yield Label("Headers (Key:Value|Key:Value):")
                    yield Input(placeholder="Content-Type: application/json|Authorization: Bearer ...", id="curl-headers-input")
                    
                    yield Label("Body (JSON/Text):")
                    yield Input(placeholder='{"key": "value"}', id="curl-body-input")
                    
                    with Horizontal(id="curl-builder-actions"):
                        yield Button("SEND REQUEST", id="curl-btn-send", variant="primary")
                
                # Response View
                with Vertical(id="curl-response-pane"):
                    yield Label("HTTP RESPONSE", classes="pane-title")
                    yield Static("Response body will appear here...", id="curl-response-view", classes="detail-view")
                    yield Static("", id="curl-response-status")

    def on_mount(self) -> None:
        self._event_bus.publish(PanelMounted(panel_id=self.PANEL_ID, panel_type=self.PANEL_TYPE))
        self._render_all()

    def initialize(self, context: dict[str, object]) -> None:
        self._workspace_root = str(context.get("workspace_root", ""))
        self._target_kind = SessionTargetKind(str(context.get("target_kind", "local")))
        self._target_ref = context.get("target_ref")
        self.focus()

    def on_key(self, event: events.Key) -> None:
        if event.key == "r":
            self._render_all()
            event.stop()
        elif event.key == "enter" and not self.query_one("#curl-body-input").has_focus:
            self._handle_send()
            event.stop()

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
        
        args = {"argv": [method, url], "headers": headers, "body": body}
        cmd = Command(
            id=make_id("cmd"),
            source=CommandSource.KEYBINDING,
            name="curl.send",
            args=args,
            context=self.command_context()
        )
        self.app._dispatch_command(cmd)
        self.app.notify(f"Sending {method} to {url}...")

    def apply_command_result(self, payload: dict[str, object]) -> None:
        response = payload.get("response")
        if isinstance(response, dict):
            self._last_response = response
            # Add to history
            history_entry = {
                "method": payload.get("draft_method", "GET"),
                "url": payload.get("draft_url", ""),
                "status_code": response.get("status_code"),
                "duration_ms": response.get("duration_ms"),
                "body_preview": response.get("body_preview")
            }
            self._history.insert(0, history_entry)
            self._history = self._history[:10]
            self._render_all()

    def _render_all(self) -> None:
        # 1. History List
        history_text = Text()
        if not self._history:
            history_text.append("  No history yet.", style="dim")
        else:
            for i, h in enumerate(self._history):
                is_selected = i == self._selected_history_index
                marker = "▶ " if is_selected else "  "
                
                status = h.get("status_code", "???")
                status_color = "green" if str(status).startswith("2") else "red"
                if str(status).startswith("3"): status_color = "yellow"
                
                history_text.append(marker, style=C_PRIMARY if is_selected else "dim")
                history_text.append(f"{status} ", style=status_color)
                history_text.append(f"{h.get('method')} ", style="bold")
                url_trimmed = str(h.get("url"))[-20:]
                history_text.append(f"...{url_trimmed}\n", style="dim")
        
        self.query_one("#curl-history-list", Static).update(history_text)
        
        # 2. Response View
        if self._last_response:
            status_code = self._last_response.get("status_code")
            duration = self._last_response.get("duration_ms", 0)
            body = self._last_response.get("body_preview", "")
            
            # Status bar info
            self.query_one("#curl-response-status", Static).update(
                f"Status: [bold]{status_code}[/] | Time: [bold]{duration}ms[/]"
            )
            
            # Syntax highlighting for body
            lexer = "json"
            if body.strip().startswith("<"): lexer = "html"
            
            try:
                # Try to pretty print JSON if possible
                if lexer == "json":
                    parsed = json.loads(body)
                    body = json.dumps(parsed, indent=2)
            except Exception:
                pass
                
            self.query_one("#curl-response-view", Static).update(Syntax(body, lexer, theme="monokai"))
        else:
            self.query_one("#curl-response-view", Static).update("Ready to send request.")

    def resume(self) -> None:
        self._render_all()
        self.focus()

    def command_context(self) -> dict[str, object]:
        return {
            "panel_id": self.PANEL_ID,
            "workspace_root": self._workspace_root,
            "target_kind": self._target_kind.value,
            "target_ref": self._target_ref,
            "draft_method": self._draft_method,
            "draft_url": self._draft_url,
        }

    def snapshot_state(self) -> PanelState:
        return PanelState(panel_id=self.PANEL_ID, panel_type=self.PANEL_TYPE)
