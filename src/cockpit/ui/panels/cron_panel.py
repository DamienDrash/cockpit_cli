"""Reference CronPanel implementation."""

from __future__ import annotations

from textual import events
from textual.widgets import Static

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.domain.events.runtime_events import PanelMounted, PanelStateChanged
from cockpit.domain.models.panel_state import PanelState
from cockpit.infrastructure.cron.cron_adapter import CronAdapter, CronJob
from cockpit.shared.enums import SessionTargetKind


class CronPanel(Static):
    """Read-only cron panel for local and SSH-backed crontab inspection."""

    PANEL_ID = "cron-panel"
    PANEL_TYPE = "cron"
    can_focus = True

    def __init__(self, *, event_bus: EventBus, cron_adapter: CronAdapter) -> None:
        super().__init__("", id=self.PANEL_ID, markup=False)
        self._event_bus = event_bus
        self._cron_adapter = cron_adapter
        self._workspace_name = "No workspace"
        self._workspace_root = ""
        self._workspace_id: str | None = None
        self._session_id: str | None = None
        self._target_kind = SessionTargetKind.LOCAL
        self._target_ref: str | None = None
        self._jobs: list[CronJob] = []
        self._selected_index = 0
        self._message = "No crontab state loaded."

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
        self._target_kind = self._target_kind_from_context(context.get("target_kind"))
        self._target_ref = self._optional_str(context.get("target_ref"))
        selected_command = context.get("selected_command")
        if isinstance(selected_command, str) and selected_command:
            self._selected_index = 0
        self.refresh_jobs(selected_command=selected_command if isinstance(selected_command, str) else None)

    def restore_state(self, snapshot: dict[str, object]) -> None:
        selected_command = snapshot.get("selected_command")
        self.refresh_jobs(selected_command=selected_command if isinstance(selected_command, str) else None)

    def snapshot_state(self) -> PanelState:
        selected = self._selected_job()
        return PanelState(
            panel_id=self.PANEL_ID,
            panel_type=self.PANEL_TYPE,
            snapshot={"selected_command": selected.command if selected is not None else None},
        )

    def suspend(self) -> None:
        """No runtime resources need suspension yet."""

    def resume(self) -> None:
        self.refresh_jobs()

    def dispose(self) -> None:
        """No runtime resources need disposal yet."""

    def command_context(self) -> dict[str, object]:
        selected = self._selected_job()
        return {
            "panel_id": self.PANEL_ID,
            "workspace_id": self._workspace_id,
            "session_id": self._session_id,
            "target_kind": self._target_kind.value,
            "target_ref": self._target_ref,
            "workspace_root": self._workspace_root,
            "selected_cron_command": selected.command if selected is not None else None,
        }

    def on_key(self, event: events.Key) -> None:
        if event.key == "up":
            self._move_selection(-1)
            event.stop()
            return
        if event.key == "down":
            self._move_selection(1)
            event.stop()
            return
        if event.key == "r":
            self.refresh_jobs()
            event.stop()

    def refresh_jobs(self, *, selected_command: str | None = None) -> None:
        snapshot = self._cron_adapter.list_jobs(
            target_kind=self._target_kind,
            target_ref=self._target_ref,
        )
        self._jobs = snapshot.jobs
        self._message = snapshot.message or ""
        self._sync_selection(selected_command)
        self._render_state()
        self._publish_panel_state()

    def _sync_selection(self, selected_command: str | None = None) -> None:
        if not self._jobs:
            self._selected_index = 0
            return
        if selected_command:
            for index, job in enumerate(self._jobs):
                if job.command == selected_command:
                    self._selected_index = index
                    return
        self._selected_index = max(0, min(self._selected_index, len(self._jobs) - 1))

    def _move_selection(self, delta: int) -> None:
        if not self._jobs:
            return
        self._selected_index = max(0, min(len(self._jobs) - 1, self._selected_index + delta))
        self._render_state()
        self._publish_panel_state()

    def _render_state(self) -> None:
        self.update(self._render_text())

    def _render_text(self) -> str:
        lines = [
            f"Workspace: {self._workspace_name}",
            f"Root: {self._workspace_root or '(none)'}",
            f"Jobs: {len(self._jobs)}",
            "",
            "Crontab:",
        ]
        if not self._jobs:
            lines.append(self._message or "No crontab configured.")
        else:
            for index, job in enumerate(self._jobs[:12]):
                marker = ">" if index == self._selected_index else " "
                state = "on" if job.enabled else "off"
                lines.append(f"{marker} [{state}] {job.schedule} {job.command}")
        lines.extend(["", "Selected detail:"])
        selected = self._selected_job()
        if selected is None:
            lines.append(self._message or "No cron job selected.")
        else:
            lines.append(f"schedule={selected.schedule}")
            lines.append(f"command={selected.command}")
            lines.append(f"enabled={'yes' if selected.enabled else 'no'}")
            if selected.comment:
                lines.append(f"comment={selected.comment}")
        lines.extend(
            [
                "",
                "Use Up/Down to inspect jobs. Press r to refresh. Use /cron enable or /cron disable for the selected job.",
            ]
        )
        return "\n".join(lines)

    def _selected_job(self) -> CronJob | None:
        if not self._jobs:
            return None
        if self._selected_index >= len(self._jobs):
            self._selected_index = 0
        return self._jobs[self._selected_index]

    def _publish_panel_state(self) -> None:
        self._event_bus.publish(
            PanelStateChanged(
                panel_id=self.PANEL_ID,
                snapshot=dict(self.snapshot_state().snapshot),
            )
        )

    @staticmethod
    def _optional_str(value: object) -> str | None:
        return value if isinstance(value, str) else None

    @staticmethod
    def _target_kind_from_context(value: object) -> SessionTargetKind:
        if isinstance(value, SessionTargetKind):
            return value
        if isinstance(value, str):
            try:
                return SessionTargetKind(value)
            except ValueError:
                return SessionTargetKind.LOCAL
        return SessionTargetKind.LOCAL
