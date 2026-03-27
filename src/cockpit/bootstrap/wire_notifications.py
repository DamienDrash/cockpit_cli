"""Notification context wiring."""

from __future__ import annotations

from typing import Any

from cockpit.core.dispatch.event_bus import EventBus
from cockpit.notifications.services.policy_service import (
    NotificationPolicyService,
)
from cockpit.notifications.services.notification_service import NotificationService
from cockpit.notifications.services.suppression_service import SuppressionService
from cockpit.notifications.adapters.ntfy_adapter import NtfyNotificationAdapter
from cockpit.notifications.adapters.slack_adapter import SlackNotificationAdapter
from cockpit.notifications.adapters.webhook_adapter import (
    WebhookNotificationAdapter,
)
from cockpit.ops.repositories import (
    NotificationChannelRepository,
    NotificationDeliveryRepository,
    NotificationRepository,
    NotificationRuleRepository,
    NotificationSuppressionRepository,
    OperationDiagnosticsRepository,
)
from cockpit.core.persistence.sqlite_store import SQLiteStore
from cockpit.datasources.adapters.secret_resolver import SecretResolver
from cockpit.core.enums import NotificationChannelKind


def wire_notifications(
    store: SQLiteStore,
    event_bus: EventBus,
    secret_resolver: SecretResolver,
) -> dict[str, Any]:
    """Wire notification and suppression components."""
    notification_channel_repository = NotificationChannelRepository(store)
    notification_rule_repository = NotificationRuleRepository(store)
    notification_suppression_repository = NotificationSuppressionRepository(store)
    notification_repository = NotificationRepository(store)
    notification_delivery_repository = NotificationDeliveryRepository(store)

    notification_policy_service = NotificationPolicyService(
        channel_repository=notification_channel_repository,
        rule_repository=notification_rule_repository,
    )
    suppression_service = SuppressionService(
        repository=notification_suppression_repository,
        event_bus=event_bus,
    )
    operation_diagnostics_repository = OperationDiagnosticsRepository(store)

    notification_service = NotificationService(
        event_bus=event_bus,
        notification_repository=notification_repository,
        delivery_repository=notification_delivery_repository,
        operation_diagnostics_repository=operation_diagnostics_repository,
        notification_policy_service=notification_policy_service,
        suppression_service=suppression_service,
        secret_resolver=secret_resolver,
        adapters={
            NotificationChannelKind.WEBHOOK: WebhookNotificationAdapter(),
            NotificationChannelKind.SLACK: SlackNotificationAdapter(),
            NotificationChannelKind.NTFY: NtfyNotificationAdapter(),
        },
    )

    return {
        "notification_service": notification_service,
        "notification_policy_service": notification_policy_service,
        "suppression_service": suppression_service,
    }
