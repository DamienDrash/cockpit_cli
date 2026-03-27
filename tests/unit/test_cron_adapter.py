from subprocess import CompletedProcess
import unittest
from unittest.mock import patch

from cockpit.infrastructure.cron.cron_adapter import CronAdapter
from cockpit.datasources.adapters.ssh_command_runner import SSHCommandResult
from cockpit.core.enums import SessionTargetKind


class FakeSSHCommandRunner:
    def __init__(self, results: list[SSHCommandResult]) -> None:
        self._results = list(results)
        self.inputs: list[str | None] = []

    def run(
        self,
        target_ref: str,
        command: str,
        *,
        timeout_seconds: int = 5,
        input_text: str | None = None,
    ) -> SSHCommandResult:
        del timeout_seconds
        self.inputs.append(input_text)
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
        with patch(
            "cockpit.infrastructure.cron.cron_adapter.subprocess.run"
        ) as run_mock:
            run_mock.side_effect = FileNotFoundError()
            snapshot = adapter.list_jobs()

        self.assertFalse(snapshot.is_available)
        self.assertIn("crontab executable", snapshot.message or "")

    def test_parses_remote_crontab_listing(self) -> None:
        adapter = CronAdapter(
            ssh_command_runner=FakeSSHCommandRunner(
                [
                    SSHCommandResult(
                        target_ref="dev@example.com",
                        command="crontab -l",
                        returncode=0,
                        stdout="@daily /usr/local/bin/cleanup\n",
                        stderr="",
                    )
                ]
            )
        )

        snapshot = adapter.list_jobs(
            target_kind=SessionTargetKind.SSH,
            target_ref="dev@example.com",
        )

        self.assertEqual(len(snapshot.jobs), 1)
        self.assertEqual(snapshot.jobs[0].schedule, "@daily")
        self.assertEqual(snapshot.jobs[0].command, "/usr/local/bin/cleanup")

    def test_can_disable_remote_job(self) -> None:
        runner = FakeSSHCommandRunner(
            [
                SSHCommandResult(
                    target_ref="dev@example.com",
                    command="crontab -l",
                    returncode=0,
                    stdout="0 2 * * * /usr/local/bin/backup\n",
                    stderr="",
                ),
                SSHCommandResult(
                    target_ref="dev@example.com",
                    command="cat | crontab -",
                    returncode=0,
                    stdout="",
                    stderr="",
                ),
            ]
        )
        adapter = CronAdapter(ssh_command_runner=runner)

        result = adapter.set_job_enabled(
            "/usr/local/bin/backup",
            enabled=False,
            target_kind=SessionTargetKind.SSH,
            target_ref="dev@example.com",
        )

        self.assertTrue(result.success)
        self.assertEqual(runner.inputs[-1], "# 0 2 * * * /usr/local/bin/backup\n")


if __name__ == "__main__":
    unittest.main()
