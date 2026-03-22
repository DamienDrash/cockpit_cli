"""Reference DockerPanel implementation."""

from __future__ import annotations

from textual import events
from textual.widgets import Static

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.domain.events.runtime_events import PanelMounted, PanelStateChanged
from cockpit.domain.models.panel_state import PanelState
from cockpit.infrastructure.docker.docker_adapter import (
    DockerAdapter,
    DockerContainerSummary,
    DockerRuntimeSnapshot,
)
from cockpit.shared.enums import SessionTargetKind


class DockerPanel(Static):
    """Read-only docker runtime panel for local container inspection."""

    PANEL_ID = "docker-panel"
    PANEL_TYPE = "docker"
    can_focus = True

    def __init__(self, *, event_bus: EventBus, docker_adapter: DockerAdapter) -> None:
        super().__init__("", id=self.PANEL_ID, markup=False)
        self._event_bus = event_bus
        self._docker_adapter = docker_adapter
        self._workspace_name = "No workspace"
        self._workspace_root = ""
        self._workspace_id: str | None = None
        self._session_id: str | None = None
        self._target_kind = SessionTargetKind.LOCAL
        self._target_ref: str | None = None
        self._containers: list[DockerContainerSummary] = []
        self._selected_container_id: str | None = None
        self._message = "No docker state loaded."

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
        selected_container_id = context.get("selected_container_id")
        if isinstance(selected_container_id, str) and selected_container_id:
            self._selected_container_id = selected_container_id
        self.refresh_runtime()

    def restore_state(self, snapshot: dict[str, object]) -> None:
        selected_container_id = snapshot.get("selected_container_id")
        if isinstance(selected_container_id, str) and selected_container_id:
            self._selected_container_id = selected_container_id

    def snapshot_state(self) -> PanelState:
        return PanelState(
            panel_id=self.PANEL_ID,
            panel_type=self.PANEL_TYPE,
            snapshot={"selected_container_id": self._selected_container_id},
        )

    def suspend(self) -> None:
        """No runtime resources need suspension yet."""

    def resume(self) -> None:
        self.refresh_runtime()

    def dispose(self) -> None:
        """No runtime resources need disposal yet."""

    def command_context(self) -> dict[str, object]:
        selected = self._selected_container()
        return {
            "panel_id": self.PANEL_ID,
            "workspace_id": self._workspace_id,
            "session_id": self._session_id,
            "workspace_name": self._workspace_name,
            "target_kind": self._target_kind.value,
            "target_ref": self._target_ref,
            "workspace_root": self._workspace_root,
            "selected_container_id": self._selected_container_id,
            "selected_container_name": selected.name if selected is not None else None,
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
            self.refresh_runtime()
            event.stop()

    def refresh_runtime(self) -> None:
        snapshot = self._docker_adapter.list_containers(
            target_kind=self._target_kind,
            target_ref=self._target_ref,
        )
        self._apply_snapshot(snapshot)
        self._publish_panel_state()

    def _apply_snapshot(self, snapshot: DockerRuntimeSnapshot) -> None:
        self._containers = snapshot.containers
        self._message = snapshot.message or ""
        self._sync_selected_container()
        self._render_state()

    def _sync_selected_container(self) -> None:
        available_ids = {container.container_id for container in self._containers}
        if self._selected_container_id in available_ids:
            return
        self._selected_container_id = (
            self._containers[0].container_id if self._containers else None
        )

    def _move_selection(self, delta: int) -> None:
        if not self._containers:
            return
        current_index = 0
        for index, container in enumerate(self._containers):
            if container.container_id == self._selected_container_id:
                current_index = index
                break
        next_index = max(0, min(len(self._containers) - 1, current_index + delta))
        self._selected_container_id = self._containers[next_index].container_id
        self._render_state()
        self._publish_panel_state()

    def _render_state(self) -> None:
        self.update(self._render_text())

    def _render_text(self) -> str:
        lines = [
            f"Workspace: {self._workspace_name}",
            f"Root: {self._workspace_root or '(none)'}",
            f"Containers: {len(self._containers)}",
            "",
            "Runtime:",
        ]
        if not self._containers:
            lines.append(self._message or "No docker containers found.")
        else:
            for container in self._containers[:12]:
                marker = ">" if container.container_id == self._selected_container_id else " "
                lines.append(
                    f"{marker} {container.name} [{container.state}] {container.image}"
                )
        lines.extend(["", "Selected detail:"])
        selected = self._selected_container()
        if selected is None:
            lines.append(self._message or "No container selected.")
        else:
            lines.extend(
                [
                    f"id={selected.container_id}",
                    f"status={selected.status}",
                    f"ports={selected.ports or '(none)'}",
                ]
            )
        lines.extend(
            [
                "",
                "Use Up/Down to inspect containers. Press r to refresh. Press F8/F9/F10 to restart, stop, or remove the selected container.",
            ]
        )
        return "\n".join(lines)

    def _selected_container(self) -> DockerContainerSummary | None:
        for container in self._containers:
            if container.container_id == self._selected_container_id:
                return container
        return self._containers[0] if self._containers else None

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
