"""Focusable file explorer widget for the WorkPanel."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from textual.widgets import Static


@dataclass(slots=True, frozen=True)
class ExplorerSelection:
    browser_path: str
    selected_path: str
    recovery_message: str | None = None


class FileExplorer(Static):
    """Simple keyboard-first explorer for local workspace paths."""

    can_focus = True

    def __init__(self) -> None:
        super().__init__("No explorer context loaded.", id="file-explorer")
        self._root_path: Path | None = None
        self._browser_path: Path | None = None
        self._entries: list[Path] = []
        self._selected_index = 0

    @property
    def browser_path(self) -> str:
        return str(self._browser_path) if self._browser_path is not None else ""

    @property
    def selected_path(self) -> str:
        if not self._entries:
            return self.browser_path
        return str(self._entries[self._selected_index])

    def load(
        self,
        *,
        root_path: str,
        browser_path: str | None = None,
        selected_path: str | None = None,
    ) -> ExplorerSelection:
        root = Path(root_path).expanduser().resolve()
        browser = self._resolve_browser_path(root, browser_path)
        recovery_messages: list[str] = []

        if browser != Path(browser_path).expanduser().resolve() if browser_path else False:
            recovery_messages.append("Explorer path was reset to the workspace root.")

        self._root_path = root
        self._browser_path = browser
        self._entries = self._list_entries(browser)
        self._selected_index = self._resolve_selected_index(selected_path)

        if selected_path and self.selected_path != str(Path(selected_path).expanduser()):
            selected_candidate = Path(selected_path).expanduser()
            if not selected_candidate.exists():
                recovery_messages.append("Explorer selection no longer exists.")
            elif root not in selected_candidate.resolve().parents and selected_candidate.resolve() != root:
                recovery_messages.append("Explorer selection moved outside the workspace and was reset.")

        self._render()
        return ExplorerSelection(
            browser_path=self.browser_path,
            selected_path=self.selected_path,
            recovery_message=" ".join(recovery_messages) if recovery_messages else None,
        )

    def move_selection(self, delta: int) -> ExplorerSelection:
        if self._entries:
            self._selected_index = max(
                0,
                min(len(self._entries) - 1, self._selected_index + delta),
            )
        self._render()
        return ExplorerSelection(
            browser_path=self.browser_path,
            selected_path=self.selected_path,
        )

    def open_selection(self) -> ExplorerSelection:
        selected = Path(self.selected_path)
        if selected.is_dir():
            return self.load(
                root_path=str(self._root_path),
                browser_path=str(selected),
                selected_path=str(selected),
            )
        self._render()
        return ExplorerSelection(
            browser_path=self.browser_path,
            selected_path=self.selected_path,
        )

    def go_parent(self) -> ExplorerSelection:
        if self._root_path is None or self._browser_path is None:
            return ExplorerSelection(browser_path="", selected_path="")
        if self._browser_path == self._root_path:
            self._render()
            return ExplorerSelection(
                browser_path=self.browser_path,
                selected_path=self.selected_path,
            )
        parent = self._browser_path.parent
        return self.load(
            root_path=str(self._root_path),
            browser_path=str(parent),
            selected_path=str(parent),
        )

    def _resolve_browser_path(self, root: Path, browser_path: str | None) -> Path:
        if not browser_path:
            return root
        candidate = Path(browser_path).expanduser()
        if not candidate.exists():
            return root
        resolved = candidate.resolve()
        if root not in resolved.parents and resolved != root:
            return root
        if resolved.is_file():
            return resolved.parent
        return resolved

    def _resolve_selected_index(self, selected_path: str | None) -> int:
        if not self._entries:
            return 0
        if not selected_path:
            return 0
        candidate = Path(selected_path).expanduser()
        try:
            resolved = candidate.resolve()
        except FileNotFoundError:
            return 0
        for index, entry in enumerate(self._entries):
            if entry == resolved:
                return index
        return 0

    def _list_entries(self, directory: Path) -> list[Path]:
        entries = sorted(
            directory.iterdir(),
            key=lambda path: (not path.is_dir(), path.name.lower()),
        )
        return entries[:200]

    def _render(self) -> None:
        if self._browser_path is None:
            self.update("No explorer context loaded.")
            return
        lines = [f"Explorer: {self._browser_path}"]
        if not self._entries:
            lines.append("  (empty)")
            self.update("\n".join(lines))
            return

        for index, entry in enumerate(self._windowed_entries()):
            marker = ">" if entry[0] else " "
            path = entry[1]
            label = f"{path.name}/" if path.is_dir() else path.name
            lines.append(f"{marker} {label}")
        self.update("\n".join(lines))

    def _windowed_entries(self) -> list[tuple[bool, Path]]:
        if not self._entries:
            return []
        window = 10
        start = max(0, self._selected_index - window // 2)
        end = min(len(self._entries), start + window)
        start = max(0, end - window)
        return [
            (index == self._selected_index, self._entries[index])
            for index in range(start, end)
        ]
