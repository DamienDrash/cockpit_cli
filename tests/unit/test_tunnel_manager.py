from types import SimpleNamespace
import unittest

from cockpit.infrastructure.ssh.tunnel_manager import SSHTunnelManager


class FakeProcess:
    def __init__(self) -> None:
        self.returncode = None
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class FakeLauncher:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.processes: list[FakeProcess] = []

    def __call__(self, argv: list[str], **kwargs: object) -> FakeProcess:
        del kwargs
        self.calls.append(list(argv))
        process = FakeProcess()
        self.processes.append(process)
        return process


class SSHTunnelManagerTests(unittest.TestCase):
    def test_reuses_matching_tunnel_and_closes_on_shutdown(self) -> None:
        launcher = FakeLauncher()
        manager = SSHTunnelManager(launcher=launcher)

        first = manager.open_tunnel(
            profile_id="dsp_1",
            target_ref="deploy@example.com",
            remote_host="db.internal",
            remote_port=5432,
        )
        second = manager.open_tunnel(
            profile_id="dsp_1",
            target_ref="deploy@example.com",
            remote_host="db.internal",
            remote_port=5432,
        )

        self.assertIs(first, second)
        self.assertEqual(len(launcher.calls), 1)

        manager.shutdown()

        self.assertTrue(launcher.processes[0].terminated)
        self.assertEqual(first.remote_port, 5432)
        self.assertGreater(first.local_port, 0)

    def test_replaces_existing_tunnel_when_target_changes(self) -> None:
        launcher = FakeLauncher()
        manager = SSHTunnelManager(launcher=launcher)

        original = manager.open_tunnel(
            profile_id="dsp_1",
            target_ref="deploy@example.com",
            remote_host="db.internal",
            remote_port=5432,
        )
        replacement = manager.open_tunnel(
            profile_id="dsp_1",
            target_ref="deploy@example.com",
            remote_host="cache.internal",
            remote_port=6379,
        )

        self.assertEqual(len(launcher.calls), 2)
        self.assertTrue(launcher.processes[0].terminated)
        self.assertEqual(original.remote_host, "db.internal")
        self.assertEqual(replacement.remote_host, "cache.internal")
