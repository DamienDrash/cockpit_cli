"""Structured adapter for local and SSH git status inspection."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
import shlex
import subprocess

from cockpit.infrastructure.ssh.command_runner import SSHCommandRunner
from cockpit.shared.enums import SessionTargetKind


@dataclass(slots=True, frozen=True)
class GitFileStatus:
    path: str
    status_code: str
    staged_status: str
    unstaged_status: str


@dataclass(slots=True, frozen=True)
class GitRepositoryStatus:
    repo_root: str
    branch_summary: str
    files: list[GitFileStatus] = field(default_factory=list)
    is_repository: bool = True
    is_available: bool = True
    message: str | None = None


class GitAdapter:
    """Load structured repository status from git executables or SSH targets."""

    def __init__(self, ssh_command_runner: SSHCommandRunner | None = None) -> None:
        self._ssh_command_runner = ssh_command_runner

    def inspect_repository(
        self,
        root_path: str,
        *,
        target_kind: SessionTargetKind = SessionTargetKind.LOCAL,
        target_ref: str | None = None,
    ) -> GitRepositoryStatus:
        if target_kind is SessionTargetKind.SSH:
            return self._inspect_remote_repository(root_path, target_ref)
        return self._inspect_local_repository(root_path)

    def _inspect_local_repository(self, root_path: str) -> GitRepositoryStatus:
        path = Path(root_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"Git path '{path}' does not exist.")
        if not path.is_dir():
            raise NotADirectoryError(f"Git path '{path}' is not a directory.")

        try:
            repo_root_result = self._run_git(path, "rev-parse", "--show-toplevel")
        except FileNotFoundError:
            return GitRepositoryStatus(
                repo_root=str(path),
                branch_summary="git executable unavailable",
                is_repository=False,
                is_available=False,
                message="The git executable is not available in this environment.",
            )

        if repo_root_result.returncode != 0:
            return GitRepositoryStatus(
                repo_root=str(path),
                branch_summary="not a git repository",
                is_repository=False,
                message=repo_root_result.stderr.strip() or "The workspace is not a git repository.",
            )

        repo_root = Path(repo_root_result.stdout.strip()).resolve()
        status_result = self._run_git(repo_root, "status", "--porcelain=v1", "--branch")
        if status_result.returncode != 0:
            return GitRepositoryStatus(
                repo_root=str(repo_root),
                branch_summary="git status failed",
                is_repository=True,
                message=status_result.stderr.strip() or "git status failed.",
            )

        return self._parse_status_output(str(repo_root), status_result.stdout, remote=False)

    def _inspect_remote_repository(
        self,
        root_path: str,
        target_ref: str | None,
    ) -> GitRepositoryStatus:
        if not target_ref:
            return GitRepositoryStatus(
                repo_root=root_path,
                branch_summary="ssh target unavailable",
                is_repository=False,
                is_available=False,
                message="No SSH target is configured for this workspace.",
            )
        if self._ssh_command_runner is None:
            return GitRepositoryStatus(
                repo_root=root_path,
                branch_summary="ssh inspection unavailable",
                is_repository=False,
                is_available=False,
                message="SSH git inspection is not configured.",
            )

        repo_root_result = self._ssh_command_runner.run(
            target_ref,
            f"git -C {shlex.quote(root_path)} rev-parse --show-toplevel",
        )
        if not repo_root_result.is_available:
            return GitRepositoryStatus(
                repo_root=root_path,
                branch_summary="ssh unavailable",
                is_repository=False,
                is_available=False,
                message=repo_root_result.message or "SSH is unavailable.",
            )
        if repo_root_result.returncode != 0:
            return GitRepositoryStatus(
                repo_root=root_path,
                branch_summary="not a git repository",
                is_repository=False,
                message=repo_root_result.stderr.strip()
                or repo_root_result.message
                or "The remote workspace is not a git repository.",
            )

        repo_root = repo_root_result.stdout.strip().splitlines()[-1].strip()
        status_result = self._ssh_command_runner.run(
            target_ref,
            f"git -C {shlex.quote(repo_root)} status --porcelain=v1 --branch",
        )
        if status_result.returncode != 0:
            return GitRepositoryStatus(
                repo_root=repo_root,
                branch_summary="git status failed",
                is_repository=True,
                is_available=True,
                message=status_result.stderr.strip()
                or status_result.message
                or "git status failed.",
            )

        return self._parse_status_output(repo_root, status_result.stdout, remote=True)

    def _run_git(self, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ("git", "-C", str(cwd), *args),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    def _parse_status_output(
        self,
        repo_root: str,
        raw_output: str,
        *,
        remote: bool,
    ) -> GitRepositoryStatus:
        lines = raw_output.splitlines()
        branch_summary = "clean"
        files: list[GitFileStatus] = []

        if lines and lines[0].startswith("## "):
            branch_summary = lines[0][3:].strip() or "detached"
            lines = lines[1:]

        for line in lines:
            if len(line) < 4:
                continue
            status_code = line[:2]
            relative_path = line[3:]
            if " -> " in relative_path:
                relative_path = relative_path.split(" -> ", 1)[1]
            if remote:
                absolute_path = str(PurePosixPath(repo_root) / relative_path)
            else:
                absolute_path = str((Path(repo_root) / relative_path).resolve())
            files.append(
                GitFileStatus(
                    path=absolute_path,
                    status_code=status_code,
                    staged_status=status_code[0],
                    unstaged_status=status_code[1],
                )
            )

        message = None if files else "Working tree clean."
        return GitRepositoryStatus(
            repo_root=repo_root,
            branch_summary=branch_summary,
            files=files,
            is_repository=True,
            is_available=True,
            message=message,
        )
