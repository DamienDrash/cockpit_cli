"""Panel registry and factory contracts."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from cockpit.domain.models.panel_state import PanelState

if TYPE_CHECKING:
    from cockpit.bootstrap import ApplicationContainer


class PanelContract(Protocol):
    """Runtime contract shared by all hostable panels."""

    PANEL_ID: str
    PANEL_TYPE: str
    display: bool

    def initialize(self, context: dict[str, object]) -> None: ...

    def restore_state(self, snapshot: dict[str, object]) -> None: ...

    def snapshot_state(self) -> PanelState: ...

    def command_context(self) -> dict[str, object]: ...

    def suspend(self) -> None: ...

    def resume(self) -> None: ...

    def dispose(self) -> None: ...

    def focus(self) -> None: ...


PanelFactory = Callable[["ApplicationContainer"], PanelContract]


@dataclass(slots=True, frozen=True)
class PanelSpec:
    panel_type: str
    panel_id: str
    display_name: str
    factory: PanelFactory


class PanelRegistry:
    """Registers the panel types available to the UI shell."""

    def __init__(self) -> None:
        self._specs_by_type: "OrderedDict[str, PanelSpec]" = OrderedDict()
        self._specs_by_id: dict[str, PanelSpec] = {}

    def register(self, spec: PanelSpec) -> None:
        if spec.panel_type in self._specs_by_type:
            raise ValueError(f"Panel type '{spec.panel_type}' is already registered.")
        if spec.panel_id in self._specs_by_id:
            raise ValueError(f"Panel id '{spec.panel_id}' is already registered.")
        self._specs_by_type[spec.panel_type] = spec
        self._specs_by_id[spec.panel_id] = spec

    def create_panels(self, container: "ApplicationContainer") -> dict[str, PanelContract]:
        return {
            spec.panel_id: spec.factory(container)
            for spec in self._specs_by_type.values()
        }

    def spec_for_panel_id(self, panel_id: str) -> PanelSpec | None:
        return self._specs_by_id.get(panel_id)

    def spec_for_panel_type(self, panel_type: str) -> PanelSpec | None:
        return self._specs_by_type.get(panel_type)

    def specs(self) -> tuple[PanelSpec, ...]:
        return tuple(self._specs_by_type.values())
