"""Structured adapter for local git status inspection."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import subprocess


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
    """Load structured repository status from the local git executable."""

    def inspect_repository(self, root_path: str) -> GitRepositoryStatus:
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

        return self._parse_status_output(repo_root, status_result.stdout)

    def _run_git(self, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ("git", "-C", str(cwd), *args),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    def _parse_status_output(self, repo_root: Path, raw_output: str) -> GitRepositoryStatus:
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
            files.append(
                GitFileStatus(
                    path=str((repo_root / relative_path).resolve()),
                    status_code=status_code,
                    staged_status=status_code[0],
                    unstaged_status=status_code[1],
                )
            )

        message = None if files else "Working tree clean."
        return GitRepositoryStatus(
            repo_root=str(repo_root),
            branch_summary=branch_summary,
            files=files,
            is_repository=True,
            is_available=True,
            message=message,
        )
