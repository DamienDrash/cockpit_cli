import unittest
from datetime import UTC, datetime, timedelta

from cockpit.application.services.recovery_policy_service import RecoveryPolicyService
from cockpit.domain.models.health import ComponentHealthState, RecoveryAttempt
from cockpit.shared.enums import (
    ComponentKind,
    HealthStatus,
    RecoveryAttemptStatus,
    SessionTargetKind,
)


class RecoveryPolicyServiceTests(unittest.TestCase):
    def test_schedules_retry_with_exponential_backoff(self) -> None:
        service = RecoveryPolicyService()
        now = datetime(2026, 3, 23, tzinfo=UTC)

        evaluation = service.evaluate_failure(
            component_kind=ComponentKind.PTY_SESSION,
            state=None,
            recent_attempts=[],
            reason="pty exited unexpectedly",
            now=now,
        )

        self.assertTrue(evaluation.should_schedule_attempt)
        self.assertEqual(evaluation.attempt_number, 1)
        self.assertEqual(evaluation.backoff_seconds, 1)
        self.assertEqual(evaluation.next_status, HealthStatus.RECOVERING)

    def test_enters_cooldown_after_attempt_exhaustion(self) -> None:
        service = RecoveryPolicyService()
        now = datetime(2026, 3, 23, tzinfo=UTC)
        recent_attempts = [
            RecoveryAttempt(
                id=f"rcv-{index}",
                incident_id="inc-1",
                component_id="pty:work-panel",
                attempt_number=index,
                status=RecoveryAttemptStatus.FAILED,
                trigger="automatic",
                action="recover:pty_session",
                scheduled_for=now - timedelta(seconds=10 * index),
                finished_at=now - timedelta(seconds=10 * index),
            )
            for index in (1, 2, 3)
        ]
        state = ComponentHealthState(
            component_id="pty:work-panel",
            component_kind=ComponentKind.PTY_SESSION,
            display_name="PTY work-panel",
            status=HealthStatus.FAILED,
            target_kind=SessionTargetKind.LOCAL,
        )

        evaluation = service.evaluate_failure(
            component_kind=ComponentKind.PTY_SESSION,
            state=state,
            recent_attempts=recent_attempts,
            reason="pty exited unexpectedly",
            now=now,
        )

        self.assertTrue(evaluation.should_enter_cooldown)
        self.assertFalse(evaluation.should_schedule_attempt)
        self.assertEqual(evaluation.next_status, HealthStatus.FAILED)
        self.assertIsNotNone(evaluation.cooldown_until)

    def test_quarantines_repeated_failure_during_cooldown(self) -> None:
        service = RecoveryPolicyService()
        now = datetime(2026, 3, 23, tzinfo=UTC)
        state = ComponentHealthState(
            component_id="pty:work-panel",
            component_kind=ComponentKind.PTY_SESSION,
            display_name="PTY work-panel",
            status=HealthStatus.FAILED,
            target_kind=SessionTargetKind.LOCAL,
            cooldown_until=now + timedelta(seconds=30),
        )

        evaluation = service.evaluate_failure(
            component_kind=ComponentKind.PTY_SESSION,
            state=state,
            recent_attempts=[],
            reason="pty exited unexpectedly",
            now=now,
        )

        self.assertTrue(evaluation.should_quarantine)
        self.assertEqual(evaluation.next_status, HealthStatus.QUARANTINED)

    def test_marks_non_recoverable_reasons_as_quarantined(self) -> None:
        service = RecoveryPolicyService()
        now = datetime(2026, 3, 23, tzinfo=UTC)

        evaluation = service.evaluate_failure(
            component_kind=ComponentKind.PTY_SESSION,
            state=None,
            recent_attempts=[],
            reason="permission denied while spawning shell",
            now=now,
        )

        self.assertTrue(evaluation.should_quarantine)
        self.assertFalse(evaluation.should_schedule_attempt)

    def test_stage2_component_kinds_have_explicit_policies(self) -> None:
        service = RecoveryPolicyService()

        plugin_policy = service.policy_for(ComponentKind.PLUGIN_HOST)
        web_admin_policy = service.policy_for(ComponentKind.WEB_ADMIN)
        datasource_watch_policy = service.policy_for(ComponentKind.DATASOURCE_WATCH)
        docker_watch_policy = service.policy_for(ComponentKind.DOCKER_CONTAINER_WATCH)

        self.assertEqual(plugin_policy.max_attempts, 3)
        self.assertEqual(web_admin_policy.base_backoff_seconds, 1)
        self.assertEqual(datasource_watch_policy.cooldown_seconds, 180)
        self.assertEqual(docker_watch_policy.max_backoff_seconds, 30)


if __name__ == "__main__":
    unittest.main()
