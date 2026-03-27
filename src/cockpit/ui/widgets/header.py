"""Cyberpunk-themed header for Cockpit."""

import os
import sys
from importlib.metadata import version as get_version
from pathlib import Path

from rich.text import Text
from textual.app import RenderResult
from textual.widgets import Header

from cockpit.ui.branding import C_PRIMARY, C_SECONDARY


class CockpitHeader(Header):
    """Custom header with Cyberpunk branding and environment status."""

    def render(self) -> RenderResult:
        """Render the header with dynamic info and cyberpunk colors."""
        try:
            ver = get_version("cockpit-cli")
        except Exception:
            ver = "0.1.43"

        header_text = Text()
        header_text.append(" COCKPIT ", style=f"{C_PRIMARY} reverse")
        header_text.append(f" v{ver} ", style=C_SECONDARY)
        header_text.append(" ❯ ", style="white")
        header_text.append(self.app.title, style="bold white")
        
        # Add Environment Badges (Right aligned essentially via space)
        env_badge = self._get_env_badge()
        if env_badge:
            # Simple right-alignment strategy for fixed-height header
            available_space = self.app.size.width - len(header_text.plain) - len(env_badge.plain) - 2
            if available_space > 0:
                header_text.append(" " * available_space)
                header_text.append(env_badge)

        return header_text

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
