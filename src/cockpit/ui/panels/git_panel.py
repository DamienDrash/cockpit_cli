"""Professional GitPanel implementation with Split View and Operations."""

from __future__ import annotations

from pathlib import Path
from rich.text import Text
from rich.syntax import Syntax
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static, Input, Label

from cockpit.application.dispatch.event_bus import EventBus
from cockpit.domain.events.runtime_events import PanelMounted, PanelStateChanged
from cockpit.domain.models.panel_state import PanelState
from cockpit.infrastructure.git.git_adapter import GitAdapter, GitFileStatus, GitRepositoryStatus
from cockpit.shared.enums import SessionTargetKind, StatusLevel
from cockpit.ui.panels.base_panel import BasePanel
from cockpit.ui.branding import C_PRIMARY, C_SECONDARY


class GitPanel(BasePanel):
    """Professional Git TUI with status, diff, and staging capabilities."""

    PANEL_ID = "git-panel"
    PANEL_TYPE = "git"

    def __init__(self, *, event_bus: EventBus, git_adapter: GitAdapter) -> None:
        super().__init__(id=self.PANEL_ID)
        self._event_bus = event_bus
        self._git_adapter = git_adapter
        self._workspace_name = "Workspace"
        self._workspace_root = ""
        self._target_kind = SessionTargetKind.LOCAL
        self._target_ref: str | None = None
        self._repo_root = ""
        self._branch_summary = ""
        self._files: list[GitFileStatus] = []
        self._selected_index = 0
        self._commit_mode = False

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="git-sidebar", classes="sidebar"):
                yield Label(" [ BRANCH ] ", classes="section-title")
                yield Static("loading...", id="git-branch-info")
                yield Label(" [ FILES ] ", classes="section-title")
                yield Static("", id="git-file-list", classes="list-view")
                yield Label(" [ ACTIONS ] ", classes="section-title")
                yield Static(
                    " s: Stage\n"
                    " u: Unstage\n"
                    " c: Commit\n"
                    " r: Refresh",
                    id="git-legend"
                )
            
            with Vertical(id="git-main"):
                with Vertical(id="git-commit-container"):
                    yield Label("Commit Message:")
                    yield Input(placeholder="Enter message and press Enter...", id="git-commit-input")
                yield Static("Select a file to see diff", id="git-diff-view", classes="diff-view")

    def on_mount(self) -> None:
        self.query_one("#git-commit-container").display = False
        self._event_bus.publish(PanelMounted(panel_id=self.PANEL_ID, panel_type=self.PANEL_TYPE))
        self.refresh_status()

    def initialize(self, context: dict[str, object]) -> None:
        self._workspace_root = str(context.get("workspace_root", ""))
        self._target_kind = SessionTargetKind(str(context.get("target_kind", "local")))
        self._target_ref = context.get("target_ref")
        self.refresh_status()

    def on_key(self, event: events.Key) -> None:
        if self._commit_mode:
            if event.key == "escape":
                self._toggle_commit_mode(False)
                event.stop()
            return

        if event.key == "up":
            self._move_selection(-1)
            event.stop()
        elif event.key == "down":
            self._move_selection(1)
            event.stop()
        elif event.key == "s":
            self._stage_selected()
            event.stop()
        elif event.key == "u":
            self._unstage_selected()
            event.stop()
        elif event.key == "c":
            self._toggle_commit_mode(True)
            event.stop()
        elif event.key == "r":
            self.refresh_status()
            event.stop()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "git-commit-input":
            self._handle_commit(event.value)
            event.stop()

    def refresh_status(self) -> None:
        try:
            status = self._git_adapter.inspect_repository(
                self._workspace_root,
                target_kind=self._target_kind,
                target_ref=self._target_ref,
            )
            self._repo_root = status.repo_root
            self._branch_summary = status.branch_summary
            self._files = status.files
            self._render_all()
        except Exception as exc:
            self.query_one("#git-branch-info", Static).update(f"[red]Error: {exc}[/red]")

    def _render_all(self) -> None:
        # 1. Branch Info
        self.query_one("#git-branch-info", Static).update(f" [bold cyan] {self._branch_summary}[/]")
        
        # 2. File List
        file_list = Text()
        for i, f in enumerate(self._files):
            is_selected = i == self._selected_index
            marker = "▶ " if is_selected else "  "
            style = f"{C_SECONDARY} bold" if is_selected else ""
            
            status_style = "green" if f.staged_status != " " else "red"
            if f.status_code == "??": status_style = "yellow"
            
            file_list.append(marker, style=C_PRIMARY if is_selected else "dim")
            file_list.append(f"{f.status_code} ", style=status_style)
            file_list.append(f"{Path(f.path).name}\n", style=style)
        
        self.query_one("#git-file-list", Static).update(file_list)
        
        # 3. Diff View
        self._update_diff()

    def _update_diff(self) -> None:
        if not self._files:
            self.query_one("#git-diff-view", Static).update("Working tree clean.")
            return
            
        selected = self._files[self._selected_index]
        try:
            diff_text = self._git_adapter.get_diff(
                self._repo_root, 
                selected.path,
                staged=(selected.staged_status != " "),
                target_kind=self._target_kind,
                target_ref=self._target_ref
            )
            if not diff_text:
                diff_text = f"No changes in {Path(selected.path).name} (status {selected.status_code})"
            
            self.query_one("#git-diff-view", Static).update(Syntax(diff_text, "diff", theme="monokai"))
        except Exception as exc:
            self.query_one("#git-diff-view", Static).update(f"[red]Diff failed: {exc}[/red]")

    def _move_selection(self, delta: int) -> None:
        if not self._files: return
        self._selected_index = max(0, min(len(self._files) - 1, self._selected_index + delta))
        self._render_all()

    def _stage_selected(self) -> None:
        if not self._files: return
        f = self._files[self._selected_index]
        if self._git_adapter.stage_file(self._repo_root, f.path, target_kind=self._target_kind, target_ref=self._target_ref):
            self.refresh_status()

    def _unstage_selected(self) -> None:
        if not self._files: return
        f = self._files[self._selected_index]
        if self._git_adapter.unstage_file(self._repo_root, f.path, target_kind=self._target_kind, target_ref=self._target_ref):
            self.refresh_status()

    def _toggle_commit_mode(self, enabled: bool) -> None:
        self._commit_mode = enabled
        container = self.query_one("#git-commit-container")
        container.display = enabled
        if enabled:
            inp = self.query_one("#git-commit-input", Input)
            inp.value = ""
            inp.focus()
        else:
            self.focus()

    def _handle_commit(self, message: str) -> None:
        if not message.strip(): return
        if self._git_adapter.commit(self._repo_root, message, target_kind=self._target_kind, target_ref=self._target_ref):
            self._toggle_commit_mode(False)
            self.refresh_status()
            self.app.notify("Changes committed successfully.")

    def resume(self) -> None:
        self.refresh_status()

    def snapshot_state(self) -> PanelState:
        return PanelState(panel_id=self.PANEL_ID, panel_type=self.PANEL_TYPE)
