import unittest

from cockpit.application.handlers.base import ConfirmationRequiredError
from cockpit.application.handlers.cron_handlers import SetCronJobEnabledHandler
from cockpit.domain.commands.command import Command
from cockpit.infrastructure.cron.cron_adapter import CronWriteResult
from cockpit.shared.enums import CommandSource, SessionTargetKind


class FakeCronAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool, SessionTargetKind, str | None]] = []

    def set_job_enabled(
        self,
        command: str,
        *,
        enabled: bool,
        target_kind: SessionTargetKind = SessionTargetKind.LOCAL,
        target_ref: str | None = None,
    ) -> CronWriteResult:
        self.calls.append((command, enabled, target_kind, target_ref))
        state = "enabled" if enabled else "disabled"
        return CronWriteResult(success=True, message=f"{state} {command}")


class SetCronJobEnabledHandlerTests(unittest.TestCase):
    def test_requires_confirmation(self) -> None:
        adapter = FakeCronAdapter()
        handler = SetCronJobEnabledHandler(adapter, enabled=False)
        command = Command(
            id="cmd_1",
            source=CommandSource.SLASH,
            name="cron.disable",
            context={
                "selected_cron_command": "/usr/local/bin/backup",
                "workspace_name": "payments-prod",
                "workspace_root": "/srv/payments",
                "target_kind": SessionTargetKind.LOCAL.value,
            },
        )

        with self.assertRaises(ConfirmationRequiredError):
            handler(command)

        self.assertEqual(adapter.calls, [])

    def test_disables_selected_cron_job_after_confirmation(self) -> None:
        adapter = FakeCronAdapter()
        handler = SetCronJobEnabledHandler(adapter, enabled=False)
        command = Command(
            id="cmd_2",
            source=CommandSource.SLASH,
            name="cron.disable",
            args={"confirmed": True},
            context={
                "selected_cron_command": "/usr/local/bin/backup",
                "target_kind": SessionTargetKind.SSH.value,
                "target_ref": "dev@example.com",
            },
        )

        result = handler(command)

        self.assertTrue(result.success)
        self.assertEqual(
            adapter.calls,
            [("/usr/local/bin/backup", False, SessionTargetKind.SSH, "dev@example.com")],
        )
        self.assertEqual(result.data["refresh_panel_id"], "cron-panel")
