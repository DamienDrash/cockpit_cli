import unittest

from cockpit.infrastructure.ssh.ssh_shell_adapter import SSHShellAdapter
from cockpit.shared.enums import SessionTargetKind


class SSHShellAdapterTests(unittest.TestCase):
    def test_builds_interactive_ssh_launch_command(self) -> None:
        adapter = SSHShellAdapter()

        launch = adapter.build_launch_config(
            "/srv/app",
            target_kind=SessionTargetKind.SSH,
            target_ref="dev@example.com",
        )

        self.assertEqual(launch.command[:3], ("ssh", "-tt", "dev@example.com"))
        self.assertIn("cd /srv/app", launch.command[3])
        self.assertIn('exec "${SHELL:-/bin/bash}" -li', launch.command[3])


if __name__ == "__main__":
    unittest.main()
