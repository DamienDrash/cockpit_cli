import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import shutil
import sys
import textwrap
import types
import unittest

from cockpit.application.services.plugin_service import PluginService
from cockpit.infrastructure.persistence.repositories import InstalledPluginRepository
from cockpit.infrastructure.persistence.sqlite_store import SQLiteStore

PACKAGING_AVAILABLE = importlib.util.find_spec("packaging") is not None


class FakePipRunner:
    def __init__(self, source_root: Path) -> None:
        self._source_root = source_root
        self.calls: list[list[str]] = []

    def __call__(
        self,
        argv: list[str],
        *,
        check: bool = False,
        capture_output: bool = True,
        text: bool = True,
    ) -> types.SimpleNamespace:
        del check, capture_output, text
        self.calls.append(list(argv))
        target = Path(argv[argv.index("--target") + 1])
        target.mkdir(parents=True, exist_ok=True)
        for path in self._source_root.iterdir():
            destination = target / path.name
            if path.is_dir():
                shutil.copytree(path, destination, dirs_exist_ok=True)
            else:
                shutil.copy2(path, destination)
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")


class PluginServiceTests(unittest.TestCase):
    def test_installs_pins_disables_and_removes_plugin(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_root = root / "plugin-source"
            package_root.mkdir()
            (package_root / "sample_plugin.py").write_text(
                textwrap.dedent(
                    """
                    from cockpit.domain.models.plugin import PluginManifest

                    PLUGIN_MANIFEST = PluginManifest(
                        name="Sample Plugin",
                        module="sample_plugin",
                        version="1.2.3",
                        summary="sample",
                        commands=["sample.echo"],
                    )
                    """
                ),
                encoding="utf-8",
            )
            store = SQLiteStore(root / "cockpit.db")
            repo = InstalledPluginRepository(store)
            service = PluginService(
                repo,
                start=root,
                pip_runner=FakePipRunner(package_root),
            )

            plugin = service.install_plugin(
                requirement=str(package_root),
                module_name="sample_plugin",
                version_pin="1.2.3",
                source="local-test",
            )

            self.assertEqual(plugin.name, "Sample Plugin")
            self.assertEqual(plugin.version_pin, "1.2.3")
            self.assertIn("sample_plugin", service.enabled_modules())

            updated = service.pin_version(plugin.id, "2.0.0")
            self.assertEqual(updated.version_pin, "2.0.0")

            disabled = service.set_enabled(plugin.id, False)
            self.assertFalse(disabled.enabled)

            service.remove_plugin(plugin.id)
            self.assertEqual(service.list_plugins(), [])
            store.close()

    def test_rejects_untrusted_git_plugin_source(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = SQLiteStore(root / "cockpit.db")
            repo = InstalledPluginRepository(store)
            service = PluginService(
                repo,
                start=root,
                trusted_sources=("git+https://github.com/trusted-org/",),
            )

            with self.assertRaisesRegex(ValueError, "not trusted"):
                service.install_plugin(
                    requirement="git+https://github.com/evil-org/plugin.git",
                    module_name="evil_plugin",
                    source="https://github.com/evil-org/plugin",
                )
            store.close()

    @unittest.skipUnless(PACKAGING_AVAILABLE, "packaging must be installed for compat checks")
    def test_rejects_incompatible_plugin_manifest(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_root = root / "plugin-source"
            package_root.mkdir()
            (package_root / "sample_plugin_incompatible.py").write_text(
                textwrap.dedent(
                    """
                    from cockpit.domain.models.plugin import PluginManifest

                    PLUGIN_MANIFEST = PluginManifest(
                        name="Sample Plugin",
                        module="sample_plugin_incompatible",
                        version="1.2.3",
                        compat_range="<0.1.0",
                    )
                    """
                ),
                encoding="utf-8",
            )
            store = SQLiteStore(root / "cockpit.db")
            repo = InstalledPluginRepository(store)
            service = PluginService(
                repo,
                start=root,
                pip_runner=FakePipRunner(package_root),
                app_version="1.0.0",
            )

            with self.assertRaisesRegex(RuntimeError, "incompatible"):
                service.install_plugin(
                    requirement=str(package_root),
                    module_name="sample_plugin_incompatible",
                )
            store.close()

    def test_appends_version_pin_to_git_requirements(self) -> None:
        install_spec = PluginService._install_spec(
            "git+https://github.com/example/plugin.git",
            "1.2.3",
        )

        self.assertEqual(
            install_spec,
            "git+https://github.com/example/plugin.git@1.2.3",
        )
