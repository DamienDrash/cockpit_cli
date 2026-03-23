"""Layout service."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

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

    def load_layout_document(self, layout_id: str) -> dict[str, object]:
        layout = self._require_layout(layout_id)
        return layout.to_dict()

    def validate_layout_document(
        self,
        payload: dict[str, Any],
        *,
        allowed_panel_types: set[str] | None = None,
        allowed_panel_ids: set[str] | None = None,
    ) -> dict[str, object]:
        layout = self._layout_from_payload(payload)
        errors = self._validate_layout(
            layout,
            allowed_panel_types=allowed_panel_types,
            allowed_panel_ids=allowed_panel_ids,
        )
        return {
            "ok": not errors,
            "errors": errors,
            "layout": layout.to_dict(),
        }

    def save_layout_document(
        self,
        payload: dict[str, Any],
        *,
        allowed_panel_types: set[str] | None = None,
        allowed_panel_ids: set[str] | None = None,
    ) -> Layout:
        validation = self.validate_layout_document(
            payload,
            allowed_panel_types=allowed_panel_types,
            allowed_panel_ids=allowed_panel_ids,
        )
        errors = validation["errors"]
        if isinstance(errors, list) and errors:
            raise ValueError("; ".join(str(item) for item in errors))
        layout = self._layout_from_payload(payload)
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

    def move_panel_in_tab(
        self,
        *,
        layout_id: str,
        tab_id: str,
        panel_id: str,
        direction: str,
    ) -> Layout:
        layout = self._require_layout(layout_id)
        normalized_direction = direction.strip().lower()
        if normalized_direction not in {"previous", "next"}:
            raise ValueError("Layout panel direction must be 'previous' or 'next'.")
        updated_tabs: list[TabLayout] = []
        for tab in layout.tabs:
            if tab.id != tab_id:
                updated_tabs.append(self._clone_tab(tab))
                continue
            moved_root, _moved = self._move_panel(
                tab.root_split,
                panel_id,
                normalized_direction,
            )
            updated_tabs.append(
                TabLayout(
                    id=tab.id,
                    name=tab.name,
                    root_split=moved_root,
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

    def _validate_layout(
        self,
        layout: Layout,
        *,
        allowed_panel_types: set[str] | None,
        allowed_panel_ids: set[str] | None,
    ) -> list[str]:
        errors: list[str] = []
        if not layout.id.strip():
            errors.append("Layout id must not be empty.")
        if not layout.name.strip():
            errors.append("Layout name must not be empty.")
        if not layout.tabs:
            errors.append("Layout must contain at least one tab.")
        seen_tab_ids: set[str] = set()
        for tab in layout.tabs:
            if not tab.id.strip():
                errors.append("Tab id must not be empty.")
            if tab.id in seen_tab_ids:
                errors.append(f"Tab id '{tab.id}' is duplicated.")
            seen_tab_ids.add(tab.id)
            if not tab.name.strip():
                errors.append(f"Tab '{tab.id}' must have a name.")
            errors.extend(
                self._validate_split_node(
                    tab.root_split,
                    path=f"tabs[{tab.id}]",
                    allowed_panel_types=allowed_panel_types,
                    allowed_panel_ids=allowed_panel_ids,
                )
            )
        return errors

    def _validate_split_node(
        self,
        node: SplitNode,
        *,
        path: str,
        allowed_panel_types: set[str] | None,
        allowed_panel_ids: set[str] | None,
    ) -> list[str]:
        errors: list[str] = []
        if node.orientation not in {None, "horizontal", "vertical"}:
            errors.append(f"{path} has invalid orientation '{node.orientation}'.")
        if not node.children:
            errors.append(f"{path} must have at least one child.")
            return errors
        if node.ratio is not None:
            ratio_value = float(node.ratio)
            if len(node.children) == 1:
                if not 0.05 <= ratio_value <= 1.0:
                    errors.append(f"{path} ratio must be between 0.05 and 1.0.")
            elif not 0.05 <= ratio_value <= 0.95:
                errors.append(f"{path} ratio must be between 0.05 and 0.95.")
        if len(node.children) == 1 and isinstance(node.children[0], SplitNode):
            errors.append(f"{path} must not wrap a single nested split.")
        for index, child in enumerate(node.children):
            child_path = f"{path}.children[{index}]"
            if isinstance(child, PanelRef):
                if not child.panel_id.strip():
                    errors.append(f"{child_path} panel_id must not be empty.")
                if not child.panel_type.strip():
                    errors.append(f"{child_path} panel_type must not be empty.")
                if allowed_panel_types is not None and child.panel_type not in allowed_panel_types:
                    errors.append(f"{child_path} panel_type '{child.panel_type}' is not registered.")
                if allowed_panel_ids is not None and child.panel_id not in allowed_panel_ids:
                    errors.append(f"{child_path} panel_id '{child.panel_id}' is not registered.")
                continue
            errors.extend(
                self._validate_split_node(
                    child,
                    path=child_path,
                    allowed_panel_types=allowed_panel_types,
                    allowed_panel_ids=allowed_panel_ids,
                )
            )
        return errors

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

    def _move_panel(
        self,
        node: SplitNode,
        panel_id: str,
        direction: str,
    ) -> tuple[SplitNode, bool]:
        next_children: list[SplitNode | PanelRef] = []
        moved = False
        for child in node.children:
            if isinstance(child, PanelRef):
                next_children.append(
                    PanelRef(panel_id=child.panel_id, panel_type=child.panel_type)
                )
                continue
            moved_child, child_moved = self._move_panel(child, panel_id, direction)
            next_children.append(moved_child)
            moved = moved or child_moved
        if moved:
            return SplitNode(
                orientation=node.orientation,
                ratio=node.ratio,
                children=next_children,
            ), True

        panel_indexes = [
            index
            for index, child in enumerate(next_children)
            if isinstance(child, PanelRef) and child.panel_id == panel_id
        ]
        if not panel_indexes:
            return SplitNode(
                orientation=node.orientation,
                ratio=node.ratio,
                children=next_children,
            ), False
        index = panel_indexes[0]
        target = index - 1 if direction == "previous" else index + 1
        if target < 0 or target >= len(next_children):
            return SplitNode(
                orientation=node.orientation,
                ratio=node.ratio,
                children=next_children,
            ), False
        next_children[index], next_children[target] = next_children[target], next_children[index]
        return SplitNode(
            orientation=node.orientation,
            ratio=node.ratio,
            children=next_children,
        ), True
