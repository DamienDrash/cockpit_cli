"""Reference GitPanel implementation."""

from __future__ import annotations

from pathlib import Path

from textual import events
from textual.widgets import Static

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.domain.events.runtime_events import PanelMounted, PanelStateChanged
from cockpit.domain.models.panel_state import PanelState
from cockpit.infrastructure.git.git_adapter import GitAdapter, GitFileStatus, GitRepositoryStatus
from cockpit.shared.enums import SessionTargetKind


class GitPanel(Static):
    """Read-only repository status panel for the first domain slice."""

    PANEL_ID = "git-panel"
    PANEL_TYPE = "git"
    can_focus = True

    def __init__(self, *, event_bus: EventBus, git_adapter: GitAdapter) -> None:
        super().__init__("", id=self.PANEL_ID, markup=False)
        self._event_bus = event_bus
        self._git_adapter = git_adapter
        self._workspace_name = "No workspace"
        self._workspace_root = ""
        self._workspace_id: str | None = None
        self._session_id: str | None = None
        self._target_kind = SessionTargetKind.LOCAL
        self._target_ref: str | None = None
        self._repo_root = ""
        self._branch_summary = ""
        self._message = "No git state loaded."
        self._files: list[GitFileStatus] = []
        self._selected_path = ""

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
        selected_path = context.get("selected_path")
        if isinstance(selected_path, str) and selected_path:
            self._selected_path = selected_path
        self.refresh_status()

    def restore_state(self, snapshot: dict[str, object]) -> None:
        selected_path = snapshot.get("selected_path")
        if isinstance(selected_path, str) and selected_path:
            self._selected_path = selected_path

    def snapshot_state(self) -> PanelState:
        return PanelState(
            panel_id=self.PANEL_ID,
            panel_type=self.PANEL_TYPE,
            snapshot={
                "selected_path": self._selected_path or self._repo_root or self._workspace_root,
            },
        )

    def suspend(self) -> None:
        """No runtime resources need suspension yet."""

    def resume(self) -> None:
        self.refresh_status()

    def dispose(self) -> None:
        """No runtime resources need disposal yet."""

    def command_context(self) -> dict[str, object]:
        return {
            "panel_id": self.PANEL_ID,
            "workspace_id": self._workspace_id,
            "session_id": self._session_id,
            "target_kind": self._target_kind.value,
            "target_ref": self._target_ref,
            "workspace_root": self._workspace_root,
            "repo_root": self._repo_root or self._workspace_root,
            "selected_path": self._selected_path or self._repo_root or self._workspace_root,
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
            self.refresh_status()
            event.stop()

    def refresh_status(self) -> None:
        status = self._git_adapter.inspect_repository(
            self._workspace_root,
            target_kind=self._target_kind,
            target_ref=self._target_ref,
        )
        self._apply_status(status)
        self._publish_panel_state()

    def _apply_status(self, status: GitRepositoryStatus) -> None:
        self._repo_root = status.repo_root
        self._branch_summary = status.branch_summary
        self._files = status.files
        self._message = status.message or ""
        self._sync_selected_path()
        self._render_state()

    def _sync_selected_path(self) -> None:
        available_paths = {entry.path for entry in self._files}
        if self._selected_path in available_paths:
            return
        if self._files:
            self._selected_path = self._files[0].path
            return
        self._selected_path = self._repo_root or self._workspace_root

    def _move_selection(self, delta: int) -> None:
        if not self._files:
            return
        current_index = 0
        for index, entry in enumerate(self._files):
            if entry.path == self._selected_path:
                current_index = index
                break
        next_index = max(0, min(len(self._files) - 1, current_index + delta))
        self._selected_path = self._files[next_index].path
        self._render_state()
        self._publish_panel_state()

    def _render_state(self) -> None:
        self.update(self._render_text())

    def _render_text(self) -> str:
        summary_lines = [
            f"Workspace: {self._workspace_name}",
            f"Repo: {self._repo_root or self._workspace_root or '(none)'}",
            f"Branch: {self._branch_summary or '(unknown)'}",
            "",
            "Files:",
        ]
        if not self._files:
            summary_lines.append(self._message or "No tracked changes.")
        else:
            for entry in self._files[:20]:
                marker = ">" if entry.path == self._selected_path else " "
                summary_lines.append(
                    f"{marker} {entry.status_code} {self._display_path(entry.path)}"
                )
        note = self._message or "Use Up/Down to inspect entries. Press r to refresh."
        summary_lines.extend(["", note])
        return "\n".join(summary_lines)

    def _display_path(self, absolute_path: str) -> str:
        if not self._repo_root:
            return absolute_path
        try:
            return str(Path(absolute_path).resolve().relative_to(Path(self._repo_root).resolve()))
        except Exception:
            return absolute_path

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
