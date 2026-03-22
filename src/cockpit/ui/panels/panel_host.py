"""Workspace panel host."""

from __future__ import annotations

import copy
from collections.abc import Iterable

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical

from cockpit.bootstrap import ApplicationContainer
from cockpit.domain.models.panel_state import PanelState
from cockpit.ui.panels.registry import PanelContract


class PanelHost(Vertical):
    """Hosts the reference panel set and materializes layout split trees."""

    def __init__(self, *, container: ApplicationContainer) -> None:
        super().__init__(id="panel-host")
        self._container = container
        self._panels_by_id = self._container.panel_registry.create_panels(container)
        self._surface = Vertical(id="panel-surface")
        self._parking = Vertical(id="panel-parking")
        self._active_tab_id = "work"
        self._layout_id = "default"
        self._layout_render_scheduled = False
        self._pending_focus_panel_id: str | None = None
        self._tabs: list[dict[str, object]] = [
            {
                "id": "work",
                "name": "Work",
                "panel_id": "work-panel",
                "panel_type": "work",
                "root_split": {
                    "orientation": "vertical",
                    "ratio": 1.0,
                    "children": [
                        {
                            "panel_id": "work-panel",
                            "panel_type": "work",
                        }
                    ],
                },
            }
        ]

    def compose(self) -> ComposeResult:
        yield self._surface
        yield self._parking

    async def on_mount(self) -> None:
        self._parking.display = False
        await self._parking.mount(*self._panels_by_id.values())
        self._queue_layout_render()

    def load_workspace(self, context: dict[str, object]) -> None:
        layout_id = context.get("layout_id")
        if isinstance(layout_id, str) and layout_id:
            self._layout_id = layout_id
        self._tabs = self._normalize_tabs(context.get("tabs"))
        snapshot = context.get("snapshot")
        panel_snapshots = self._panel_snapshots(snapshot if isinstance(snapshot, dict) else {})
        for panel_id, panel in self._panels_by_id.items():
            panel_snapshot = panel_snapshots.get(panel_id, {})
            panel_context = dict(context)
            panel_context.update(panel_snapshot)
            panel.initialize(panel_context)
            panel.restore_state(panel_snapshot)
        active_tab_id = context.get("active_tab_id")
        self._active_tab_id = (
            str(active_tab_id) if isinstance(active_tab_id, str) and active_tab_id else "work"
        )
        self.set_active_tab(self._active_tab_id, focus=False)

    def focus_terminal(self) -> None:
        panel = self._panels_by_id.get("work-panel")
        focus_terminal = getattr(panel, "focus_terminal", None)
        if callable(focus_terminal):
            focus_terminal()

    def command_context(self) -> dict[str, object]:
        context = self._active_panel().command_context()
        context["layout_id"] = self._layout_id
        context["active_tab_id"] = self._active_tab_id
        context["available_tab_ids"] = [str(tab["id"]) for tab in self._tabs]
        context["tabs"] = copy.deepcopy(self._tabs)
        context["visible_panel_ids"] = self._panel_ids_for_tab(self._active_tab_id)
        context["focused_panel_id"] = self._active_panel().PANEL_ID
        return context

    def snapshot_state(self) -> PanelState:
        panels = self._panels()
        active_state = self._active_panel().snapshot_state()
        panel_snapshots = {
            panel.PANEL_ID: panel.snapshot_state().snapshot
            for panel in panels
        }
        work_snapshot = panel_snapshots.get("work-panel", {})
        snapshot = dict(active_state.snapshot)
        if "cwd" in work_snapshot:
            snapshot["cwd"] = work_snapshot["cwd"]
        if "browser_path" in work_snapshot:
            snapshot["browser_path"] = work_snapshot["browser_path"]
        snapshot["panels"] = panel_snapshots
        snapshot["active_tab_id"] = self._active_tab_id
        snapshot["tabs"] = copy.deepcopy(self._tabs)
        return PanelState(
            panel_id=active_state.panel_id,
            panel_type=active_state.panel_type,
            snapshot=snapshot,
            config=dict(active_state.config),
            persist_policy=active_state.persist_policy,
        )

    def set_active_tab(self, tab_id: str, *, focus: bool = True) -> str:
        next_tab = tab_id if tab_id in {str(tab["id"]) for tab in self._tabs} else str(self._tabs[0]["id"])
        self._active_tab_id = next_tab
        if focus:
            self._pending_focus_panel_id = self._panel_ids_for_tab(next_tab)[0]
        self._queue_layout_render()
        return next_tab

    def active_tab_id(self) -> str:
        return self._active_tab_id

    def shutdown(self) -> None:
        for panel in self._panels():
            panel.dispose()

    def available_tabs(self) -> list[tuple[str, str]]:
        return [(str(tab["id"]), str(tab["name"])) for tab in self._tabs]

    def apply_tabs(
        self,
        tabs: list[dict[str, object]],
        *,
        active_tab_id: str | None = None,
        focus: bool = False,
    ) -> None:
        self._tabs = self._normalize_tabs(tabs)
        if isinstance(active_tab_id, str) and active_tab_id:
            self._active_tab_id = active_tab_id
        if focus:
            visible = self._panel_ids_for_tab(self._active_tab_id)
            self._pending_focus_panel_id = visible[0] if visible else None
        self._queue_layout_render()

    def refresh_panel(self, panel_id: str) -> None:
        panel = self._panels_by_id.get(panel_id)
        if panel is not None:
            panel.resume()

    def deliver_panel_result(self, panel_id: str, payload: dict[str, object]) -> None:
        panel = self._panels_by_id.get(panel_id)
        if panel is not None:
            panel.apply_command_result(payload)

    def focus_panel(self, panel_id: str) -> None:
        panel = self._panels_by_id.get(panel_id)
        if panel is None:
            return
        self._pending_focus_panel_id = panel_id
        self._queue_layout_render()

    def focus_next_panel(self) -> None:
        visible_panel_ids = self._panel_ids_for_tab(self._active_tab_id)
        if not visible_panel_ids:
            return
        current_id = self._active_panel().PANEL_ID
        if current_id in visible_panel_ids:
            next_index = (visible_panel_ids.index(current_id) + 1) % len(visible_panel_ids)
        else:
            next_index = 0
        self.focus_panel(visible_panel_ids[next_index])

    def _active_panel(self) -> PanelContract:
        panel = self._focused_panel()
        if panel is not None:
            return panel
        visible_panel_ids = self._panel_ids_for_tab(self._active_tab_id)
        active_panel_id = visible_panel_ids[0] if visible_panel_ids else self._tab_panel_id(self._active_tab_id)
        panel = self._panels_by_id.get(active_panel_id)
        if panel is not None:
            return panel
        return next(iter(self._panels_by_id.values()))

    def _panels(self) -> list[PanelContract]:
        return list(self._panels_by_id.values())

    def _panel_snapshots(self, snapshot: dict[str, object]) -> dict[str, dict[str, object]]:
        raw_panels = snapshot.get("panels", {})
        if not isinstance(raw_panels, dict):
            raw_panels = {}
        panel_snapshots: dict[str, dict[str, object]] = {}
        for panel_id, payload in raw_panels.items():
            if isinstance(panel_id, str) and isinstance(payload, dict):
                panel_snapshots[panel_id] = payload
        if "work-panel" not in panel_snapshots:
            panel_snapshots["work-panel"] = {
                key: value
                for key, value in snapshot.items()
                if key in {"cwd", "browser_path", "selected_path"}
            }
        return panel_snapshots

    def _normalize_tabs(self, raw_tabs: object) -> list[dict[str, object]]:
        if not isinstance(raw_tabs, list):
            return list(self._tabs)
        tabs: list[dict[str, object]] = []
        for raw_tab in raw_tabs:
            if not isinstance(raw_tab, dict):
                continue
            tab_id = raw_tab.get("id")
            panel_id = raw_tab.get("panel_id")
            panel_type = raw_tab.get("panel_type")
            if not isinstance(tab_id, str) or not isinstance(panel_id, str):
                continue
            tabs.append(
                {
                    "id": tab_id,
                    "name": str(raw_tab.get("name", tab_id.title())),
                    "panel_id": panel_id,
                    "panel_type": str(panel_type or tab_id),
                    "root_split": (
                        raw_tab.get("root_split")
                        if isinstance(raw_tab.get("root_split"), dict)
                        else {
                            "orientation": "vertical",
                            "ratio": 1.0,
                            "children": [
                                {
                                    "panel_id": panel_id,
                                    "panel_type": str(panel_type or tab_id),
                                }
                            ],
                        }
                    ),
                }
            )
        return tabs or list(self._tabs)

    def _tab_panels(self) -> dict[str, PanelContract]:
        tabs: dict[str, PanelContract] = {}
        for tab in self._tabs:
            panel_id = self._tab_panel_id(str(tab["id"]))
            panel = self._panels_by_id.get(panel_id)
            if panel is not None:
                tabs[str(tab["id"])] = panel
        if "work" not in tabs:
            work_panel = self._panels_by_id.get("work-panel")
            if work_panel is not None:
                tabs["work"] = work_panel
        return tabs

    def _tab_panel_id(self, tab_id: str) -> str:
        panel_ids = self._panel_ids_for_tab(tab_id)
        if panel_ids:
            return panel_ids[0]
        return "work-panel"

    def _focused_panel(self) -> PanelContract | None:
        focused = getattr(self.screen, "focused", None)
        while focused is not None:
            panel_id = getattr(focused, "id", None)
            if isinstance(panel_id, str):
                panel = self._panels_by_id.get(panel_id)
                if panel is not None:
                    return panel
            focused = getattr(focused, "parent", None)
        return None

    def _panel_ids_for_tab(self, tab_id: str) -> list[str]:
        for tab in self._tabs:
            if tab["id"] == tab_id:
                return list(self._panel_ids_from_node(tab.get("root_split")))
        return ["work-panel"]

    def _panel_ids_from_node(self, raw_node: object) -> Iterable[str]:
        if not isinstance(raw_node, dict):
            return ()
        raw_children = raw_node.get("children", [])
        panel_ids: list[str] = []
        for child in raw_children if isinstance(raw_children, list) else []:
            if isinstance(child, dict) and isinstance(child.get("panel_id"), str):
                panel_ids.append(str(child["panel_id"]))
                continue
            panel_ids.extend(self._panel_ids_from_node(child))
        return panel_ids

    def _queue_layout_render(self) -> None:
        if not self.is_mounted or self._layout_render_scheduled:
            return
        self._layout_render_scheduled = True
        self.run_worker(self._render_active_layout(), exclusive=True, group="panel-layout")

    async def _render_active_layout(self) -> None:
        try:
            await self._surface.remove_children()
            visible_panel_ids = set(self._panel_ids_for_tab(self._active_tab_id))
            for panel in self._panels():
                if panel.PANEL_ID not in visible_panel_ids:
                    if panel.parent is not None and panel.parent is not self._parking:
                        await panel.remove()
                        await self._parking.mount(panel)
                    panel.display = False
                    panel.suspend()
            root_split = self._root_split_for_tab(self._active_tab_id)
            if root_split is None:
                return
            await self._mount_node(self._surface, root_split)
            for panel_id in visible_panel_ids:
                panel = self._panels_by_id.get(panel_id)
                if panel is None:
                    continue
                panel.display = True
                panel.resume()
            if self._pending_focus_panel_id:
                panel = self._panels_by_id.get(self._pending_focus_panel_id)
                if panel is not None and panel.PANEL_ID in visible_panel_ids:
                    panel.focus()
            self._pending_focus_panel_id = None
        finally:
            self._layout_render_scheduled = False

    async def _mount_node(
        self,
        parent: Vertical | Horizontal,
        raw_node: dict[str, object],
    ):
        panel_id = raw_node.get("panel_id")
        if isinstance(panel_id, str):
            panel = self._panels_by_id[panel_id]
            if panel.parent is not None:
                await panel.remove()
            await parent.mount(panel)
            return panel

        orientation = str(raw_node.get("orientation", "vertical"))
        children = raw_node.get("children", [])
        if not isinstance(children, list):
            children = []
        if len(children) == 1 and isinstance(children[0], dict) and isinstance(children[0].get("panel_id"), str):
            return await self._mount_node(parent, children[0])

        container = Horizontal(classes="split-node") if orientation == "horizontal" else Vertical(classes="split-node")
        await parent.mount(container)
        mounted_children = []
        for child in children:
            if isinstance(child, dict):
                mounted_child = await self._mount_node(container, child)
                if mounted_child is not None:
                    mounted_children.append(mounted_child)
        self._apply_child_ratios(container, mounted_children, raw_node)
        return container

    def _apply_child_ratios(self, container: Vertical | Horizontal, children: list[object], raw_node: dict[str, object]) -> None:
        if len(children) != 2:
            return
        ratio = raw_node.get("ratio", 0.5)
        try:
            first_ratio = float(ratio)
        except (TypeError, ValueError):
            first_ratio = 0.5
        first_ratio = max(0.2, min(0.8, first_ratio))
        second_ratio = max(0.2, min(0.8, round(1.0 - first_ratio, 2)))
        first, second = children
        if raw_node.get("orientation") == "horizontal":
            getattr(first, "styles").width = f"{int(first_ratio * 100)}%"
            getattr(second, "styles").width = f"{int(second_ratio * 100)}%"
            getattr(first, "styles").height = "1fr"
            getattr(second, "styles").height = "1fr"
        else:
            getattr(first, "styles").height = f"{int(first_ratio * 100)}%"
            getattr(second, "styles").height = f"{int(second_ratio * 100)}%"
            getattr(first, "styles").width = "1fr"
            getattr(second, "styles").width = "1fr"

    def _root_split_for_tab(self, tab_id: str) -> dict[str, object] | None:
        for tab in self._tabs:
            if tab["id"] == tab_id:
                root_split = tab.get("root_split")
                if isinstance(root_split, dict):
                    return root_split
        return None
