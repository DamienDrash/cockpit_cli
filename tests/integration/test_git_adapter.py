from pathlib import Path
from shutil import which
from subprocess import run
from tempfile import TemporaryDirectory
import unittest

from cockpit.infrastructure.git.git_adapter import GitAdapter


@unittest.skipUnless(which("git"), "git must be installed for git adapter tests")
class GitAdapterTests(unittest.TestCase):
    def test_inspect_repository_returns_branch_and_changed_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo = Path(temp_dir)
            self._init_repo(repo)
            tracked = repo / "tracked.txt"
            tracked.write_text("changed\n", encoding="utf-8")
            untracked = repo / "untracked.txt"
            untracked.write_text("new\n", encoding="utf-8")

            status = GitAdapter().inspect_repository(str(repo))

            self.assertTrue(status.is_repository)
            self.assertEqual(status.repo_root, str(repo.resolve()))
            self.assertTrue(status.branch_summary)
            paths = {Path(item.path).name for item in status.files}
            self.assertIn("tracked.txt", paths)
            self.assertIn("untracked.txt", paths)

    def test_inspect_repository_reports_non_git_directories_cleanly(self) -> None:
        with TemporaryDirectory() as temp_dir:
            status = GitAdapter().inspect_repository(temp_dir)

            self.assertFalse(status.is_repository)
            self.assertIn("not a git repository", status.branch_summary)

    def _init_repo(self, repo: Path) -> None:
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
