"""Repository-backed loading for declarative Stage 4 runbooks."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import yaml

from cockpit.ops.models.response import RunbookDefinition
from cockpit.infrastructure.runbooks.schema import validate_runbook_payload


class RunbookLoader:
    """Load validated runbooks from the repository configuration tree."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def discover(self) -> list[RunbookDefinition]:
        """Load all declarative runbooks from disk."""

        if not self._root.exists():
            return []
        definitions: list[RunbookDefinition] = []
        for path in sorted(self._root.rglob("*.yaml")):
            raw_text = path.read_text(encoding="utf-8")
            payload = yaml.safe_load(raw_text) or {}
            if not isinstance(payload, dict):
                msg = f"Runbook file '{path}' must load into an object."
                raise ValueError(msg)
            checksum = sha256(raw_text.encode("utf-8")).hexdigest()
            definitions.append(
                validate_runbook_payload(
                    payload,
                    source_path=str(path),
                    checksum=checksum,
                )
            )
        return definitions
