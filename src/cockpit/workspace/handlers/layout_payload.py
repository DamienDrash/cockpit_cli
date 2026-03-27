"""Shared helpers for turning layout models into UI payloads."""

from __future__ import annotations

from cockpit.workspace.models.layout import Layout, PanelRef, SplitNode


def layout_tabs_payload(layout: Layout) -> list[dict[str, object]]:
    with open("/tmp/layout-debug.txt", "a") as f:
        f.write(
            f"DEBUG: layout_tabs_payload called with layout {layout.id} containing {len(layout.tabs)} tabs\\n"
        )
    tabs: list[dict[str, object]] = []
    for tab in layout.tabs:
        panel = first_panel_ref(tab.root_split)
        tabs.append(
            {
                "id": tab.id,
                "name": tab.name,
                "panel_id": panel.panel_id if panel is not None else f"{tab.id}-panel",
                "panel_type": panel.panel_type if panel is not None else tab.id,
                "root_split": split_node_to_payload(tab.root_split),
            }
        )
    return tabs


def split_node_to_payload(node: SplitNode) -> dict[str, object]:
    return {
        "orientation": node.orientation,
        "ratio": node.ratio,
        "children": [
            {
                "panel_id": child.panel_id,
                "panel_type": child.panel_type,
            }
            if isinstance(child, PanelRef)
            else split_node_to_payload(child)
            for child in node.children
        ],
    }


def first_panel_ref(node: SplitNode) -> PanelRef | None:
    for child in node.children:
        if isinstance(child, PanelRef):
            return child
        if isinstance(child, SplitNode):
            panel = first_panel_ref(child)
            if panel is not None:
                return panel
    return None
