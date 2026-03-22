"""Layout models."""

from __future__ import annotations

from dataclasses import dataclass, field

from cockpit.shared.utils import serialize_contract


@dataclass(slots=True)
class PanelRef:
    panel_id: str
    panel_type: str


@dataclass(slots=True)
class SplitNode:
    orientation: str | None
    ratio: float | None
    children: list["SplitNode | PanelRef"] = field(default_factory=list)


@dataclass(slots=True)
class TabLayout:
    id: str
    name: str
    root_split: SplitNode


@dataclass(slots=True)
class Layout:
    id: str
    name: str
    tabs: list[TabLayout]
    focus_path: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)
