from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import textwrap
import unittest

from cockpit.core.dispatch.command_dispatcher import CommandDispatcher
from cockpit.core.dispatch.event_bus import EventBus
from cockpit.plugins.loader import PluginBootstrapContext, PluginLoader
from cockpit.ui.panels.registry import PanelRegistry


class PluginLoaderTests(unittest.TestCase):
    def test_loads_external_module_and_registers_panel_and_command(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            module_path = root / "fake_plugin.py"
            module_path.write_text(
                textwrap.dedent(
                    """
                    from cockpit.core.dispatch.handler_base import DispatchResult
                    from cockpit.core.panel_state import PanelState
                    from cockpit.ui.panels.registry import PanelSpec

                    class FakePanel:
                        PANEL_ID = "fake-panel"
                        PANEL_TYPE = "fake"
                        display = True

                        def __init__(self, id=None):
                            self.id = id

                        def initialize(self, context):
                            del context

                        def restore_state(self, snapshot):
                            del snapshot

                        def snapshot_state(self):
                            return PanelState(panel_id=self.PANEL_ID, panel_type=self.PANEL_TYPE, snapshot={})

                        def command_context(self):
                            return {"panel_id": self.PANEL_ID}

                        def suspend(self):
                            pass

                        def resume(self):
                            pass

                        def dispose(self):
                            pass

                        def focus(self):
                            pass

                    class EchoHandler:
                        def __call__(self, command):
                            del command
                            return DispatchResult(success=True, message="ok")

                    def register_plugin(context):
                        context.register_panel(
                            PanelSpec(
                                panel_type=FakePanel.PANEL_TYPE,
                                panel_id=FakePanel.PANEL_ID,
                                display_name="Fake",
                                factory=lambda container: FakePanel(id=FakePanel.PANEL_ID),
                            )
                        )
                        context.register_command("fake.echo", EchoHandler())
                    """
                ),
                encoding="utf-8",
            )

            sys.path.insert(0, str(root))
            try:
                registry = PanelRegistry()
                dispatcher = CommandDispatcher(event_bus=EventBus())
                command_catalog: list[str] = []
                loader = PluginLoader()

                loaded = loader.load_from_config(
                    {"plugins": [{"module": "fake_plugin"}]},
                    context=PluginBootstrapContext(
                        project_root=root,
                        panel_registry=registry,
                        command_dispatcher=dispatcher,
                        command_catalog=command_catalog,
                    ),
                )

                self.assertEqual(loaded, ["fake_plugin"])
                self.assertIsNotNone(registry.spec_for_panel_id("fake-panel"))
                self.assertIn("fake.echo", command_catalog)
                self.assertIsNone(loader.manifest_for_module("fake_plugin"))
            finally:
                sys.path.remove(str(root))
                sys.modules.pop("fake_plugin", None)


if __name__ == "__main__":
    unittest.main()
