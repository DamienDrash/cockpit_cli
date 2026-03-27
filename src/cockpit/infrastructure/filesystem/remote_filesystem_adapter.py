"""Remote filesystem inspection for SSH-backed workspaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
import shlex

from cockpit.datasources.adapters.ssh_command_runner import SSHCommandRunner


@dataclass(slots=True, frozen=True)
class RemotePathEntry:
    path: str
    is_dir: bool

    @property
    def name(self) -> str:
        return PurePosixPath(self.path).name or self.path


@dataclass(slots=True, frozen=True)
class RemoteDirectorySnapshot:
    browser_path: str
    entries: list[RemotePathEntry] = field(default_factory=list)
    is_available: bool = True
    message: str | None = None


class RemoteFilesystemAdapter:
    """Load directory listings from a remote SSH target."""

    _SPLIT_MARKER = "__COCKPIT_REMOTE_LISTING__"

    def __init__(self, ssh_command_runner: SSHCommandRunner) -> None:
        self._ssh_command_runner = ssh_command_runner

    def list_directory(
        self,
        *,
        target_ref: str | None,
        root_path: str,
        browser_path: str | None = None,
    ) -> RemoteDirectorySnapshot:
        if not target_ref:
            return RemoteDirectorySnapshot(
                browser_path=browser_path or root_path,
                is_available=False,
                message="No SSH target is configured for this workspace.",
            )

        browse_target = browser_path or root_path or "."
        command = self._directory_command(
            root_path=root_path or ".", browser_path=browse_target
        )
        result = self._ssh_command_runner.run(target_ref, command)
        if not result.is_available:
            return RemoteDirectorySnapshot(
                browser_path=browse_target,
                is_available=False,
                message=result.message or "SSH is unavailable.",
            )
        if result.returncode != 0:
            return RemoteDirectorySnapshot(
                browser_path=browse_target,
                is_available=True,
                message=result.stderr.strip()
                or result.message
                or "Remote directory inspection failed.",
            )

        browser_root, entries = self._parse_directory_output(result.stdout)
        if browser_root is None:
            return RemoteDirectorySnapshot(
                browser_path=browse_target,
                is_available=True,
                message="Remote directory output could not be parsed.",
            )

        return RemoteDirectorySnapshot(
            browser_path=browser_root,
            entries=entries,
            is_available=True,
            message=None if entries else "Remote directory is empty.",
        )

    def _directory_command(self, *, root_path: str, browser_path: str) -> str:
        return "\n".join(
            (
                f"target={shlex.quote(browser_path)}",
                f"fallback={shlex.quote(root_path)}",
                'cd "$target" 2>/dev/null || cd "$fallback" 2>/dev/null || exit 32',
                "pwd",
                f"printf '{self._SPLIT_MARKER}\\n'",
                "LC_ALL=C ls -1Ap",
            )
        )

    def _parse_directory_output(
        self,
        raw_output: str,
    ) -> tuple[str | None, list[RemotePathEntry]]:
        marker = f"\n{self._SPLIT_MARKER}\n"
        if marker not in raw_output:
            return None, []
        browser_root, listing_block = raw_output.split(marker, 1)
        browser_root = browser_root.strip()
        if not browser_root:
            return None, []

        base_path = PurePosixPath(browser_root)
        entries: list[RemotePathEntry] = []
        for line in listing_block.splitlines():
            entry_name = line.strip()
            if not entry_name:
                continue
            is_dir = entry_name.endswith("/")
            normalized_name = entry_name[:-1] if is_dir else entry_name
            entries.append(
                RemotePathEntry(
                    path=str(base_path / normalized_name),
                    is_dir=is_dir,
                )
            )
        return browser_root, entries
