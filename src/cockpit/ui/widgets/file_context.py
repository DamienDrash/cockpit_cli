"""Workspace and file context widget with intelligent path truncation."""

from __future__ import annotations

from pathlib import Path
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
        
        # Intelligent path truncation
        def truncate(p: str, max_len: int = 35) -> str:
            if len(p) <= max_len: return p
            return p[:15] + "..." + p[-(max_len-18):]

        lines = [
            f"WS: [bold]{workspace_name}[/]",
            f"Root: {truncate(workspace_root)}",
            f"CWD:  {truncate(cwd)}",
            f"File: {truncate(selected_path)}",
            f"Mode: [cyan]{mode}[/]",
        ]
        if target_label:
            lines.append(f"Tgt:  [yellow]{target_label}[/]")
        if risk_label:
            lines.append(f"Risk: {risk_label}")
        
        self.update("\n".join(lines))
