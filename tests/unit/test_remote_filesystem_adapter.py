import unittest

from cockpit.infrastructure.filesystem.remote_filesystem_adapter import (
    RemoteFilesystemAdapter,
)
from cockpit.datasources.adapters.ssh_command_runner import SSHCommandResult


class FakeSSHCommandRunner:
    def __init__(self, result: SSHCommandResult) -> None:
        self._result = result

    def run(
        self,
        target_ref: str,
        command: str,
        *,
        timeout_seconds: int = 5,
        input_text: str | None = None,
    ) -> SSHCommandResult:
        del timeout_seconds, input_text
        return SSHCommandResult(
            target_ref=target_ref,
            command=command,
            returncode=self._result.returncode,
            stdout=self._result.stdout,
            stderr=self._result.stderr,
            is_available=self._result.is_available,
            message=self._result.message,
        )


class RemoteFilesystemAdapterTests(unittest.TestCase):
    def test_parses_remote_directory_listing(self) -> None:
        adapter = RemoteFilesystemAdapter(
            FakeSSHCommandRunner(
                SSHCommandResult(
                    target_ref="dev@example.com",
                    command="list",
                    returncode=0,
                    stdout="/srv/app\n__COCKPIT_REMOTE_LISTING__\ncurrent/\nREADME.md\n",
                    stderr="",
                )
            )
        )

        snapshot = adapter.list_directory(
            target_ref="dev@example.com",
            root_path="/srv/app",
            browser_path="/srv/app",
        )

        self.assertEqual(snapshot.browser_path, "/srv/app")
        self.assertEqual(
            [entry.name for entry in snapshot.entries], ["current", "README.md"]
        )
        self.assertTrue(snapshot.entries[0].is_dir)

    def test_reports_remote_listing_failures_cleanly(self) -> None:
        adapter = RemoteFilesystemAdapter(
            FakeSSHCommandRunner(
                SSHCommandResult(
                    target_ref="dev@example.com",
                    command="list",
                    returncode=255,
                    stdout="",
                    stderr="Connection refused",
                )
            )
        )

        snapshot = adapter.list_directory(
            target_ref="dev@example.com",
            root_path="/srv/app",
            browser_path="/srv/app",
        )

        self.assertEqual(snapshot.browser_path, "/srv/app")
        self.assertEqual(snapshot.entries, [])
        self.assertIn("Connection refused", snapshot.message or "")


if __name__ == "__main__":
    unittest.main()
