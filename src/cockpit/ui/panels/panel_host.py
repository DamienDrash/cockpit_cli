"""Workspace panel host."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical

from cockpit.bootstrap import ApplicationContainer
from cockpit.domain.models.panel_state import PanelState
from cockpit.ui.panels.work_panel import WorkPanel


class PanelHost(Vertical):
    """Hosts the reference panel set for the first application slice."""

    def __init__(self, *, container: ApplicationContainer) -> None:
        super().__init__(id="panel-host")
        self._container = container

    def compose(self) -> ComposeResult:
        yield WorkPanel(
            event_bus=self._container.event_bus,
            pty_manager=self._container.pty_manager,
            stream_router=self._container.stream_router,
        )

    def load_workspace(self, context: dict[str, object]) -> None:
        work_panel = self.query_one(WorkPanel)
        snapshot = context.get("snapshot")
        if isinstance(snapshot, dict):
            work_panel.restore_state(snapshot)
        work_panel.initialize(context)

    def focus_terminal(self) -> None:
        self.query_one(WorkPanel).focus_terminal()

    def command_context(self) -> dict[str, object]:
        return self.query_one(WorkPanel).command_context()

    def snapshot_state(self) -> PanelState:
        return self.query_one(WorkPanel).snapshot_state()

    def shutdown(self) -> None:
        self.query_one(WorkPanel).dispose()
