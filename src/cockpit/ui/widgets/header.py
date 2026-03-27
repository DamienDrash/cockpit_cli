"""Cyberpunk-themed header for Cockpit."""

import os
import sys
from importlib.metadata import version as get_version
from pathlib import Path

from rich.table import Table
from textual.app import RenderResult
from textual.widgets import Header

from cockpit.ui.branding import C_PRIMARY, C_SECONDARY


class CockpitHeader(Header):
    """Custom header with Cyberpunk branding and environment status."""

    def render(self) -> RenderResult:
        """Render the header with dynamic info using a Table for alignment."""
        try:
            ver = get_version("cockpit-cli")
        except Exception:
            ver = "0.1.44"

        # Use a table to ensure perfect left/right alignment
        table = Table.grid(expand=True)
        table.add_column("left", justify="left")
        table.add_column("right", justify="right")

        left_text = Text()
        left_text.append(" COCKPIT ", style=f"{C_PRIMARY} reverse")
        left_text.append(f" v{ver} ", style=C_SECONDARY)
        left_text.append(" ❯ ", style="white")
        left_text.append(self.app.title, style="bold white")
        
        table.add_row(left_text, self._get_env_badge())
        return table

    def _get_env_badge(self) -> Text:
        """Detect active developer environment (venv, node, cloud)."""
        badge = Text()
        
        # 1. Python Environment
        venv = os.environ.get("VIRTUAL_ENV")
        conda = os.environ.get("CONDA_DEFAULT_ENV")
        if venv:
            badge.append(f" py:{Path(venv).name} ", style="on #4B8BBE black")
        elif conda:
            badge.append(f" py:{conda} ", style="on #4B8BBE black")
        else:
            py_ver = f"{sys.version_info.major}.{sys.version_info.minor}"
            badge.append(f" py:{py_ver} ", style="dim")

        # 2. Node.js (Very basic check if in a node project)
        if Path("package.json").exists():
            badge.append(" node ", style="on #68A063 black")

        # 3. Cloud Context (Mock detection for now)
        kube_config = os.environ.get("KUBECONFIG")
        if kube_config:
            badge.append(" k8s ", style="on #326CE5 white")

        return badge
