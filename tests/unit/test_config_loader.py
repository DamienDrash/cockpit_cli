from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cockpit.infrastructure.config.config_loader import ConfigLoader


class ConfigLoaderTests(unittest.TestCase):
    def test_loads_project_configuration_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "config" / "layouts").mkdir(parents=True)
            (root / "config" / "themes").mkdir(parents=True)
            (root / "src").mkdir()
            (root / "pyproject.toml").write_text("[project]\nname='cockpit'\n", encoding="utf-8")
            (root / "config" / "layouts" / "default.yaml").write_text(
                "id: default\nname: Default\n",
                encoding="utf-8",
            )
            (root / "config" / "keybindings.yaml").write_text(
                "bindings:\n  - key: ctrl+k\n    action: palette.open\n",
                encoding="utf-8",
            )
            (root / "config" / "commands.yaml").write_text(
                "commands:\n  - workspace.open\n",
                encoding="utf-8",
            )
            (root / "config" / "themes" / "default.tcss").write_text(
                "Screen { layout: vertical; }\n",
                encoding="utf-8",
            )

            loader = ConfigLoader(start=root)

            self.assertEqual(loader.load_layout_definition()["id"], "default")
            self.assertEqual(loader.load_keybindings()["bindings"][0]["key"], "ctrl+k")
            self.assertEqual(loader.load_command_catalog()["commands"][0], "workspace.open")
            self.assertIn("layout: vertical", loader.load_theme())


if __name__ == "__main__":
    unittest.main()
