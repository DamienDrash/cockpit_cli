"""Example external-style plugin module for Cockpit."""

from __future__ import annotations

from textual.widgets import Static

from cockpit.core.panel_state import PanelState
from cockpit.plugins.models import PluginManifest
from cockpit.plugins.loader import PluginBootstrapContext
from cockpit.ui.panels.registry import PanelSpec


class NotesPanel(Static):
    PANEL_ID = "notes-panel"
    PANEL_TYPE = "notes"
    can_focus = True

    def __init__(self) -> None:
        super().__init__("", id=self.PANEL_ID, markup=False)
        self._notes: list[str] = []

    def initialize(self, context: dict[str, object]) -> None:
        del context
        self.update(self._render_text())

    def restore_state(self, snapshot: dict[str, object]) -> None:
        notes = snapshot.get("notes")
        if isinstance(notes, list):
            self._notes = [str(note) for note in notes if isinstance(note, str)]
        self.update(self._render_text())

    def snapshot_state(self) -> PanelState:
        return PanelState(
            panel_id=self.PANEL_ID,
            panel_type=self.PANEL_TYPE,
            snapshot={"notes": list(self._notes)},
        )

    def command_context(self) -> dict[str, object]:
        return {"panel_id": self.PANEL_ID, "notes_count": len(self._notes)}

    def suspend(self) -> None:
        """No runtime resources."""

    def resume(self) -> None:
        self.update(self._render_text())

    def dispose(self) -> None:
        """No runtime resources."""

    def apply_command_result(self, payload: dict[str, object]) -> None:
        note = payload.get("note")
        if isinstance(note, str) and note:
            self._notes.append(note)
        self.update(self._render_text())

    def _render_text(self) -> str:
        if not self._notes:
            return "Plugin Notes\n\nUse a plugin command to append notes."
        lines = ["Plugin Notes", ""]
        lines.extend(f"- {note}" for note in self._notes[-8:])
        return "\n".join(lines)


class AppendNoteHandler:
    def __call__(self, command: object):
        args = getattr(command, "args", {})
        argv = args.get("argv", []) if isinstance(args, dict) else []
        note = " ".join(str(token) for token in argv if isinstance(token, str)).strip()
        if not note:
            note = "plugin note"
        from cockpit.core.dispatch.handler_base import DispatchResult

        return DispatchResult(
            success=True,
            message=f"Added plugin note: {note}",
            data={"result_panel_id": "notes-panel", "result_payload": {"note": note}},
        )


PLUGIN_MANIFEST = PluginManifest(
    name="Notes Plugin",
    module="cockpit.plugins.notes_plugin",
    version="1.0.0",
    compat_range=">=0.1.0",
    summary="Example plugin that adds a notes panel and append command.",
    panels=["notes"],
    commands=["notes.append"],
    admin_pages=["plugins"],
    permissions=["ui.read", "commands.execute"],
    runtime_mode="hosted",
)


def register_plugin(context: PluginBootstrapContext) -> None:
    context.register_panel(
        PanelSpec(
            panel_type=NotesPanel.PANEL_TYPE,
            panel_id=NotesPanel.PANEL_ID,
            display_name="Notes",
            factory=lambda _container: NotesPanel(),
        )
    )
    context.register_command("notes.append", AppendNoteHandler())
