from subprocess import CompletedProcess
import unittest
from unittest.mock import patch

from cockpit.infrastructure.docker.docker_adapter import DockerAdapter
from cockpit.infrastructure.ssh.command_runner import SSHCommandResult
from cockpit.shared.enums import SessionTargetKind


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


class DockerAdapterTests(unittest.TestCase):
    def test_reports_missing_docker_binary_cleanly(self) -> None:
        adapter = DockerAdapter()
        with patch("cockpit.infrastructure.docker.docker_adapter.subprocess.run") as run_mock:
            run_mock.side_effect = FileNotFoundError()
            snapshot = adapter.list_containers()

        self.assertFalse(snapshot.is_available)
        self.assertFalse(snapshot.daemon_reachable)
        self.assertIn("docker executable", snapshot.message or "")

    def test_parses_container_listing(self) -> None:
        adapter = DockerAdapter()
        stdout = "\n".join(
            [
                "abc123\tweb\tnginx:latest\trunning\tUp 2 minutes\t0.0.0.0:80->80/tcp",
                "def456\tdb\tpostgres:16\texited\tExited (0) 1 hour ago\t",
            ]
        )
        with patch(
            "cockpit.infrastructure.docker.docker_adapter.subprocess.run",
            return_value=CompletedProcess(
                args=("docker",),
                returncode=0,
                stdout=stdout,
                stderr="",
            ),
        ):
            snapshot = adapter.list_containers()

        self.assertTrue(snapshot.is_available)
        self.assertTrue(snapshot.daemon_reachable)
        self.assertEqual(len(snapshot.containers), 2)
        self.assertEqual(snapshot.containers[0].name, "web")
        self.assertEqual(snapshot.containers[1].state, "exited")

    def test_reports_daemon_failure_without_crashing(self) -> None:
        adapter = DockerAdapter()
        with patch(
            "cockpit.infrastructure.docker.docker_adapter.subprocess.run",
            return_value=CompletedProcess(
                args=("docker",),
                returncode=1,
                stdout="",
                stderr="Cannot connect to the Docker daemon at unix:///var/run/docker.sock",
            ),
        ):
            snapshot = adapter.list_containers()

        self.assertTrue(snapshot.is_available)
        self.assertFalse(snapshot.daemon_reachable)
        self.assertIn("Cannot connect", snapshot.message or "")

    def test_parses_remote_container_listing(self) -> None:
        adapter = DockerAdapter(
            ssh_command_runner=FakeSSHCommandRunner(
                SSHCommandResult(
                    target_ref="dev@example.com",
                    command="docker ps",
                    returncode=0,
                    stdout="abc123\tweb\tnginx:latest\trunning\tUp 2 minutes\t80/tcp\n",
                    stderr="",
                )
            )
        )

        snapshot = adapter.list_containers(
            target_kind=SessionTargetKind.SSH,
            target_ref="dev@example.com",
        )

        self.assertTrue(snapshot.is_available)
        self.assertEqual(len(snapshot.containers), 1)
        self.assertEqual(snapshot.containers[0].name, "web")

    def test_restarts_local_container(self) -> None:
        adapter = DockerAdapter()
        with patch(
            "cockpit.infrastructure.docker.docker_adapter.subprocess.run",
            return_value=CompletedProcess(
                args=("docker", "restart", "abc123"),
                returncode=0,
                stdout="abc123\n",
                stderr="",
            ),
        ):
            result = adapter.restart_container("abc123")

        self.assertTrue(result.success)
        self.assertEqual(result.message, "abc123")

    def test_reports_missing_docker_binary_on_restart(self) -> None:
        adapter = DockerAdapter()
        with patch("cockpit.infrastructure.docker.docker_adapter.subprocess.run") as run_mock:
            run_mock.side_effect = FileNotFoundError()
            result = adapter.restart_container("abc123")

        self.assertFalse(result.success)
        self.assertIn("docker executable", result.message)

    def test_restarts_remote_container(self) -> None:
        adapter = DockerAdapter(
            ssh_command_runner=FakeSSHCommandRunner(
                SSHCommandResult(
                    target_ref="dev@example.com",
                    command="docker restart abc123",
                    returncode=0,
                    stdout="abc123\n",
                    stderr="",
                )
            )
        )

        result = adapter.restart_container(
            "abc123",
            target_kind=SessionTargetKind.SSH,
            target_ref="dev@example.com",
        )

        self.assertTrue(result.success)
        self.assertEqual(result.message, "abc123")

    def test_stops_remote_container(self) -> None:
        adapter = DockerAdapter(
            ssh_command_runner=FakeSSHCommandRunner(
                SSHCommandResult(
                    target_ref="dev@example.com",
                    command="docker stop abc123",
                    returncode=0,
                    stdout="abc123\n",
                    stderr="",
                )
            )
        )

        result = adapter.stop_container(
            "abc123",
            target_kind=SessionTargetKind.SSH,
            target_ref="dev@example.com",
        )

        self.assertTrue(result.success)
        self.assertEqual(result.message, "abc123")

    def test_removes_remote_container(self) -> None:
        adapter = DockerAdapter(
            ssh_command_runner=FakeSSHCommandRunner(
                SSHCommandResult(
                    target_ref="dev@example.com",
                    command="docker rm abc123",
                    returncode=0,
                    stdout="abc123\n",
                    stderr="",
                )
            )
        )

        result = adapter.remove_container(
            "abc123",
            target_kind=SessionTargetKind.SSH,
            target_ref="dev@example.com",
        )

        self.assertTrue(result.success)
        self.assertEqual(result.message, "abc123")


if __name__ == "__main__":
    unittest.main()
