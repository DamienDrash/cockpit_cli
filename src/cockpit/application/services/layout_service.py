"""Layout service."""

from __future__ import annotations

from cockpit.domain.models.layout import Layout, PanelRef, SplitNode, TabLayout
from cockpit.domain.models.workspace import Workspace
from cockpit.infrastructure.config.config_loader import ConfigLoader
from cockpit.infrastructure.persistence.repositories import LayoutRepository


class LayoutService:
    """Loads and persists the layout selected for a workspace."""

    def __init__(
        self,
        layout_repository: LayoutRepository,
        config_loader: ConfigLoader,
    ) -> None:
        self._layout_repository = layout_repository
        self._config_loader = config_loader

    def resolve_for_workspace(self, workspace: Workspace) -> Layout:
        layout_id = workspace.default_layout_id or "default"
        layout = self._layout_repository.get(layout_id)
        if layout is not None:
            return layout

        payload = self._config_loader.load_layout_definition(layout_id)
        layout = self._layout_from_payload(payload)
        self._layout_repository.save(layout)
        return layout

    def _layout_from_payload(self, payload: dict[str, object]) -> Layout:
        raw_tabs = payload.get("tabs", [])
        tabs: list[TabLayout] = []
        for raw_tab in raw_tabs if isinstance(raw_tabs, list) else []:
            if not isinstance(raw_tab, dict):
                continue
            tabs.append(
                TabLayout(
                    id=str(raw_tab["id"]),
                    name=str(raw_tab["name"]),
                    root_split=self._decode_split_node(raw_tab["root_split"]),
                )
            )
        return Layout(
            id=str(payload.get("id", "default")),
            name=str(payload.get("name", "Default")),
            tabs=tabs,
            focus_path=[str(item) for item in payload.get("focus_path", [])],
        )

    def _decode_split_node(self, raw_node: object) -> SplitNode:
        if not isinstance(raw_node, dict):
            msg = "Layout split node must be a mapping."
            raise TypeError(msg)

        raw_children = raw_node.get("children", [])
        children: list[SplitNode | PanelRef] = []
        for child in raw_children if isinstance(raw_children, list) else []:
            if isinstance(child, dict) and {"panel_id", "panel_type"} <= set(child.keys()):
                children.append(
                    PanelRef(
                        panel_id=str(child["panel_id"]),
                        panel_type=str(child["panel_type"]),
                    )
                )
            else:
                children.append(self._decode_split_node(child))

        return SplitNode(
            orientation=(
                str(raw_node["orientation"])
                if raw_node.get("orientation") is not None
                else None
            ),
            ratio=float(raw_node["ratio"]) if raw_node.get("ratio") is not None else None,
            children=children,
        )
