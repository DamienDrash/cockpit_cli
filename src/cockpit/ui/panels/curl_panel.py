"""Curl/HTTP panel implementation."""

from __future__ import annotations

from textual import events
from textual.widgets import Static

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.domain.events.runtime_events import PanelMounted, PanelStateChanged
from cockpit.domain.models.panel_state import PanelState


class CurlPanel(Static):
    """Request/response panel for quick HTTP interactions."""

    PANEL_ID = "curl-panel"
    PANEL_TYPE = "curl"
    can_focus = True

    def __init__(self, *, event_bus: EventBus) -> None:
        super().__init__("", id=self.PANEL_ID, markup=False)
        self._event_bus = event_bus
        self._workspace_name = "No workspace"
        self._workspace_root = ""
        self._workspace_id: str | None = None
        self._session_id: str | None = None
        self._draft_method = "GET"
        self._draft_url = ""
        self._draft_body = ""
        self._last_response: dict[str, object] | None = None
        self._history: list[dict[str, object]] = []

    def on_mount(self) -> None:
        self._event_bus.publish(
            PanelMounted(
                panel_id=self.PANEL_ID,
                panel_type=self.PANEL_TYPE,
            )
        )
        self._render_state()

    def initialize(self, context: dict[str, object]) -> None:
        self._workspace_name = str(context.get("workspace_name", "Workspace"))
        self._workspace_root = str(context.get("workspace_root", ""))
        self._workspace_id = self._optional_str(context.get("workspace_id"))
        self._session_id = self._optional_str(context.get("session_id"))
        self._render_state()

    def restore_state(self, snapshot: dict[str, object]) -> None:
        draft_method = snapshot.get("draft_method")
        draft_url = snapshot.get("draft_url")
        draft_body = snapshot.get("draft_body")
        last_response = snapshot.get("last_response")
        history = snapshot.get("history")
        if isinstance(draft_method, str) and draft_method:
            self._draft_method = draft_method
        if isinstance(draft_url, str):
            self._draft_url = draft_url
        if isinstance(draft_body, str):
            self._draft_body = draft_body
        if isinstance(last_response, dict):
            self._last_response = dict(last_response)
        if isinstance(history, list):
            self._history = [item for item in history if isinstance(item, dict)][:8]
        if self.is_mounted:
            self._render_state()

    def snapshot_state(self) -> PanelState:
        return PanelState(
            panel_id=self.PANEL_ID,
            panel_type=self.PANEL_TYPE,
            snapshot={
                "draft_method": self._draft_method,
                "draft_url": self._draft_url,
                "draft_body": self._draft_body,
                "last_response": dict(self._last_response) if self._last_response else None,
                "history": list(self._history),
            },
        )

    def command_context(self) -> dict[str, object]:
        return {
            "panel_id": self.PANEL_ID,
            "workspace_id": self._workspace_id,
            "session_id": self._session_id,
            "workspace_name": self._workspace_name,
            "workspace_root": self._workspace_root,
            "draft_method": self._draft_method,
            "draft_url": self._draft_url,
            "draft_body": self._draft_body,
        }

    def suspend(self) -> None:
        """No runtime resources need suspension."""

    def resume(self) -> None:
        self._render_state()

    def dispose(self) -> None:
        """No runtime resources need disposal."""

    def apply_command_result(self, payload: dict[str, object]) -> None:
        draft_method = payload.get("draft_method")
        draft_url = payload.get("draft_url")
        draft_body = payload.get("draft_body")
        response = payload.get("response")
        if isinstance(draft_method, str) and draft_method:
            self._draft_method = draft_method
        if isinstance(draft_url, str):
            self._draft_url = draft_url
        if isinstance(draft_body, str):
            self._draft_body = draft_body
        if isinstance(response, dict):
            self._last_response = dict(response)
            self._history.insert(0, dict(response))
            self._history = self._history[:8]
        self._render_state()
        self._publish_panel_state()

    def on_key(self, event: events.Key) -> None:
        if event.key == "r":
            self._render_state()
            event.stop()

    def _render_state(self) -> None:
        self.update(self._render_text())

    def _render_text(self) -> str:
        lines = [
            f"Workspace: {self._workspace_name}",
            f"Root: {self._workspace_root or '(none)'}",
            f"Draft: {self._draft_method} {self._draft_url or '(set via command)'}",
            "",
            "Last response:",
        ]
        if not self._last_response:
            lines.append(
                'Use /curl send GET https://example.com or /curl send POST https://... body=\'{"ok":true}\''
            )
        else:
            status_code = self._last_response.get("status_code")
            duration_ms = self._last_response.get("duration_ms")
            lines.append(
                f"status={status_code or '(none)'} duration_ms={duration_ms or 0}"
            )
            body_preview = self._last_response.get("body_preview")
            if isinstance(body_preview, str) and body_preview:
                lines.append(body_preview[:600])
            message = self._last_response.get("message")
            if isinstance(message, str) and message:
                lines.append(message)
        lines.extend(["", "History:"])
        if not self._history:
            lines.append("No requests sent yet.")
        else:
            for entry in self._history[:6]:
                method = entry.get("method", "GET")
                url = entry.get("url", "")
                status_code = entry.get("status_code", "-")
                lines.append(f"{method} {status_code} {url}")
        return "\n".join(lines)

    def _publish_panel_state(self) -> None:
        state = self.snapshot_state()
        self._event_bus.publish(
            PanelStateChanged(
                panel_id=self.PANEL_ID,
                panel_type=self.PANEL_TYPE,
                snapshot=state.snapshot,
                config=state.config,
            )
        )

    @staticmethod
    def _optional_str(value: object) -> str | None:
        return value if isinstance(value, str) else None
