"""Load declarative YAML and TCSS configuration files."""

from __future__ import annotations

from pathlib import Path

import yaml

from cockpit.shared.config import config_dir, layouts_dir, themes_dir


class ConfigLoader:
    """Loads the project configuration files used by the bootstrap slice."""

    def __init__(self, *, start: Path | None = None) -> None:
        self._start = start

    def load_layout_definition(self, layout_id: str = "default") -> dict[str, object]:
        path = layouts_dir(self._start) / f"{layout_id}.yaml"
        return self._load_yaml(path)

    def load_keybindings(self) -> dict[str, object]:
        return self._load_yaml(config_dir(self._start) / "keybindings.yaml")

    def load_command_catalog(self) -> dict[str, object]:
        return self._load_yaml(config_dir(self._start) / "commands.yaml")

    def load_theme(self, theme_name: str = "default") -> str:
        path = themes_dir(self._start) / f"{theme_name}.tcss"
        return path.read_text(encoding="utf-8")

    def _load_yaml(self, path: Path) -> dict[str, object]:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            msg = f"Expected mapping payload in '{path}'."
            raise ValueError(msg)
        return payload
