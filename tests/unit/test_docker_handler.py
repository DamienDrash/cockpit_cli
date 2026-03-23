import unittest

from cockpit.application.handlers.base import ConfirmationRequiredError
from cockpit.application.handlers.docker_handlers import (
    RemoveDockerContainerHandler,
    RestartDockerContainerHandler,
    StopDockerContainerHandler,
)
from cockpit.domain.commands.command import Command
from cockpit.domain.models.policy import GuardDecision
from cockpit.infrastructure.docker.docker_adapter import DockerActionResult
from cockpit.shared.enums import (
    CommandSource,
    GuardDecisionOutcome,
    SessionTargetKind,
    TargetRiskLevel,
)


class FakeDockerAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, SessionTargetKind, str | None]] = []

    def restart_container(
        self,
        container_id: str,
        *,
        target_kind: SessionTargetKind = SessionTargetKind.LOCAL,
        target_ref: str | None = None,
    ) -> DockerActionResult:
        self.calls.append(("restart", container_id, target_kind, target_ref))
        return DockerActionResult(success=True, message=f"restarted {container_id}")

    def stop_container(
        self,
        container_id: str,
        *,
        target_kind: SessionTargetKind = SessionTargetKind.LOCAL,
        target_ref: str | None = None,
    ) -> DockerActionResult:
        self.calls.append(("stop", container_id, target_kind, target_ref))
        return DockerActionResult(success=True, message=f"stopped {container_id}")

    def remove_container(
        self,
        container_id: str,
        *,
        target_kind: SessionTargetKind = SessionTargetKind.LOCAL,
        target_ref: str | None = None,
    ) -> DockerActionResult:
        self.calls.append(("remove", container_id, target_kind, target_ref))
        return DockerActionResult(success=True, message=f"removed {container_id}")


class FakeGuardPolicyService:
    def __init__(self) -> None:
        self.calls = []

    def evaluate(self, context):
        self.calls.append(context)
        if not context.confirmed:
            return GuardDecision(
                command_id=context.command_id,
                action_kind=context.action_kind,
                component_kind=context.component_kind,
                target_risk=context.target_risk,
                outcome=GuardDecisionOutcome.REQUIRE_CONFIRMATION,
                explanation="confirmation required",
                requires_confirmation=True,
                confirmation_message="Confirm docker action.",
            )
        return GuardDecision(
            command_id=context.command_id,
            action_kind=context.action_kind,
            component_kind=context.component_kind,
            target_risk=context.target_risk,
            outcome=GuardDecisionOutcome.ALLOW,
            explanation="allowed",
        )


class FakeOperationsDiagnosticsService:
    def __init__(self) -> None:
        self.calls = []

    def record_operation(self, **payload):
        self.calls.append(payload)


class RestartDockerContainerHandlerTests(unittest.TestCase):
    def test_requires_confirmation_before_restart(self) -> None:
        adapter = FakeDockerAdapter()
        handler = RestartDockerContainerHandler(
            adapter,
            guard_policy_service=FakeGuardPolicyService(),
            operations_diagnostics_service=FakeOperationsDiagnosticsService(),
        )
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
        diagnostics = FakeOperationsDiagnosticsService()
        handler = RestartDockerContainerHandler(
            adapter,
            guard_policy_service=FakeGuardPolicyService(),
            operations_diagnostics_service=diagnostics,
        )
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
            [("restart", "abc123", SessionTargetKind.SSH, "dev@example.com")],
        )
        self.assertEqual(result.data["refresh_panel_id"], "docker-panel")
        self.assertEqual(result.data["restarted_container_id"], "abc123")
        self.assertEqual(len(diagnostics.calls), 1)

    def test_stops_selected_container_after_confirmation(self) -> None:
        adapter = FakeDockerAdapter()
        handler = StopDockerContainerHandler(
            adapter,
            guard_policy_service=FakeGuardPolicyService(),
            operations_diagnostics_service=FakeOperationsDiagnosticsService(),
        )
        command = Command(
            id="cmd_3",
            source=CommandSource.KEYBINDING,
            name="docker.stop",
            args={"confirmed": True},
            context={"selected_container_id": "abc123"},
        )

        result = handler(command)

        self.assertTrue(result.success)
        self.assertEqual(
            adapter.calls,
            [("stop", "abc123", SessionTargetKind.LOCAL, None)],
        )
        self.assertEqual(result.data["stopped_container_id"], "abc123")

    def test_removes_selected_container_after_confirmation(self) -> None:
        adapter = FakeDockerAdapter()
        handler = RemoveDockerContainerHandler(
            adapter,
            guard_policy_service=FakeGuardPolicyService(),
            operations_diagnostics_service=FakeOperationsDiagnosticsService(),
        )
        command = Command(
            id="cmd_4",
            source=CommandSource.KEYBINDING,
            name="docker.remove",
            args={"confirmed": True},
            context={"selected_container_id": "abc123"},
        )

        result = handler(command)

        self.assertTrue(result.success)
        self.assertEqual(
            adapter.calls,
            [("remove", "abc123", SessionTargetKind.LOCAL, None)],
        )
        self.assertEqual(result.data["removed_container_id"], "abc123")


if __name__ == "__main__":
    unittest.main()
