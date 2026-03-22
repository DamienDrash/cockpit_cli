"""Layout service."""

from __future__ import annotations

from dataclasses import replace

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

    def list_layouts(self) -> list[Layout]:
        return self._layout_repository.list_all()

    def get_layout(self, layout_id: str) -> Layout | None:
        return self._layout_repository.get(layout_id)

    def save_layout(self, layout: Layout) -> Layout:
        self._layout_repository.save(layout)
        return layout

    def save_variant(
        self,
        *,
        source_layout_id: str,
        target_layout_id: str,
        name: str | None = None,
    ) -> Layout:
        source = self._layout_repository.get(source_layout_id)
        if source is None:
            raise LookupError(f"Layout '{source_layout_id}' was not found.")
        clone = Layout(
            id=target_layout_id,
            name=name or f"{source.name} Copy",
            tabs=[self._clone_tab(tab) for tab in source.tabs],
            focus_path=list(source.focus_path),
        )
        self._layout_repository.save(clone)
        return clone

    def toggle_tab_orientation(self, *, layout_id: str, tab_id: str) -> Layout:
        layout = self._require_layout(layout_id)
        updated_tabs: list[TabLayout] = []
        for tab in layout.tabs:
            if tab.id != tab_id:
                updated_tabs.append(self._clone_tab(tab))
                continue
            current = tab.root_split.orientation or "vertical"
            updated_tabs.append(
                TabLayout(
                    id=tab.id,
                    name=tab.name,
                    root_split=replace(
                        self._clone_split(tab.root_split),
                        orientation="horizontal" if current == "vertical" else "vertical",
                    ),
                )
            )
        updated = replace(layout, tabs=updated_tabs)
        self._layout_repository.save(updated)
        return updated

    def set_tab_ratio(self, *, layout_id: str, tab_id: str, ratio: float) -> Layout:
        layout = self._require_layout(layout_id)
        normalized_ratio = max(0.2, min(0.8, float(ratio)))
        updated_tabs: list[TabLayout] = []
        for tab in layout.tabs:
            if tab.id != tab_id:
                updated_tabs.append(self._clone_tab(tab))
                continue
            updated_tabs.append(
                TabLayout(
                    id=tab.id,
                    name=tab.name,
                    root_split=replace(
                        self._clone_split(tab.root_split),
                        ratio=normalized_ratio,
                    ),
                )
            )
        updated = replace(layout, tabs=updated_tabs)
        self._layout_repository.save(updated)
        return updated

    def add_panel_to_tab(
        self,
        *,
        layout_id: str,
        tab_id: str,
        panel_id: str,
        panel_type: str,
    ) -> Layout:
        layout = self._require_layout(layout_id)
        updated_tabs: list[TabLayout] = []
        new_panel = PanelRef(panel_id=panel_id, panel_type=panel_type)
        for tab in layout.tabs:
            if tab.id != tab_id:
                updated_tabs.append(self._clone_tab(tab))
                continue
            root_split = self._clone_split(tab.root_split)
            existing_children = list(root_split.children)
            if len(existing_children) == 1 and isinstance(existing_children[0], PanelRef):
                root_split = SplitNode(
                    orientation=root_split.orientation or "vertical",
                    ratio=root_split.ratio or 0.5,
                    children=[existing_children[0], new_panel],
                )
            else:
                root_split.children.append(new_panel)
                if root_split.orientation is None:
                    root_split.orientation = "vertical"
                if root_split.ratio is None:
                    root_split.ratio = 0.5
            updated_tabs.append(
                TabLayout(
                    id=tab.id,
                    name=tab.name,
                    root_split=root_split,
                )
            )
        updated = replace(layout, tabs=updated_tabs)
        self._layout_repository.save(updated)
        return updated

    def remove_panel_from_tab(
        self,
        *,
        layout_id: str,
        tab_id: str,
        panel_id: str,
    ) -> Layout:
        layout = self._require_layout(layout_id)
        updated_tabs: list[TabLayout] = []
        for tab in layout.tabs:
            if tab.id != tab_id:
                updated_tabs.append(self._clone_tab(tab))
                continue
            collapsed = self._remove_panel(tab.root_split, panel_id)
            if isinstance(collapsed, PanelRef):
                next_root = SplitNode(
                    orientation="vertical",
                    ratio=1.0,
                    children=[collapsed],
                )
            else:
                next_root = collapsed
            updated_tabs.append(
                TabLayout(id=tab.id, name=tab.name, root_split=next_root)
            )
        updated = replace(layout, tabs=updated_tabs)
        self._layout_repository.save(updated)
        return updated

    def replace_panel_in_tab(
        self,
        *,
        layout_id: str,
        tab_id: str,
        existing_panel_id: str,
        replacement_panel_id: str,
        replacement_panel_type: str,
    ) -> Layout:
        layout = self._require_layout(layout_id)
        updated_tabs: list[TabLayout] = []
        for tab in layout.tabs:
            if tab.id != tab_id:
                updated_tabs.append(self._clone_tab(tab))
                continue
            updated_tabs.append(
                TabLayout(
                    id=tab.id,
                    name=tab.name,
                    root_split=self._replace_panel(
                        tab.root_split,
                        existing_panel_id,
                        PanelRef(
                            panel_id=replacement_panel_id,
                            panel_type=replacement_panel_type,
                        ),
                    ),
                )
            )
        updated = replace(layout, tabs=updated_tabs)
        self._layout_repository.save(updated)
        return updated

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

    def _require_layout(self, layout_id: str) -> Layout:
        layout = self._layout_repository.get(layout_id)
        if layout is None:
            raise LookupError(f"Layout '{layout_id}' was not found.")
        return layout

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

    def _clone_tab(self, tab: TabLayout) -> TabLayout:
        return TabLayout(id=tab.id, name=tab.name, root_split=self._clone_split(tab.root_split))

    def _clone_split(self, node: SplitNode) -> SplitNode:
        children: list[SplitNode | PanelRef] = []
        for child in node.children:
            if isinstance(child, PanelRef):
                children.append(PanelRef(panel_id=child.panel_id, panel_type=child.panel_type))
            else:
                children.append(self._clone_split(child))
        return SplitNode(orientation=node.orientation, ratio=node.ratio, children=children)

    def _remove_panel(self, node: SplitNode, panel_id: str) -> SplitNode | PanelRef:
        next_children: list[SplitNode | PanelRef] = []
        for child in node.children:
            if isinstance(child, PanelRef):
                if child.panel_id != panel_id:
                    next_children.append(PanelRef(panel_id=child.panel_id, panel_type=child.panel_type))
                continue
            collapsed = self._remove_panel(child, panel_id)
            next_children.append(collapsed)
        if not next_children:
            return PanelRef(panel_id="work-panel", panel_type="work")
        if len(next_children) == 1 and isinstance(next_children[0], PanelRef):
            return next_children[0]
        if len(next_children) == 1 and isinstance(next_children[0], SplitNode):
            return next_children[0]
        return SplitNode(orientation=node.orientation, ratio=node.ratio, children=next_children)

    def _replace_panel(
        self,
        node: SplitNode,
        existing_panel_id: str,
        replacement: PanelRef,
    ) -> SplitNode:
        next_children: list[SplitNode | PanelRef] = []
        for child in node.children:
            if isinstance(child, PanelRef):
                if child.panel_id == existing_panel_id:
                    next_children.append(
                        PanelRef(
                            panel_id=replacement.panel_id,
                            panel_type=replacement.panel_type,
                        )
                    )
                else:
                    next_children.append(PanelRef(panel_id=child.panel_id, panel_type=child.panel_type))
            else:
                next_children.append(self._replace_panel(child, existing_panel_id, replacement))
        return SplitNode(orientation=node.orientation, ratio=node.ratio, children=next_children)
