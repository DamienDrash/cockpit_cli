from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cockpit.core.dispatch.event_bus import EventBus
from cockpit.notifications.services.policy_service import (
    NotificationPolicyService,
)
from cockpit.notifications.services.notification_service import NotificationService
from cockpit.notifications.services.suppression_service import SuppressionService
from cockpit.ops.events.health import ComponentQuarantined, IncidentOpened
from cockpit.notifications.adapters.base import NotificationDeliveryResult
from cockpit.ops.repositories import (
    NotificationChannelRepository,
    NotificationDeliveryRepository,
    NotificationRepository,
    NotificationRuleRepository,
    NotificationSuppressionRepository,
    OperationDiagnosticsRepository,
)
from cockpit.core.persistence.sqlite_store import SQLiteStore
from cockpit.core.enums import (
    ComponentKind,
    IncidentSeverity,
    NotificationChannelKind,
    NotificationDeliveryStatus,
    NotificationEventClass,
)


class _PassThroughSecretResolver:
    def resolve_value(
        self,
        target: dict[str, object],
        secret_refs: dict[str, str],
    ) -> dict[str, object]:
        del secret_refs
        return dict(target)


class _FakeNotificationAdapter:
    def __init__(self, *, success: bool) -> None:
        self._success = success
        self.calls = 0

    def deliver(self, payload) -> NotificationDeliveryResult:
        self.calls += 1
        return NotificationDeliveryResult(
            success=self._success,
            message="ok" if self._success else "delivery failed",
            response_payload={"channel": payload.channel.id},
        )


class NotificationServiceTests(unittest.TestCase):
    def test_internal_notifications_are_persisted_and_marked_delivered(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            bus = EventBus()
            policy_service = NotificationPolicyService(
                channel_repository=NotificationChannelRepository(store),
                rule_repository=NotificationRuleRepository(store),
            )
            suppression_service = SuppressionService(
                repository=NotificationSuppressionRepository(store),
            )
            notification_repository = NotificationRepository(store)
            delivery_repository = NotificationDeliveryRepository(store)
            service = NotificationService(
                event_bus=bus,
                notification_repository=notification_repository,
                delivery_repository=delivery_repository,
                notification_policy_service=policy_service,
                suppression_service=suppression_service,
                secret_resolver=_PassThroughSecretResolver(),
                operation_diagnostics_repository=OperationDiagnosticsRepository(store),
                adapters={},
            )

            bus.publish(
                IncidentOpened(
                    incident_id="inc-1",
                    component_id="ssh-tunnel:pg-main",
                    component_kind=ComponentKind.SSH_TUNNEL,
                    severity=IncidentSeverity.HIGH,
                    title="Tunnel unhealthy",
                )
            )

            notifications = service.list_notifications()
            self.assertEqual(len(notifications), 1)
            self.assertEqual(notifications[0].status.value, "delivered")
            deliveries = delivery_repository.list_for_notification(notifications[0].id)
            self.assertEqual(len(deliveries), 1)
            self.assertEqual(deliveries[0].status, NotificationDeliveryStatus.SUCCEEDED)

    def test_suppressed_notification_records_suppressed_status(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            bus = EventBus()
            policy_service = NotificationPolicyService(
                channel_repository=NotificationChannelRepository(store),
                rule_repository=NotificationRuleRepository(store),
            )
            suppression_service = SuppressionService(
                repository=NotificationSuppressionRepository(store),
            )
            suppression_service.save_rule(
                suppression_service.new_rule(
                    name="Mute quarantines",
                    reason="maintenance window",
                    event_classes=(NotificationEventClass.COMPONENT_QUARANTINED,),
                )
            )
            service = NotificationService(
                event_bus=bus,
                notification_repository=NotificationRepository(store),
                delivery_repository=NotificationDeliveryRepository(store),
                notification_policy_service=policy_service,
                suppression_service=suppression_service,
                secret_resolver=_PassThroughSecretResolver(),
                operation_diagnostics_repository=OperationDiagnosticsRepository(store),
                adapters={},
            )

            bus.publish(
                ComponentQuarantined(
                    component_id="plugin-host:notes",
                    component_kind=ComponentKind.PLUGIN_HOST,
                    reason="host crashed repeatedly",
                )
            )

            notifications = service.list_notifications()
            self.assertEqual(len(notifications), 1)
            self.assertEqual(notifications[0].status.value, "suppressed")
            self.assertEqual(notifications[0].suppression_reason, "maintenance window")

    def test_failed_external_delivery_schedules_retry(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            bus = EventBus()
            policy_service = NotificationPolicyService(
                channel_repository=NotificationChannelRepository(store),
                rule_repository=NotificationRuleRepository(store),
            )
            webhook = policy_service.new_channel(
                name="Webhook",
                kind=NotificationChannelKind.WEBHOOK,
                target={"url": "https://hooks.example.invalid"},
                max_attempts=2,
                base_backoff_seconds=1,
                max_backoff_seconds=5,
            )
            policy_service.save_channel(webhook)
            policy_service.save_rule(
                policy_service.new_rule(
                    name="Route incidents to webhook",
                    event_classes=(NotificationEventClass.INCIDENT_OPENED,),
                    channel_ids=(webhook.id,),
                    delivery_priority=10,
                )
            )
            adapter = _FakeNotificationAdapter(success=False)
            delivery_repository = NotificationDeliveryRepository(store)
            service = NotificationService(
                event_bus=bus,
                notification_repository=NotificationRepository(store),
                delivery_repository=delivery_repository,
                notification_policy_service=policy_service,
                suppression_service=SuppressionService(
                    repository=NotificationSuppressionRepository(store),
                ),
                secret_resolver=_PassThroughSecretResolver(),
                operation_diagnostics_repository=OperationDiagnosticsRepository(store),
                adapters={NotificationChannelKind.WEBHOOK: adapter},
            )

            bus.publish(
                IncidentOpened(
                    incident_id="inc-1",
                    component_id="ssh-tunnel:pg-main",
                    component_kind=ComponentKind.SSH_TUNNEL,
                    severity=IncidentSeverity.HIGH,
                    title="Tunnel unhealthy",
                )
            )

            notifications = service.list_notifications()
            self.assertEqual(len(notifications), 1)
            self.assertEqual(notifications[0].status.value, "delivering")
            attempts = delivery_repository.list_for_notification(notifications[0].id)
            self.assertEqual(len(attempts), 3)
            webhook_attempts = [
                attempt for attempt in attempts if attempt.channel_id == webhook.id
            ]
            self.assertEqual(len(webhook_attempts), 2)
            self.assertEqual(
                webhook_attempts[0].status, NotificationDeliveryStatus.FAILED
            )
            self.assertEqual(
                webhook_attempts[1].status, NotificationDeliveryStatus.SCHEDULED
            )
            self.assertEqual(adapter.calls, 1)


if __name__ == "__main__":
    unittest.main()
