"""Panel state model."""

from __future__ import annotations

from dataclasses import dataclass, field

from cockpit.core.enums import PanelPersistPolicy
from cockpit.core.utils import serialize_contract


@dataclass(slots=True)
class PanelState:
    panel_id: str
    panel_type: str
    config: dict[str, object] = field(default_factory=dict)
    snapshot: dict[str, object] = field(default_factory=dict)
    persist_policy: PanelPersistPolicy = PanelPersistPolicy.RUNTIME_RECREATED

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)
