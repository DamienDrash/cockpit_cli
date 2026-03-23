from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cockpit.application.services.layout_service import LayoutService
from cockpit.domain.models.layout import Layout, PanelRef, SplitNode, TabLayout
from cockpit.infrastructure.config.config_loader import ConfigLoader
from cockpit.infrastructure.persistence.repositories import LayoutRepository
from cockpit.infrastructure.persistence.sqlite_store import SQLiteStore


class LayoutServiceTests(unittest.TestCase):
    def test_moves_panel_within_split_children(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "config").mkdir()
            store = SQLiteStore(root / "cockpit.db")
            repository = LayoutRepository(store)
            service = LayoutService(repository, ConfigLoader(start=root))
            layout = Layout(
                id="default",
                name="Default",
                tabs=[
                    TabLayout(
                        id="work",
                        name="Work",
                        root_split=SplitNode(
                            orientation="horizontal",
                            ratio=0.5,
                            children=[
                                PanelRef(panel_id="work-panel", panel_type="work"),
                                PanelRef(panel_id="db-panel", panel_type="db"),
                                PanelRef(panel_id="logs-panel", panel_type="logs"),
                            ],
                        ),
                    )
                ],
            )
            repository.save(layout)

            updated = service.move_panel_in_tab(
                layout_id="default",
                tab_id="work",
                panel_id="db-panel",
                direction="next",
            )

            children = updated.tabs[0].root_split.children
            self.assertEqual(
                [getattr(child, "panel_id", "") for child in children],
                ["work-panel", "logs-panel", "db-panel"],
            )
            store.close()
