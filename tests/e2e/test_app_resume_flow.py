import importlib.util
import os
from pathlib import Path
from shutil import which
from subprocess import run
from tempfile import TemporaryDirectory
import unittest

TEXTUAL_AVAILABLE = importlib.util.find_spec("textual") is not None

if TEXTUAL_AVAILABLE:
    from cockpit.bootstrap import build_container
    from cockpit.infrastructure.cron.cron_adapter import (
        CronAdapter,
        CronJob,
        CronSnapshot,
    )
    from cockpit.datasources.adapters.database_adapter import (
        DatabaseCatalogSnapshot,
        DatabaseQueryResult,
    )
    from cockpit.infrastructure.docker.docker_adapter import (
        DockerActionResult,
        DockerContainerSummary,
        DockerRuntimeSnapshot,
    )
    from cockpit.infrastructure.http.http_adapter import HttpResponseSummary
    from cockpit.infrastructure.shell.local_shell_adapter import (
        LocalShellAdapter,
    )
    from cockpit.infrastructure.shell.base import ShellLaunchConfig
    from cockpit.datasources.adapters.ssh_command_runner import SSHCommandResult
    from cockpit.core.enums import SessionTargetKind
    from cockpit.ui.panels.curl_panel import CurlPanel
    from cockpit.ui.panels.db_panel import DBPanel
    from cockpit.ui.panels.docker_panel import DockerPanel
    from cockpit.ui.panels.git_panel import GitPanel
    from cockpit.ui.panels.logs_panel import LogsPanel
    from cockpit.ui.panels.cron_panel import CronPanel
    from cockpit.ui.screens.app_shell import CockpitApp
    from cockpit.ui.widgets.confirmation_bar import ConfirmationBar
    from cockpit.ui.widgets.command_palette import CommandPalette
    from cockpit.ui.widgets.embedded_terminal import EmbeddedTerminal
    from cockpit.ui.widgets.file_context import FileContext
    from cockpit.ui.widgets.file_explorer import FileExplorer
    from cockpit.ui.widgets.slash_input import SlashInput
    from cockpit.ui.widgets.tab_bar import TabBar

    class StaticShellAdapter(LocalShellAdapter):
        def build_launch_config(
            self,
            cwd: str,
            *,
            command: list[str] | tuple[str, ...] | None = None,
            target_kind: SessionTargetKind = SessionTargetKind.LOCAL,
            target_ref: str | None = None,
        ) -> "ShellLaunchConfig":
            if command is not None:
                return super().build_launch_config(
                    cwd,
                    command=command,
                    target_kind=target_kind,
                    target_ref=target_ref,
                )
            if target_kind is SessionTargetKind.SSH:
                env = os.environ.copy()
                env.setdefault("TERM", "xterm-256color")
                env.setdefault("COLORTERM", "truecolor")
                return ShellLaunchConfig(
                    command=("/bin/sh", "-lc", "printf 'remote ready\\n'; sleep 30"),
                    cwd=str(Path.cwd()),
                    env=env,
                )

            path = Path(cwd).expanduser().resolve()
            if not path.exists():
                raise FileNotFoundError(f"Shell cwd '{path}' does not exist.")
            if not path.is_dir():
                raise NotADirectoryError(f"Shell cwd '{path}' is not a directory.")

            env = os.environ.copy()
            env.setdefault("TERM", "xterm-256color")
            env.setdefault("COLORTERM", "truecolor")
            env.setdefault("PS1", "cockpit$ ")
            return ShellLaunchConfig(
                command=("/bin/sh", "-lc", "printf 'ready\\n'; sleep 30"),
                cwd=str(path),
                env=env,
            )

    class FakeSSHCommandRunner:
        def run(
            self,
            target_ref: str,
            command: str,
            *,
            timeout_seconds: int = 5,
        ) -> SSHCommandResult:
            del timeout_seconds
            if "pwd" in command and "ls -1Ap" in command:
                browser_path = (
                    "/srv/app/current" if "/srv/app/current" in command else "/srv/app"
                )
                listing = "current/\nREADME.md\nsrc/\n"
                if browser_path == "/srv/app/current":
                    listing = "api/\nrelease.txt\n"
                return SSHCommandResult(
                    target_ref=target_ref,
                    command=command,
                    returncode=0,
                    stdout=f"{browser_path}\n__COCKPIT_REMOTE_LISTING__\n{listing}",
                    stderr="",
                )
            if "git -C" in command:
                return SSHCommandResult(
                    target_ref=target_ref,
                    command=command,
                    returncode=1,
                    stdout="",
                    stderr="not a git repository",
                )
            if "docker ps" in command:
                return SSHCommandResult(
                    target_ref=target_ref,
                    command=command,
                    returncode=1,
                    stdout="",
                    stderr="Cannot connect to the Docker daemon",
                )
            return SSHCommandResult(
                target_ref=target_ref,
                command=command,
                returncode=1,
                stdout="",
                stderr="unsupported test command",
            )

    class FakeCronAdapter(CronAdapter):
        def list_jobs(
            self,
            *,
            target_kind: SessionTargetKind = SessionTargetKind.LOCAL,
            target_ref: str | None = None,
        ) -> CronSnapshot:
            target_label = target_ref or target_kind.value
            return CronSnapshot(
                jobs=[
                    CronJob(
                        schedule="0 2 * * *",
                        command="/usr/local/bin/backup",
                        enabled=True,
                        comment=f"target={target_label}",
                    ),
                    CronJob(
                        schedule="@daily",
                        command="/usr/local/bin/cleanup",
                        enabled=False,
                    ),
                ],
                is_available=True,
                message=None,
            )

    class FakeDockerAdapter:
        def __init__(self) -> None:
            self._restart_counts: dict[str, int] = {}

        def list_containers(
            self,
            *,
            target_kind: SessionTargetKind = SessionTargetKind.LOCAL,
            target_ref: str | None = None,
        ) -> DockerRuntimeSnapshot:
            del target_kind, target_ref
            web_restarts = self._restart_counts.get("abc123", 0)
            web_status = (
                "Up 10 minutes" if web_restarts == 0 else "Up 0 seconds (restarted)"
            )
            return DockerRuntimeSnapshot(
                containers=[
                    DockerContainerSummary(
                        container_id="abc123",
                        name="web",
                        image="nginx:latest",
                        state="running",
                        status=web_status,
                        ports="80/tcp",
                    ),
                    DockerContainerSummary(
                        container_id="def456",
                        name="db",
                        image="postgres:16",
                        state="running",
                        status="Up 2 hours",
                        ports="5432/tcp",
                    ),
                ],
                is_available=True,
                daemon_reachable=True,
                message=None,
            )

        def restart_container(
            self,
            container_id: str,
            *,
            target_kind: SessionTargetKind = SessionTargetKind.LOCAL,
            target_ref: str | None = None,
        ) -> DockerActionResult:
            del target_kind, target_ref
            self._restart_counts[container_id] = (
                self._restart_counts.get(container_id, 0) + 1
            )
            return DockerActionResult(success=True, message=f"restarted {container_id}")

    class FakeDatabaseAdapter:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def list_databases(
            self,
            root_path: str,
            *,
            target_kind: SessionTargetKind = SessionTargetKind.LOCAL,
            target_ref: str | None = None,
        ) -> DatabaseCatalogSnapshot:
            del target_kind, target_ref
            database_path = str(Path(root_path).resolve() / "workspace.sqlite3")
            return DatabaseCatalogSnapshot(
                databases=[database_path],
                is_available=True,
                message=None,
            )

        def run_query(
            self,
            database_path: str,
            query: str,
            *,
            target_kind: SessionTargetKind = SessionTargetKind.LOCAL,
            target_ref: str | None = None,
            row_limit: int = 50,
        ) -> DatabaseQueryResult:
            del target_kind, target_ref, row_limit
            self.calls.append(query)
            lowered = query.lower()
            if lowered.startswith(
                ("insert", "update", "delete", "create", "alter", "drop")
            ):
                return DatabaseQueryResult(
                    success=True,
                    database_path=database_path,
                    query=query,
                    affected_rows=1,
                    message="Affected 1 row.",
                )
            return DatabaseQueryResult(
                success=True,
                database_path=database_path,
                query=query,
                columns=["name"],
                rows=[["users"], ["jobs"]],
                row_count=2,
                message="Returned 2 rows.",
            )

    class FakeHttpAdapter:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, str | None]] = []

        def send_request(
            self,
            method: str,
            url: str,
            *,
            headers: dict[str, str] | None = None,
            body: str | None = None,
            timeout_seconds: int = 10,
        ) -> HttpResponseSummary:
            del headers, timeout_seconds
            self.calls.append((method, url, body))
            return HttpResponseSummary(
                success=True,
                method=method,
                url=url,
                status_code=200,
                reason="OK",
                duration_ms=17,
                headers={"content-type": "application/json"},
                body_preview='{"ok": true, "url": "' + url + '"}',
                message=f"{method} {url} -> 200",
            )


@unittest.skipUnless(TEXTUAL_AVAILABLE, "textual must be installed for e2e tests")
class CockpitAppE2ETests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_open_command_loads_workspace_without_manual_input(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            root, workspace_dir, _nested_dir, _selected_file = (
                self._write_project_fixture(Path(temp_dir))
            )
            app = self._build_app(
                root,
                startup_command_text=f"workspace open {workspace_dir}",
            )

            async with app.run_test() as pilot:
                await pilot.pause()

                tab_text = self._rendered_text(app.query_one(TabBar))
                context_text = self._rendered_text(app.query_one(FileContext))

                self.assertIn("Workspace: workspace", tab_text)
                self.assertIn(f"Root: {workspace_dir.resolve()}", context_text)

    async def test_open_workspace_renders_work_panel(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root, workspace_dir, nested_dir, _selected_file = (
                self._write_project_fixture(Path(temp_dir))
            )
            app = self._build_app(root)

            async with app.run_test() as pilot:
                await self._open_workspace(app, pilot, workspace_dir)

                tab_text = self._rendered_text(app.query_one(TabBar))
                context_text = self._rendered_text(app.query_one(FileContext))
                explorer_text = self._rendered_text(app.query_one(FileExplorer))

                self.assertIn("Workspace: workspace", tab_text)
                self.assertIn(f"Root: {workspace_dir.resolve()}", context_text)
                self.assertIn(f"Selected: {nested_dir.resolve()}", context_text)
                self.assertIn(f"Explorer: {workspace_dir.resolve()}", explorer_text)
                self.assertIn("> nested/", explorer_text)

    async def test_restart_restores_workspace_and_explorer_selection(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root, workspace_dir, nested_dir, selected_file = (
                self._write_project_fixture(Path(temp_dir))
            )

            first_app = self._build_app(root)
            async with first_app.run_test() as pilot:
                await self._open_workspace(first_app, pilot, workspace_dir)
                await pilot.press("enter")
                await pilot.pause()

                context_text = self._rendered_text(first_app.query_one(FileContext))
                explorer_text = self._rendered_text(first_app.query_one(FileExplorer))
                self.assertIn(f"Selected: {selected_file.resolve()}", context_text)
                self.assertIn(f"Explorer: {nested_dir.resolve()}", explorer_text)
                self.assertIn("> target.txt", explorer_text)

            second_app = self._build_app(root)
            async with second_app.run_test() as pilot:
                await pilot.pause()

                tab_text = self._rendered_text(second_app.query_one(TabBar))
                context_text = self._rendered_text(second_app.query_one(FileContext))
                explorer_text = self._rendered_text(second_app.query_one(FileExplorer))

                self.assertIn("Session: restored", tab_text)
                self.assertIn("Workspace: workspace", context_text)
                self.assertIn(f"Selected: {selected_file.resolve()}", context_text)
                self.assertIn(f"Explorer: {nested_dir.resolve()}", explorer_text)
                self.assertIn("> target.txt", explorer_text)

    async def test_command_palette_dispatches_workspace_open(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root, _workspace_dir, _nested_dir, _selected_file = (
                self._write_project_fixture(Path(temp_dir))
            )
            app = self._build_app(root)

            async with app.run_test() as pilot:
                app.action_toggle_palette()
                await pilot.pause()

                palette = app.query_one(CommandPalette)
                self.assertTrue(palette.is_open)

                palette_input = app.query_one("#command-palette-input")
                palette_input.value = "open"
                await pilot.press("enter")
                await pilot.pause()

                tab_text = self._rendered_text(app.query_one(TabBar))
                context_text = self._rendered_text(app.query_one(FileContext))

                self.assertIn(f"Workspace: {root.name}", tab_text)
                self.assertIn(f"Root: {root.resolve()}", context_text)

    @unittest.skipUnless(which("git"), "git must be installed for git panel e2e")
    async def test_git_tab_displays_repository_status_and_restores_active_tab(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            root, workspace_dir, _nested_dir, _selected_file = (
                self._write_project_fixture(Path(temp_dir))
            )
            self._init_git_repo(workspace_dir)
            tracked = workspace_dir / "tracked.txt"
            tracked.write_text("changed\n", encoding="utf-8")

            first_app = self._build_app(root)
            async with first_app.run_test() as pilot:
                await self._open_workspace(first_app, pilot, workspace_dir)
                await self._run_slash_command(first_app, pilot, "/tab focus git")

                tab_text = self._rendered_text(first_app.query_one(TabBar))
                git_text = self._rendered_text(first_app.query_one(GitPanel))

                self.assertIn("[Git]", tab_text)
                self.assertIn("tracked.txt", git_text)
                self.assertIn("Branch:", git_text)

            second_app = self._build_app(root)
            async with second_app.run_test() as pilot:
                await pilot.pause()

                tab_text = self._rendered_text(second_app.query_one(TabBar))
                git_text = self._rendered_text(second_app.query_one(GitPanel))

                self.assertIn("[Git]", tab_text)
                self.assertIn("tracked.txt", git_text)

    async def test_logs_tab_displays_recent_activity_and_restores_active_tab(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            root, workspace_dir, _nested_dir, _selected_file = (
                self._write_project_fixture(Path(temp_dir))
            )

            first_app = self._build_app(root)
            async with first_app.run_test() as pilot:
                await self._open_workspace(first_app, pilot, workspace_dir)
                await self._run_slash_command(first_app, pilot, "/tab focus logs")

                tab_text = self._rendered_text(first_app.query_one(TabBar))
                logs_text = self._rendered_text(first_app.query_one(LogsPanel))

                self.assertIn("[Logs]", tab_text)
                self.assertIn("workspace.opened", logs_text)
                self.assertIn("layout.applied", logs_text)

            second_app = self._build_app(root)
            async with second_app.run_test() as pilot:
                await pilot.pause()

                tab_text = self._rendered_text(second_app.query_one(TabBar))
                logs_text = self._rendered_text(second_app.query_one(LogsPanel))

                self.assertIn("[Logs]", tab_text)
                self.assertIn("session.restored", logs_text)

    async def test_docker_tab_displays_runtime_state_and_restores_active_tab(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            root, workspace_dir, _nested_dir, _selected_file = (
                self._write_project_fixture(Path(temp_dir))
            )

            first_app = self._build_app(root)
            async with first_app.run_test() as pilot:
                await self._open_workspace(first_app, pilot, workspace_dir)
                await self._run_slash_command(first_app, pilot, "/tab focus docker")

                tab_text = self._rendered_text(first_app.query_one(TabBar))
                docker_text = self._rendered_text(first_app.query_one(DockerPanel))

                self.assertIn("[Docker]", tab_text)
                self.assertIn("Containers:", docker_text)

            second_app = self._build_app(root)
            async with second_app.run_test() as pilot:
                await pilot.pause()

                tab_text = self._rendered_text(second_app.query_one(TabBar))
                docker_text = self._rendered_text(second_app.query_one(DockerPanel))

                self.assertIn("[Docker]", tab_text)
                self.assertIn("Containers:", docker_text)

    async def test_docker_restart_requires_confirmation_and_refreshes_panel(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            root, workspace_dir, _nested_dir, _selected_file = (
                self._write_project_fixture(Path(temp_dir))
            )

            app = self._build_app(root)
            async with app.run_test() as pilot:
                await self._open_workspace(app, pilot, workspace_dir)
                await self._run_slash_command(app, pilot, "/tab focus docker")

                before_text = self._rendered_text(app.query_one(DockerPanel))
                self.assertIn("status=Up 10 minutes", before_text)

                await pilot.press("f8")
                await pilot.pause()

                confirmation_bar = app.query_one(ConfirmationBar)
                self.assertTrue(confirmation_bar.is_open)
                self.assertIn(
                    "Restart container web?", self._rendered_text(confirmation_bar)
                )

                await pilot.press("enter")
                await pilot.pause()

                after_text = self._rendered_text(app.query_one(DockerPanel))
                self.assertFalse(confirmation_bar.is_open)
                self.assertIn("status=Up 0 seconds (restarted)", after_text)

    async def test_cron_tab_displays_jobs_and_restores_active_tab(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root, workspace_dir, _nested_dir, _selected_file = (
                self._write_project_fixture(Path(temp_dir))
            )

            first_app = self._build_app(root)
            async with first_app.run_test() as pilot:
                await self._open_workspace(first_app, pilot, workspace_dir)
                await self._run_slash_command(first_app, pilot, "/tab focus cron")

                tab_text = self._rendered_text(first_app.query_one(TabBar))
                cron_text = self._rendered_text(first_app.query_one(CronPanel))

                self.assertIn("[Cron]", tab_text)
                self.assertIn("/usr/local/bin/backup", cron_text)

            second_app = self._build_app(root)
            async with second_app.run_test() as pilot:
                await pilot.pause()

                tab_text = self._rendered_text(second_app.query_one(TabBar))
                cron_text = self._rendered_text(second_app.query_one(CronPanel))

                self.assertIn("[Cron]", tab_text)
                self.assertIn("/usr/local/bin/backup", cron_text)

    async def test_db_tab_runs_query_and_restores_active_tab(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root, workspace_dir, _nested_dir, _selected_file = (
                self._write_project_fixture(Path(temp_dir))
            )

            first_app = self._build_app(root)
            async with first_app.run_test() as pilot:
                await self._open_workspace(first_app, pilot, workspace_dir)
                await self._run_slash_command(first_app, pilot, "/tab focus db")
                await self._run_slash_command(
                    first_app,
                    pilot,
                    '/db run_query "SELECT name FROM sqlite_master ORDER BY name LIMIT 10"',
                )

                tab_text = self._rendered_text(first_app.query_one(TabBar))
                db_text = self._rendered_text(first_app.query_one(DBPanel))

                self.assertIn("[DB]", tab_text)
                self.assertIn("columns=name", db_text)
                self.assertIn("users", db_text)

            second_app = self._build_app(root)
            async with second_app.run_test() as pilot:
                await pilot.pause()

                tab_text = self._rendered_text(second_app.query_one(TabBar))
                db_text = self._rendered_text(second_app.query_one(DBPanel))

                self.assertIn("[DB]", tab_text)
                self.assertIn("users", db_text)

    async def test_db_write_query_requires_confirmation(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root, workspace_dir, _nested_dir, _selected_file = (
                self._write_project_fixture(Path(temp_dir))
            )

            app = self._build_app(root)
            async with app.run_test() as pilot:
                await self._open_workspace(app, pilot, workspace_dir)
                await self._run_slash_command(app, pilot, "/tab focus db")

                slash_input = app.query_one(SlashInput)
                slash_input.focus()
                slash_input.value = '/db run_query "UPDATE users SET active = 0"'
                await pilot.press("enter")
                await pilot.pause()

                confirmation_bar = app.query_one(ConfirmationBar)
                self.assertTrue(confirmation_bar.is_open)
                self.assertIn("mutating SQL", self._rendered_text(confirmation_bar))

                await pilot.press("enter")
                await pilot.pause()

                db_text = self._rendered_text(app.query_one(DBPanel))
                self.assertFalse(confirmation_bar.is_open)
                self.assertIn("affected_rows=1", db_text)

    async def test_curl_tab_sends_request_and_requires_confirmation_for_post(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            root, workspace_dir, _nested_dir, _selected_file = (
                self._write_project_fixture(Path(temp_dir))
            )

            app = self._build_app(root)
            async with app.run_test() as pilot:
                await self._open_workspace(app, pilot, workspace_dir)
                await self._run_slash_command(app, pilot, "/tab focus curl")
                await self._run_slash_command(
                    app,
                    pilot,
                    "/curl send GET https://example.com/health",
                )

                curl_text = self._rendered_text(app.query_one(CurlPanel))
                self.assertIn("status=200", curl_text)
                self.assertIn('"ok": true', curl_text)

                slash_input = app.query_one(SlashInput)
                slash_input.focus()
                slash_input.value = (
                    '/curl send POST https://example.com/api body="{\\"ok\\":true}"'
                )
                await pilot.press("enter")
                await pilot.pause()

                confirmation_bar = app.query_one(ConfirmationBar)
                self.assertTrue(confirmation_bar.is_open)
                self.assertIn(
                    "Send POST request", self._rendered_text(confirmation_bar)
                )

                await pilot.press("enter")
                await pilot.pause()

                curl_text = self._rendered_text(app.query_one(CurlPanel))
                self.assertFalse(confirmation_bar.is_open)
                self.assertIn("POST 200 https://example.com/api", curl_text)

    async def test_remote_workspace_opens_with_remote_context_and_restores(
        self,
    ) -> None:
        with TemporaryDirectory() as temp_dir:
            root, _workspace_dir, _nested_dir, _selected_file = (
                self._write_project_fixture(Path(temp_dir))
            )
            remote_uri = "ssh://dev@example.com/srv/app"

            first_app = self._build_app(root)
            async with first_app.run_test() as pilot:
                await self._run_slash_command(
                    first_app, pilot, f"/workspace open {remote_uri}"
                )

                context_text = self._rendered_text(first_app.query_one(FileContext))
                explorer_text = self._rendered_text(first_app.query_one(FileExplorer))
                terminal_output = first_app.query_one(EmbeddedTerminal).current_output()

                self.assertIn("Root: /srv/app", context_text)
                self.assertIn("Target: ssh:dev@example.com", context_text)
                self.assertIn(
                    "Explorer: remote dev@example.com:/srv/app", explorer_text
                )
                self.assertIn("> current/", explorer_text)
                self.assertIn("remote ready", terminal_output)
                await pilot.press("enter")
                await pilot.pause()

                context_text = self._rendered_text(first_app.query_one(FileContext))
                explorer_text = self._rendered_text(first_app.query_one(FileExplorer))

                self.assertIn("Selected: /srv/app/current/api", context_text)
                self.assertIn(
                    "Explorer: remote dev@example.com:/srv/app/current", explorer_text
                )
                self.assertIn("> api/", explorer_text)

            second_app = self._build_app(root)
            async with second_app.run_test() as pilot:
                await pilot.pause()

                context_text = self._rendered_text(second_app.query_one(FileContext))
                explorer_text = self._rendered_text(second_app.query_one(FileExplorer))

                self.assertIn("Root: /srv/app", context_text)
                self.assertIn("Target: ssh:dev@example.com", context_text)
                self.assertIn(
                    "Explorer: remote dev@example.com:/srv/app/current", explorer_text
                )
                self.assertIn("Selected: /srv/app/current/api", context_text)
                self.assertIn("> api/", explorer_text)

    async def test_apply_default_layout_resets_focus_to_first_tab(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root, workspace_dir, _nested_dir, _selected_file = (
                self._write_project_fixture(Path(temp_dir))
            )

            app = self._build_app(root)
            async with app.run_test() as pilot:
                await self._open_workspace(app, pilot, workspace_dir)
                await self._run_slash_command(app, pilot, "/tab focus logs")
                await self._run_slash_command(app, pilot, "/layout apply_default")

                tab_text = self._rendered_text(app.query_one(TabBar))

                self.assertIn("[Work]", tab_text)

    async def test_split_layout_displays_multiple_panels_in_the_same_tab(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root, workspace_dir, _nested_dir, _selected_file = (
                self._write_project_fixture(
                    Path(temp_dir),
                    split_layout=True,
                )
            )

            app = self._build_app(root)
            async with app.run_test() as pilot:
                await self._open_workspace(app, pilot, workspace_dir)
                await pilot.pause()

                self.assertTrue(app.query_one(FileContext).display)
                self.assertTrue(app.query_one(DBPanel).display)

    def _build_app(
        self,
        root: Path,
        *,
        startup_command_text: str | None = None,
    ) -> "CockpitApp":
        container = build_container(
            start=root,
            shell_adapter=StaticShellAdapter(shell="/bin/sh"),
            ssh_command_runner=FakeSSHCommandRunner(),
            cron_adapter=FakeCronAdapter(),
            docker_adapter=FakeDockerAdapter(),
            database_adapter=FakeDatabaseAdapter(),
            http_adapter=FakeHttpAdapter(),
        )
        return CockpitApp(
            container=container,
            startup_command_text=startup_command_text,
        )

    async def _open_workspace(
        self,
        app: "CockpitApp",
        pilot: object,
        workspace_dir: Path,
    ) -> None:
        slash_input = app.query_one(SlashInput)
        slash_input.focus()
        slash_input.value = f"/workspace open {workspace_dir}"
        await getattr(pilot, "press")("enter")
        await getattr(pilot, "pause")()

    async def _run_slash_command(
        self, app: "CockpitApp", pilot: object, command: str
    ) -> None:
        slash_input = app.query_one(SlashInput)
        slash_input.focus()
        slash_input.value = command
        await getattr(pilot, "press")("enter")
        await getattr(pilot, "pause")()

    def _write_project_fixture(
        self,
        root: Path,
        *,
        split_layout: bool = False,
    ) -> tuple[Path, Path, Path, Path]:
        (root / "src").mkdir()
        (root / "config" / "layouts").mkdir(parents=True)
        (root / "config" / "themes").mkdir(parents=True)
        (root / "pyproject.toml").write_text(
            "[project]\nname='cockpit-e2e'\n",
            encoding="utf-8",
        )
        layout_lines = [
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
        ]
        if split_layout:
            layout_lines.extend(
                [
                    "        - panel_id: db-panel",
                    "          panel_type: db",
                    "  - id: docker",
                    "    name: Docker",
                    "    root_split:",
                    "      orientation: vertical",
                    "      ratio: 1.0",
                    "      children:",
                    "        - panel_id: docker-panel",
                    "          panel_type: docker",
                ]
            )
        else:
            layout_lines.extend(
                [
                    "  - id: git",
                    "    name: Git",
                    "    root_split:",
                    "      orientation: vertical",
                    "      ratio: 1.0",
                    "      children:",
                    "        - panel_id: git-panel",
                    "          panel_type: git",
                    "  - id: docker",
                    "    name: Docker",
                    "    root_split:",
                    "      orientation: vertical",
                    "      ratio: 1.0",
                    "      children:",
                    "        - panel_id: docker-panel",
                    "          panel_type: docker",
                    "  - id: cron",
                    "    name: Cron",
                    "    root_split:",
                    "      orientation: vertical",
                    "      ratio: 1.0",
                    "      children:",
                    "        - panel_id: cron-panel",
                    "          panel_type: cron",
                    "  - id: db",
                    "    name: DB",
                    "    root_split:",
                    "      orientation: vertical",
                    "      ratio: 1.0",
                    "      children:",
                    "        - panel_id: db-panel",
                    "          panel_type: db",
                    "  - id: curl",
                    "    name: Curl",
                    "    root_split:",
                    "      orientation: vertical",
                    "      ratio: 1.0",
                    "      children:",
                    "        - panel_id: curl-panel",
                    "          panel_type: curl",
                    "  - id: logs",
                    "    name: Logs",
                    "    root_split:",
                    "      orientation: vertical",
                    "      ratio: 1.0",
                    "      children:",
                    "        - panel_id: logs-panel",
                    "          panel_type: logs",
                ]
            )
        layout_lines.extend(
            [
                "focus_path:",
                "  - work",
                "  - work-panel",
            ]
        )
        (root / "config" / "layouts" / "default.yaml").write_text(
            "\n".join(layout_lines) + "\n",
            encoding="utf-8",
        )
        (root / "config" / "commands.yaml").write_text(
            "\n".join(
                [
                    "commands:",
                    "  - workspace.open",
                    "  - workspace.reopen_last",
                    "  - session.restore",
                    "  - tab.focus",
                    "  - layout.apply_default",
                    "  - terminal.focus",
                    "  - terminal.restart",
                    "  - docker.restart",
                    "  - db.run_query",
                    "  - curl.send",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        (root / "config" / "themes" / "default.tcss").write_text("", encoding="utf-8")

        workspace_dir = root / "workspace"
        workspace_dir.mkdir()
        nested_dir = workspace_dir / "nested"
        nested_dir.mkdir()
        (workspace_dir / "README.md").write_text("# fixture\n", encoding="utf-8")
        selected_file = nested_dir / "target.txt"
        selected_file.write_text("resume target\n", encoding="utf-8")
        return root, workspace_dir, nested_dir, selected_file

    @staticmethod
    def _rendered_text(widget: object) -> str:
        renderable = getattr(widget, "renderable", None)
        if renderable is not None:
            return str(renderable)
        return str(getattr(widget, "render")())

    def _init_git_repo(self, repo: Path) -> None:
        self._git(repo, "init")
        self._git(repo, "config", "user.name", "Cockpit Tests")
        self._git(repo, "config", "user.email", "tests@example.com")
        tracked = repo / "tracked.txt"
        tracked.write_text("initial\n", encoding="utf-8")
        self._git(repo, "add", "tracked.txt")
        self._git(repo, "commit", "-m", "Initial commit")

    def _git(self, repo: Path, *args: str) -> None:
        completed = run(
            ("git", "-C", str(repo), *args),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(completed.stderr or completed.stdout)


if __name__ == "__main__":
    unittest.main()
