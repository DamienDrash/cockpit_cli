import unittest

from cockpit.infrastructure.git.git_adapter import GitAdapter
from cockpit.infrastructure.ssh.command_runner import SSHCommandResult
from cockpit.shared.enums import SessionTargetKind


class FakeSSHCommandRunner:
    def __init__(self, results: list[SSHCommandResult]) -> None:
        self._results = list(results)

    def run(
        self,
        target_ref: str,
        command: str,
        *,
        timeout_seconds: int = 5,
        input_text: str | None = None,
    ) -> SSHCommandResult:
        del timeout_seconds, input_text
        if not self._results:
            raise AssertionError("No fake SSH result remaining.")
        result = self._results.pop(0)
        return SSHCommandResult(
            target_ref=target_ref,
            command=command,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            is_available=result.is_available,
            message=result.message,
        )


class RemoteGitAdapterTests(unittest.TestCase):
    def test_inspect_repository_supports_ssh_targets(self) -> None:
        adapter = GitAdapter(
            ssh_command_runner=FakeSSHCommandRunner(
                [
                    SSHCommandResult(
                        target_ref="dev@example.com",
                        command="rev-parse",
                        returncode=0,
                        stdout="/srv/app\n",
                        stderr="",
                    ),
                    SSHCommandResult(
                        target_ref="dev@example.com",
                        command="status",
                        returncode=0,
                        stdout="## main...origin/main\n M tracked.txt\n?? untracked.txt\n",
                        stderr="",
                    ),
                ]
            )
        )

        status = adapter.inspect_repository(
            "/srv/app",
            target_kind=SessionTargetKind.SSH,
            target_ref="dev@example.com",
        )

        self.assertTrue(status.is_repository)
        self.assertEqual(status.repo_root, "/srv/app")
        self.assertEqual(status.branch_summary, "main...origin/main")
        self.assertEqual(
            {item.path for item in status.files},
            {"/srv/app/tracked.txt", "/srv/app/untracked.txt"},
        )


if __name__ == "__main__":
    unittest.main()
