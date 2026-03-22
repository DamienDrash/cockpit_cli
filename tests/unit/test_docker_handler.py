import unittest

from cockpit.application.handlers.base import ConfirmationRequiredError
from cockpit.application.handlers.docker_handlers import RestartDockerContainerHandler
from cockpit.domain.commands.command import Command
from cockpit.infrastructure.docker.docker_adapter import DockerActionResult
from cockpit.shared.enums import CommandSource, SessionTargetKind


class FakeDockerAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, SessionTargetKind, str | None]] = []

    def restart_container(
        self,
        container_id: str,
        *,
        target_kind: SessionTargetKind = SessionTargetKind.LOCAL,
        target_ref: str | None = None,
    ) -> DockerActionResult:
        self.calls.append((container_id, target_kind, target_ref))
        return DockerActionResult(success=True, message=f"restarted {container_id}")


class RestartDockerContainerHandlerTests(unittest.TestCase):
    def test_requires_confirmation_before_restart(self) -> None:
        adapter = FakeDockerAdapter()
        handler = RestartDockerContainerHandler(adapter)
        command = Command(
            id="cmd_1",
            source=CommandSource.KEYBINDING,
            name="docker.restart",
            context={
                "selected_container_id": "abc123",
                "selected_container_name": "web",
                "workspace_name": "payments-prod",
                "workspace_root": "/srv/payments",
                "target_kind": SessionTargetKind.LOCAL.value,
            },
        )

        with self.assertRaises(ConfirmationRequiredError) as ctx:
            handler(command)

        self.assertEqual(adapter.calls, [])
        self.assertEqual(
            ctx.exception.payload["pending_command_name"],
            "docker.restart",
        )
        self.assertIn("Restart container web?", ctx.exception.payload["confirmation_message"])
        self.assertIn("PROD", str(ctx.exception))

    def test_restarts_selected_container_after_confirmation(self) -> None:
        adapter = FakeDockerAdapter()
        handler = RestartDockerContainerHandler(adapter)
        command = Command(
            id="cmd_2",
            source=CommandSource.KEYBINDING,
            name="docker.restart",
            args={"confirmed": True},
            context={
                "selected_container_id": "abc123",
                "target_kind": SessionTargetKind.SSH.value,
                "target_ref": "dev@example.com",
            },
        )

        result = handler(command)

        self.assertTrue(result.success)
        self.assertEqual(
            adapter.calls,
            [("abc123", SessionTargetKind.SSH, "dev@example.com")],
        )
        self.assertEqual(result.data["refresh_panel_id"], "docker-panel")
        self.assertEqual(result.data["restarted_container_id"], "abc123")


if __name__ == "__main__":
    unittest.main()
