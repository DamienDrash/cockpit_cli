from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cockpit.core.dispatch.event_bus import EventBus
from cockpit.core.dispatch.command_dispatcher import CommandDispatcher
from cockpit.workspace.handlers.session_handlers import RestoreSessionHandler
from cockpit.workspace.handlers.workspace_handlers import OpenWorkspaceHandler
from cockpit.core.command import Command
from cockpit.workspace.services.connection_service import ConnectionService
from cockpit.workspace.services.layout_service import LayoutService
from cockpit.workspace.services.navigation_controller import NavigationController
from cockpit.workspace.services.session_service import SessionService
from cockpit.workspace.services.workspace_service import WorkspaceService
from cockpit.workspace.events import (
    LayoutApplied,
    SessionCreated,
    SessionRestored,
    SnapshotSaved,
    WorkspaceOpened,
)
from cockpit.core.events.runtime import StatusMessagePublished
from cockpit.workspace.config_loader import ConfigLoader
from cockpit.workspace.repositories import (
    LayoutRepository,
    SessionRepository,
    SnapshotRepository,
    WorkspaceRepository,
)
from cockpit.core.persistence.sqlite_store import SQLiteStore
from cockpit.core.enums import SnapshotKind, StatusLevel
from cockpit.core.enums import CommandSource


class NavigationControllerTests(unittest.TestCase):
    def test_open_workspace_flow_creates_session_and_layout(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace_dir = self._write_project_fixture(root)
            controller, store, bus, session_repo, _snapshot_repo = (
                self._build_controller(root)
            )

            state = controller.open_workspace(str(workspace_dir))

            self.assertEqual(state.cwd, str(workspace_dir.resolve()))
            self.assertFalse(state.restored)
            self.assertIsNotNone(
                session_repo.get_latest_for_workspace(state.workspace.id)
            )
            published_types = {type(event) for event in bus.published}
            self.assertIn(WorkspaceOpened, published_types)
            self.assertIn(SessionCreated, published_types)
            self.assertIn(LayoutApplied, published_types)
            self.assertIn(SnapshotSaved, published_types)
            store.close()

    def test_restore_session_recovers_from_invalid_cwd(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace_dir = self._write_project_fixture(root)
            controller, store, bus, session_repo, snapshot_repo = (
                self._build_controller(root)
            )

            created = controller.open_workspace(str(workspace_dir))
            bad_ref = snapshot_repo.save(
                session_id=created.session.id,
                snapshot_kind=SnapshotKind.RESUME,
                payload={"cwd": str(root / "missing-dir")},
            )
            created.session.snapshot_ref = bad_ref
            session_repo.save(created.session)
            event_count = len(bus.published)

            restored = controller.restore_session(created.workspace.id)

            self.assertTrue(restored.restored)
            self.assertEqual(restored.cwd, str(workspace_dir.resolve()))
            self.assertIn(
                "Falling back to workspace root", restored.recovery_message or ""
            )
            new_events = bus.published[event_count:]
            self.assertTrue(
                any(isinstance(event, SessionRestored) for event in new_events)
            )
            self.assertTrue(
                any(
                    isinstance(event, StatusMessagePublished)
                    and event.level == StatusLevel.WARNING
                    for event in new_events
                )
            )
            store.close()

    def test_reopen_last_workspace_uses_persisted_resume_snapshot(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace_dir = self._write_project_fixture(root)
            nested_dir = workspace_dir / "nested"
            nested_dir.mkdir()
            selected_file = nested_dir / "notes.txt"
            selected_file.write_text("resume me\n", encoding="utf-8")

            controller, store, _bus, _session_repo, _snapshot_repo = (
                self._build_controller(root)
            )
            created = controller.open_workspace(str(workspace_dir))
            first_service = SessionService(
                SessionRepository(store),
                SnapshotRepository(store),
            )
            first_service.save_resume_snapshot(
                session_id=created.session.id,
                payload={
                    "cwd": str(nested_dir.resolve()),
                    "browser_path": str(nested_dir.resolve()),
                    "selected_path": str(selected_file.resolve()),
                },
                active_tab_id="work",
                focused_panel_id="work-panel",
            )
            store.close()

            (
                reopened_controller,
                reopened_store,
                _bus2,
                _session_repo2,
                _snapshot_repo2,
            ) = self._build_controller(root)
            reopened = reopened_controller.reopen_last_workspace()

            self.assertTrue(reopened.restored)
            self.assertEqual(reopened.cwd, str(nested_dir.resolve()))
            self.assertEqual(
                reopened.snapshot_payload.get("browser_path"),
                str(nested_dir.resolve()),
            )
            self.assertEqual(
                reopened.snapshot_payload.get("selected_path"),
                str(selected_file.resolve()),
            )
            reopened_store.close()

    def test_restore_session_handler_returns_snapshot_paths(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace_dir = self._write_project_fixture(root)
            nested_dir = workspace_dir / "nested"
            nested_dir.mkdir()
            selected_file = nested_dir / "notes.txt"
            selected_file.write_text("handler restore\n", encoding="utf-8")

            controller, store, bus, _session_repo, _snapshot_repo = (
                self._build_controller(root)
            )
            created = controller.open_workspace(str(workspace_dir))
            SessionService(
                SessionRepository(store),
                SnapshotRepository(store),
            ).save_resume_snapshot(
                session_id=created.session.id,
                payload={
                    "cwd": str(nested_dir.resolve()),
                    "browser_path": str(nested_dir.resolve()),
                    "selected_path": str(selected_file.resolve()),
                },
                active_tab_id="work",
                focused_panel_id="work-panel",
            )
            dispatcher = CommandDispatcher(event_bus=bus)
            dispatcher.register(
                "session.restore",
                RestoreSessionHandler(
                    bus,
                    navigation_controller=controller,
                ),
            )

            result = dispatcher.dispatch(
                Command(
                    id="cmd_restore",
                    source=CommandSource.SLASH,
                    name="session.restore",
                    context={"workspace_id": created.workspace.id},
                )
            )

            self.assertTrue(result.success)
            self.assertEqual(result.data["cwd"], str(nested_dir.resolve()))
            self.assertEqual(result.data["browser_path"], str(nested_dir.resolve()))
            self.assertEqual(result.data["selected_path"], str(selected_file.resolve()))
            store.close()

    def test_open_remote_workspace_creates_ssh_target_and_preserves_remote_cwd(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_project_fixture(root)
            controller, store, _bus, session_repo, snapshot_repo = (
                self._build_controller(root)
            )

            remote_uri = "ssh://dev@example.com/srv/app"
            created = controller.open_workspace(remote_uri)
            snapshot_ref = snapshot_repo.save(
                session_id=created.session.id,
                snapshot_kind=SnapshotKind.RESUME,
                payload={"cwd": "/srv/app/current"},
            )
            created.session.snapshot_ref = snapshot_ref
            session_repo.save(created.session)

            restored = controller.restore_session(created.workspace.id)

            self.assertEqual(created.workspace.target.kind.value, "ssh")
            self.assertEqual(created.workspace.target.ref, "dev@example.com")
            self.assertEqual(created.workspace.root_path, "/srv/app")
            self.assertEqual(restored.cwd, "/srv/app/current")
            store.close()

    def test_open_profile_workspace_uses_configured_connection_alias(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_project_fixture(root)
            (root / "config" / "connections.yaml").write_text(
                "\n".join(
                    [
                        "connections:",
                        "  prod:",
                        "    target: deploy@example.com",
                        "    default_path: /srv/platform",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            controller, store, _bus, _session_repo, _snapshot_repo = (
                self._build_controller(root)
            )

            created = controller.open_workspace("@prod")

            self.assertEqual(created.workspace.target.kind.value, "ssh")
            self.assertEqual(created.workspace.target.ref, "deploy@example.com")
            self.assertEqual(created.workspace.root_path, "/srv/platform")
            self.assertEqual(created.cwd, "/srv/platform")
            store.close()

    def test_invalid_workspace_path_returns_recoverable_failure(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._write_project_fixture(root)
            controller, store, bus, _session_repo, _snapshot_repo = (
                self._build_controller(root)
            )
            dispatcher = CommandDispatcher(event_bus=bus)
            dispatcher.register(
                "workspace.open",
                OpenWorkspaceHandler(
                    bus,
                    navigation_controller=controller,
                ),
            )
            dispatcher.register(
                "session.restore",
                RestoreSessionHandler(
                    bus,
                    navigation_controller=controller,
                ),
            )

            result = dispatcher.dispatch(
                Command(
                    id="cmd_invalid",
                    source=CommandSource.SLASH,
                    name="workspace.open",
                    args={"argv": [str(root / "missing-workspace")]},
                )
            )

            self.assertFalse(result.success)
            self.assertIn("does not exist", result.message or "")
            self.assertTrue(
                any(
                    isinstance(event, StatusMessagePublished)
                    and event.level == StatusLevel.ERROR
                    for event in bus.published
                )
            )
            store.close()

    def _build_controller(
        self,
        root: Path,
    ) -> tuple[
        NavigationController,
        SQLiteStore,
        EventBus,
        SessionRepository,
        SnapshotRepository,
    ]:
        bus = EventBus()
        store = SQLiteStore(root / ".cockpit" / "test.db")
        workspace_repo = WorkspaceRepository(store)
        layout_repo = LayoutRepository(store)
        session_repo = SessionRepository(store)
        snapshot_repo = SnapshotRepository(store)
        config_loader = ConfigLoader(start=root)
        controller = NavigationController(
            event_bus=bus,
            workspace_service=WorkspaceService(
                workspace_repo,
                connection_service=ConnectionService(config_loader),
            ),
            layout_service=LayoutService(layout_repo, config_loader),
            session_service=SessionService(session_repo, snapshot_repo),
        )
        return controller, store, bus, session_repo, snapshot_repo

    def _write_project_fixture(self, root: Path) -> Path:
        (root / "src").mkdir()
        (root / "config" / "layouts").mkdir(parents=True)
        (root / "pyproject.toml").write_text(
            "[project]\nname='cockpit'\n",
            encoding="utf-8",
        )
        (root / "config" / "layouts" / "default.yaml").write_text(
            "\n".join(
                [
                    "id: default",
                    "name: Default",
                    "tabs:",
                    "  - id: work",
                    "    name: Work",
                    "    root_split:",
                    "      orientation: vertical",
                    "      ratio: 0.7",
                    "      children:",
                    "        - panel_id: work-panel",
                    "          panel_type: work",
                    "focus_path:",
                    "  - work",
                    "  - work-panel",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        workspace_dir = root / "workspace"
        workspace_dir.mkdir()
        return workspace_dir


if __name__ == "__main__":
    unittest.main()
