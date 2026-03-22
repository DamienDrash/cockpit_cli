"""Tab bar placeholder widget."""

from textual.widgets import Static


class TabBar(Static):
    """Minimal tab bar placeholder."""

    def __init__(self) -> None:
        super().__init__("Tabs: work | Workspace: none", id="tab-bar")

    def set_workspace(self, workspace_name: str, *, restored: bool) -> None:
        state = "restored" if restored else "fresh"
        self.update(f"Tabs: work | Workspace: {workspace_name} | Session: {state}")
