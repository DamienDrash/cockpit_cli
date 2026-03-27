"""Base panel contract."""

from __future__ import annotations

from textual.containers import Vertical

from cockpit.core.panel_state import PanelState


class BasePanel(Vertical):
    """Common contract for panels hosted inside the workspace shell."""

    PANEL_ID = "panel"
    PANEL_TYPE = "panel"

    def initialize(self, context: dict[str, object]) -> None:
        """Load panel state from application context."""
        pass

    def restore_state(self, snapshot: dict[str, object]) -> None:
        """Apply the persisted panel snapshot."""
        pass

    def snapshot_state(self) -> PanelState:
        """Return the persistable state for the panel."""
        return PanelState(panel_id=self.PANEL_ID, panel_type=self.PANEL_TYPE)

    def apply_command_result(self, payload: dict[str, object]) -> None:
        """Apply command-result data routed back into the panel."""

    def suspend(self) -> None:
        """Pause panel-specific runtime resources."""

    def resume(self) -> None:
        """Resume panel-specific runtime resources."""

    def dispose(self) -> None:
        """Release panel-specific runtime resources."""
