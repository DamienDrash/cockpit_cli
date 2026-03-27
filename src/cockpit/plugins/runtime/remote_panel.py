"""Core-side proxy widgets for isolated managed plugin panels."""

from __future__ import annotations

try:  # pragma: no cover - exercised in integration environments with textual
    from textual.widgets import Static
except Exception:  # pragma: no cover - test fallback when textual is unavailable

    class Static:  # type: ignore[override]
        can_focus = True

        def __init__(
            self, value: str = "", *, id: str | None = None, markup: bool = False
        ) -> None:
            del markup
            self.id = id
            self.display = True
            self._value = value

        def update(self, value: str) -> None:
            self._value = value

        def focus(self) -> None:
            return None


from cockpit.core.panel_state import PanelState


class RemotePluginPanel(Static):
    """Display a managed plugin panel through the isolated host bridge."""

    can_focus = True

    def __init__(
        self,
        *,
        plugin_service: object,
        plugin_id: str,
        panel_id: str,
        panel_type: str,
        display_name: str,
    ) -> None:
        super().__init__("", id=panel_id, markup=False)
        self.PANEL_ID = panel_id
        self.PANEL_TYPE = panel_type
        self._display_name = display_name
        self._plugin_id = plugin_id
        self._plugin_service = plugin_service
        self._render_text = f"{display_name}\n\nPlugin panel is not initialized yet."

    def initialize(self, context: dict[str, object]) -> None:
        self._refresh("initialize", context)

    def restore_state(self, snapshot: dict[str, object]) -> None:
        self._refresh("restore_state", snapshot)

    def snapshot_state(self) -> PanelState:
        result = self._panel_call("snapshot_state", {})
        payload = result.get("panel_state", {})
        if not isinstance(payload, dict):
            return PanelState(
                panel_id=self.PANEL_ID,
                panel_type=self.PANEL_TYPE,
                snapshot={},
            )
        return PanelState(
            panel_id=str(payload.get("panel_id", self.PANEL_ID)),
            panel_type=str(payload.get("panel_type", self.PANEL_TYPE)),
            snapshot=dict(payload.get("snapshot", {}))
            if isinstance(payload.get("snapshot"), dict)
            else {},
            config=dict(payload.get("config", {}))
            if isinstance(payload.get("config"), dict)
            else {},
            persist_policy=str(payload.get("persist_policy", "session")),
        )

    def command_context(self) -> dict[str, object]:
        result = self._panel_call("command_context", {})
        payload = result.get("command_context", {})
        if not isinstance(payload, dict):
            return {"panel_id": self.PANEL_ID}
        return {str(key): value for key, value in payload.items()}

    def suspend(self) -> None:
        self._refresh("suspend", {})

    def resume(self) -> None:
        self._refresh("resume", {})

    def dispose(self) -> None:
        self._refresh("dispose", {})

    def apply_command_result(self, payload: dict[str, object]) -> None:
        self._refresh("apply_command_result", payload)

    def _refresh(self, action: str, payload: dict[str, object]) -> None:
        result = self._panel_call(action, payload)
        render_text = result.get("render_text")
        if isinstance(render_text, str):
            self._render_text = render_text
            self.update(render_text)

    def _panel_call(self, action: str, payload: dict[str, object]) -> dict[str, object]:
        call = getattr(self._plugin_service, "invoke_panel_action")
        try:
            return call(
                plugin_id=self._plugin_id,
                panel_id=self.PANEL_ID,
                action=action,
                payload=payload,
            )
        except Exception as exc:
            self._render_text = (
                f"{self._display_name}\n\nPlugin host unavailable.\n{exc}"
            )
            self.update(self._render_text)
            if action == "snapshot_state":
                return {
                    "panel_state": {
                        "panel_id": self.PANEL_ID,
                        "panel_type": self.PANEL_TYPE,
                        "snapshot": {},
                    }
                }
            if action == "command_context":
                return {"command_context": {"panel_id": self.PANEL_ID}}
            return {"render_text": self._render_text}
