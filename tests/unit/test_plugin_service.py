import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import shutil
import textwrap
import types
import unittest

from cockpit.application.dispatch.command_dispatcher import CommandDispatcher
from cockpit.application.dispatch.event_bus import EventBus
from cockpit.application.services.plugin_service import PluginService
from cockpit.domain.commands.command import Command
from cockpit.infrastructure.persistence.repositories import InstalledPluginRepository
from cockpit.infrastructure.persistence.sqlite_store import SQLiteStore
from cockpit.shared.enums import CommandSource
from cockpit.shared.utils import make_id
from cockpit.ui.panels.registry import PanelRegistry

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


def _write_plugin_module(
    package_root: Path,
    module_name: str,
    *,
    manifest_body: str,
    handler_body: str = "",
) -> None:
    handler_source = textwrap.indent(
        textwrap.dedent(handler_body or _default_handler_body(module_name)).strip(),
        " " * 8,
    )
    manifest_source = textwrap.indent(textwrap.dedent(manifest_body).strip(), " " * 4)
    source = "\n".join(
        [
            "from cockpit.application.handlers.base import DispatchResult",
            "from cockpit.domain.models.panel_state import PanelState",
            "from cockpit.domain.models.plugin import PluginManifest",
            "from cockpit.ui.panels.registry import PanelSpec",
            "",
            "class HostedPanel:",
            f"    PANEL_ID = \"{module_name}-panel\"",
            f"    PANEL_TYPE = \"{module_name}\"",
            "",
            "    def __init__(self):",
            "        self._notes = []",
            "        self._workspace_name = \"Plugin\"",
            "",
            "    def initialize(self, context):",
            "        self._workspace_name = str(context.get(\"workspace_name\", \"Plugin\"))",
            "",
            "    def restore_state(self, snapshot):",
            "        notes = snapshot.get(\"notes\")",
            "        if isinstance(notes, list):",
            "            self._notes = [str(item) for item in notes if isinstance(item, str)]",
            "",
            "    def snapshot_state(self):",
            "        return PanelState(",
            "            panel_id=self.PANEL_ID,",
            "            panel_type=self.PANEL_TYPE,",
            "            snapshot={\"notes\": list(self._notes)},",
            "        )",
            "",
            "    def command_context(self):",
            "        return {",
            "            \"panel_id\": self.PANEL_ID,",
            "            \"notes_count\": len(self._notes),",
            "        }",
            "",
            "    def suspend(self):",
            "        pass",
            "",
            "    def resume(self):",
            "        pass",
            "",
            "    def dispose(self):",
            "        pass",
            "",
            "    def apply_command_result(self, payload):",
            "        note = payload.get(\"note\")",
            "        if isinstance(note, str) and note:",
            "            self._notes.append(note)",
            "",
            "    def _render_text(self):",
            "        if not self._notes:",
            "            return f\"{self._workspace_name}\\n\\nNo plugin notes yet.\"",
            "        lines = [self._workspace_name, \"\"]",
            "        lines.extend(f\"- {note}\" for note in self._notes)",
            "        return \"\\n\".join(lines)",
            "",
            "class EchoHandler:",
            "    def __call__(self, command):",
            handler_source,
            "",
            "PLUGIN_MANIFEST = PluginManifest(",
            manifest_source,
            ")",
            "",
            "def register_plugin(context):",
            "    context.register_panel(",
            "        PanelSpec(",
            "            panel_type=HostedPanel.PANEL_TYPE,",
            "            panel_id=HostedPanel.PANEL_ID,",
            f"            display_name=\"{module_name.title()}\",",
            "            factory=lambda _container: HostedPanel(),",
            "        )",
            "    )",
            f"    context.register_command(\"{module_name}.echo\", EchoHandler())",
            "",
        ]
    )
    (package_root / f"{module_name}.py").write_text(source, encoding="utf-8")


def _default_handler_body(module_name: str) -> str:
    return textwrap.dedent(
        f"""
        args = getattr(command, "args", {{}})
        argv = args.get("argv", []) if isinstance(args, dict) else []
        note = " ".join(str(token) for token in argv if isinstance(token, str)).strip() or "{module_name}"
        return DispatchResult(
            success=True,
            message=f"Added {{note}}",
            data={{
                "result_panel_id": "{module_name}-panel",
                "result_payload": {{"note": note}},
            }},
        )
        """
    ).strip()


class PluginServiceTests(unittest.TestCase):
    def test_installs_pins_disables_and_removes_plugin(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_root = root / "plugin-source"
            package_root.mkdir()
            _write_plugin_module(
                package_root,
                "sample_plugin",
                manifest_body="""
                name="Sample Plugin",
                module="sample_plugin",
                version="1.2.3",
                summary="sample",
                commands=["sample_plugin.echo"],
                permissions=["ui.read", "commands.execute"],
                runtime_mode="hosted",
                """,
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
            self.assertEqual(service.enabled_modules(), [])
            self.assertIn("exported_commands", plugin.manifest)

            updated = service.pin_version(plugin.id, "2.0.0")
            self.assertEqual(updated.version_pin, "2.0.0")

            disabled = service.set_enabled(plugin.id, False)
            self.assertFalse(disabled.enabled)

            service.remove_plugin(plugin.id)
            self.assertEqual(service.list_plugins(), [])
            service.shutdown()
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
            service.shutdown()
            store.close()

    @unittest.skipUnless(PACKAGING_AVAILABLE, "packaging must be installed for compat checks")
    def test_rejects_incompatible_plugin_manifest(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_root = root / "plugin-source"
            package_root.mkdir()
            _write_plugin_module(
                package_root,
                "sample_plugin_incompatible",
                manifest_body="""
                name="Sample Plugin",
                module="sample_plugin_incompatible",
                version="1.2.3",
                compat_range="<0.1.0",
                permissions=["ui.read", "commands.execute"],
                runtime_mode="hosted",
                """,
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
            service.shutdown()
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

    def test_runtime_integrity_failure_blocks_host_start(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_root = root / "plugin-source"
            package_root.mkdir()
            _write_plugin_module(
                package_root,
                "sample_plugin_integrity",
                manifest_body="""
                name="Sample Plugin",
                module="sample_plugin_integrity",
                version="1.2.3",
                permissions=["ui.read", "commands.execute"],
                runtime_mode="hosted",
                """,
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
                module_name="sample_plugin_integrity",
            )
            assert plugin.install_path is not None
            Path(plugin.install_path, "sample_plugin_integrity.py").write_text(
                "tampered = True\n",
                encoding="utf-8",
            )

            updated = service.get_plugin(plugin.id)

            self.assertIsNotNone(updated)
            assert updated is not None
            self.assertEqual(updated.status, "integrity_failed")
            self.assertEqual(service.enabled_modules(), [])
            service.shutdown()
            store.close()

    def test_runtime_permission_denial_blocks_plugin_loading(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_root = root / "plugin-source"
            package_root.mkdir()
            _write_plugin_module(
                package_root,
                "sample_plugin_permissions",
                manifest_body="""
                name="Sample Plugin",
                module="sample_plugin_permissions",
                version="1.2.3",
                permissions=["ui.read", "commands.execute", "shell.execute"],
                runtime_mode="hosted",
                """,
            )
            store = SQLiteStore(root / "cockpit.db")
            repo = InstalledPluginRepository(store)
            service = PluginService(
                repo,
                start=root,
                pip_runner=FakePipRunner(package_root),
                allowed_permissions=("ui.read",),
            )

            plugin = service.install_plugin(
                requirement=str(package_root),
                module_name="sample_plugin_permissions",
            )

            updated = service.get_plugin(plugin.id)
            self.assertIsNotNone(updated)
            assert updated is not None
            self.assertEqual(updated.status, "permission_denied")
            self.assertEqual(service.diagnostics()["permission_denied"], 1)
            service.shutdown()
            store.close()

    def test_registers_managed_plugin_proxies_and_dispatches_through_host(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_root = root / "plugin-source"
            package_root.mkdir()
            _write_plugin_module(
                package_root,
                "hosted_plugin",
                manifest_body="""
                name="Hosted Plugin",
                module="hosted_plugin",
                version="1.0.0",
                permissions=["ui.read", "commands.execute"],
                runtime_mode="hosted",
                """,
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
                module_name="hosted_plugin",
            )
            registry = PanelRegistry()
            dispatcher = CommandDispatcher(event_bus=EventBus())
            catalog: list[str] = []

            service.register_managed_plugins(
                panel_registry=registry,
                command_dispatcher=dispatcher,
                command_catalog=catalog,
            )

            self.assertIn("hosted_plugin.echo", catalog)
            self.assertIsNotNone(registry.spec_for_panel_id("hosted_plugin-panel"))

            panel = registry.create_panels(container=object())["hosted_plugin-panel"]
            panel.initialize({"workspace_name": "Hosted"})
            result = dispatcher.dispatch(
                Command(
                    id=make_id("cmd"),
                    source=CommandSource.PALETTE,
                    name="hosted_plugin.echo",
                    args={"argv": ["hello", "world"]},
                )
            )
            self.assertTrue(result.success)
            panel.apply_command_result(result.data["result_payload"])
            state = panel.snapshot_state()
            self.assertEqual(state.snapshot["notes"], ["hello world"])
            self.assertEqual(service.get_plugin(plugin.id).status, "host_running")
            service.shutdown()
            store.close()

    def test_plugin_host_crash_isolated_from_core_and_can_restart(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_root = root / "plugin-source"
            package_root.mkdir()
            _write_plugin_module(
                package_root,
                "crashy_plugin",
                manifest_body="""
                name="Crashy Plugin",
                module="crashy_plugin",
                version="1.0.0",
                permissions=["ui.read", "commands.execute"],
                runtime_mode="hosted",
                """,
                handler_body="""
                import os
                args = getattr(command, "args", {})
                argv = args.get("argv", []) if isinstance(args, dict) else []
                if argv and argv[0] == "crash":
                    os._exit(17)
                note = " ".join(str(token) for token in argv if isinstance(token, str)).strip() or "ok"
                return DispatchResult(
                    success=True,
                    message=note,
                    data={
                        "result_panel_id": "crashy_plugin-panel",
                        "result_payload": {"note": note},
                    },
                )
                """,
            )
            store = SQLiteStore(root / "cockpit.db")
            repo = InstalledPluginRepository(store)
            service = PluginService(
                repo,
                start=root,
                pip_runner=FakePipRunner(package_root),
            )
            service.install_plugin(
                requirement=str(package_root),
                module_name="crashy_plugin",
            )
            dispatcher = CommandDispatcher(event_bus=EventBus())
            registry = PanelRegistry()
            catalog: list[str] = []
            service.register_managed_plugins(
                panel_registry=registry,
                command_dispatcher=dispatcher,
                command_catalog=catalog,
            )

            crash_result = dispatcher.dispatch(
                Command(
                    id=make_id("cmd"),
                    source=CommandSource.PALETTE,
                    name="crashy_plugin.echo",
                    args={"argv": ["crash"]},
                )
            )
            self.assertFalse(crash_result.success)
            self.assertIn("Plugin host error", crash_result.message or "")

            recovery = dispatcher.dispatch(
                Command(
                    id=make_id("cmd"),
                    source=CommandSource.PALETTE,
                    name="crashy_plugin.echo",
                    args={"argv": ["recovered"]},
                )
            )
            self.assertTrue(recovery.success)
            self.assertEqual(recovery.data["result_payload"]["note"], "recovered")
            service.shutdown()
            store.close()


if __name__ == "__main__":
    unittest.main()
