from subprocess import CompletedProcess
import unittest
from unittest.mock import patch

from cockpit.infrastructure.cron.cron_adapter import CronAdapter
from cockpit.infrastructure.ssh.command_runner import SSHCommandResult
from cockpit.shared.enums import SessionTargetKind


class FakeSSHCommandRunner:
    def __init__(self, result: SSHCommandResult) -> None:
        self._result = result

    def run(self, target_ref: str, command: str, *, timeout_seconds: int = 5) -> SSHCommandResult:
        return SSHCommandResult(
            target_ref=target_ref,
            command=command,
            returncode=self._result.returncode,
            stdout=self._result.stdout,
            stderr=self._result.stderr,
            is_available=self._result.is_available,
            message=self._result.message,
        )


class CronAdapterTests(unittest.TestCase):
    def test_parses_local_crontab_listing(self) -> None:
        adapter = CronAdapter()
        stdout = "\n".join(
            [
                "MAILTO=ops@example.com",
                "0 2 * * * /usr/local/bin/backup",
                "# disabled weekly job",
                "# 30 4 * * 1 /usr/local/bin/report",
            ]
        )
        with patch(
            "cockpit.infrastructure.cron.cron_adapter.subprocess.run",
            return_value=CompletedProcess(
                args=("crontab", "-l"),
                returncode=0,
                stdout=stdout,
                stderr="",
            ),
        ):
            snapshot = adapter.list_jobs()

        self.assertEqual(len(snapshot.jobs), 3)
        self.assertEqual(snapshot.jobs[0].schedule, "env")
        self.assertEqual(snapshot.jobs[1].schedule, "0 2 * * *")
        self.assertFalse(snapshot.jobs[2].enabled)
        self.assertIn("disabled weekly job", snapshot.jobs[2].comment or "")

    def test_reports_missing_crontab_binary_cleanly(self) -> None:
        adapter = CronAdapter()
        with patch("cockpit.infrastructure.cron.cron_adapter.subprocess.run") as run_mock:
            run_mock.side_effect = FileNotFoundError()
            snapshot = adapter.list_jobs()

        self.assertFalse(snapshot.is_available)
        self.assertIn("crontab executable", snapshot.message or "")

    def test_parses_remote_crontab_listing(self) -> None:
        adapter = CronAdapter(
            ssh_command_runner=FakeSSHCommandRunner(
                SSHCommandResult(
                    target_ref="dev@example.com",
                    command="crontab -l",
                    returncode=0,
                    stdout="@daily /usr/local/bin/cleanup\n",
                    stderr="",
                )
            )
        )

        snapshot = adapter.list_jobs(
            target_kind=SessionTargetKind.SSH,
            target_ref="dev@example.com",
        )

        self.assertEqual(len(snapshot.jobs), 1)
        self.assertEqual(snapshot.jobs[0].schedule, "@daily")
        self.assertEqual(snapshot.jobs[0].command, "/usr/local/bin/cleanup")


if __name__ == "__main__":
    unittest.main()
