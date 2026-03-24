"""Generic webhook notification delivery."""

from __future__ import annotations

from cockpit.infrastructure.notifications.base import (
    NotificationAdapter,
    NotificationAdapterError,
    NotificationDeliveryPayload,
    NotificationDeliveryResult,
)


class WebhookNotificationAdapter(NotificationAdapter):
    """Deliver notifications to a generic JSON webhook."""

    kind = "webhook"

    def deliver(self, payload: NotificationDeliveryPayload) -> NotificationDeliveryResult:
        url = str(payload.channel.target.get("url", "")).strip()
        if not url:
            raise NotificationAdapterError("Webhook channels require a target.url.")
        headers = payload.channel.target.get("headers", {})
        if not isinstance(headers, dict):
            headers = {}
        timeout_seconds = int(payload.channel.timeout_seconds)
        return self._post_json(
            url,
            {
                "title": payload.title,
                "summary": payload.summary,
                "body": payload.body,
                "event_class": payload.notification.event_class.value,
                "severity": payload.notification.severity.value,
                "risk_level": payload.notification.risk_level.value,
                "metadata": payload.metadata,
            },
            headers={str(key): str(value) for key, value in headers.items()},
            timeout_seconds=timeout_seconds,
        )
