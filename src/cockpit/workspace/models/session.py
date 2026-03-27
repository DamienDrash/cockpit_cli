"""Session model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from cockpit.core.enums import SessionStatus
from cockpit.core.utils import serialize_contract


@dataclass(slots=True)
class Session:
    id: str
    workspace_id: str
    name: str
    status: SessionStatus
    active_tab_id: str | None
    focused_panel_id: str | None
    snapshot_ref: str | None
    created_at: datetime
    updated_at: datetime
    last_opened_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)
