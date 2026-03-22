"""Workspace and file context widget."""

from __future__ import annotations

from textual.widgets import Static


class FileContext(Static):
    """Shows the current workspace and panel path context."""

    def __init__(self) -> None:
        super().__init__("Open a workspace to load the WorkPanel.", id="file-context")

    def update_context(
        self,
        *,
        workspace_name: str,
        workspace_root: str,
        cwd: str,
        selected_path: str,
        restored: bool,
        target_label: str | None = None,
        risk_label: str | None = None,
        recovery_message: str | None = None,
    ) -> None:
        mode = "restored" if restored else "fresh"
        lines = [
            f"Workspace: {workspace_name}",
            f"Root: {workspace_root}",
            f"CWD: {cwd}",
            f"Selected: {selected_path}",
            f"Session: {mode}",
        ]
        if target_label:
            lines.append(f"Target: {target_label}")
        if risk_label:
            lines.append(f"Risk: {risk_label}")
        if recovery_message:
            lines.append(f"Recovery: {recovery_message}")
        self.update("\n".join(lines))
