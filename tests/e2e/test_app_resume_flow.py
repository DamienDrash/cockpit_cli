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
    from cockpit.infrastructure.shell.local_shell_adapter import (
        LocalShellAdapter,
        ShellLaunchConfig,
    )
    from cockpit.ui.panels.git_panel import GitPanel
    from cockpit.ui.panels.logs_panel import LogsPanel
    from cockpit.ui.screens.app_shell import CockpitApp
    from cockpit.ui.widgets.command_palette import CommandPalette
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
        ) -> "ShellLaunchConfig":
            if command is not None:
                return super().build_launch_config(cwd, command=command)

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


@unittest.skipUnless(TEXTUAL_AVAILABLE, "textual must be installed for e2e tests")
class CockpitAppE2ETests(unittest.IsolatedAsyncioTestCase):
    async def test_open_workspace_renders_work_panel(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root, workspace_dir, nested_dir, _selected_file = self._write_project_fixture(
                Path(temp_dir)
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
            root, workspace_dir, nested_dir, selected_file = self._write_project_fixture(
                Path(temp_dir)
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
            root, _workspace_dir, _nested_dir, _selected_file = self._write_project_fixture(
                Path(temp_dir)
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
    async def test_git_tab_displays_repository_status_and_restores_active_tab(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root, workspace_dir, _nested_dir, _selected_file = self._write_project_fixture(
                Path(temp_dir)
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

    async def test_logs_tab_displays_recent_activity_and_restores_active_tab(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root, workspace_dir, _nested_dir, _selected_file = self._write_project_fixture(
                Path(temp_dir)
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

    async def test_apply_default_layout_resets_focus_to_first_tab(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root, workspace_dir, _nested_dir, _selected_file = self._write_project_fixture(
                Path(temp_dir)
            )

            app = self._build_app(root)
            async with app.run_test() as pilot:
                await self._open_workspace(app, pilot, workspace_dir)
                await self._run_slash_command(app, pilot, "/tab focus logs")
                await self._run_slash_command(app, pilot, "/layout apply_default")

                tab_text = self._rendered_text(app.query_one(TabBar))

                self.assertIn("[Work]", tab_text)

    def _build_app(self, root: Path) -> "CockpitApp":
        container = build_container(
            start=root,
            shell_adapter=StaticShellAdapter(shell="/bin/sh"),
        )
        return CockpitApp(container=container)

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

    async def _run_slash_command(self, app: "CockpitApp", pilot: object, command: str) -> None:
        slash_input = app.query_one(SlashInput)
        slash_input.focus()
        slash_input.value = command
        await getattr(pilot, "press")("enter")
        await getattr(pilot, "pause")()

    def _write_project_fixture(self, root: Path) -> tuple[Path, Path, Path, Path]:
        (root / "src").mkdir()
        (root / "config" / "layouts").mkdir(parents=True)
        (root / "config" / "themes").mkdir(parents=True)
        (root / "pyproject.toml").write_text(
            "[project]\nname='cockpit-e2e'\n",
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
                    "  - id: git",
                    "    name: Git",
                    "    root_split:",
                    "      orientation: vertical",
                    "      ratio: 1.0",
                    "      children:",
                    "        - panel_id: git-panel",
                    "          panel_type: git",
                    "  - id: logs",
                    "    name: Logs",
                    "    root_split:",
                    "      orientation: vertical",
                    "      ratio: 1.0",
                    "      children:",
                    "        - panel_id: logs-panel",
                    "          panel_type: logs",
                    "focus_path:",
                    "  - work",
                    "  - work-panel",
                ]
            )
            + "\n",
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
