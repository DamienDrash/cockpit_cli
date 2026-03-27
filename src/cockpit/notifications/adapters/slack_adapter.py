"""Slack webhook notification delivery."""

from __future__ import annotations

from cockpit.notifications.adapters.base import (
    NotificationAdapter,
    NotificationAdapterError,
    NotificationDeliveryPayload,
    NotificationDeliveryResult,
)


class SlackNotificationAdapter(NotificationAdapter):
    """Deliver notifications to Slack via incoming webhook."""

    kind = "slack"

    def deliver(
        self, payload: NotificationDeliveryPayload
    ) -> NotificationDeliveryResult:
        webhook_url = str(payload.channel.target.get("webhook_url", "")).strip()
        if not webhook_url:
            raise NotificationAdapterError(
                "Slack channels require a target.webhook_url."
            )
        channel_override = str(payload.channel.target.get("channel", "")).strip()
        text = f"*{payload.title}*\n{payload.summary}\n```{payload.body}```"
        body = {
            "text": text,
            "attachments": [
                {
                    "color": self._color(payload.notification.severity.value),
                    "fields": [
                        {
                            "title": "Event",
                            "value": payload.notification.event_class.value,
                            "short": True,
                        },
                        {
                            "title": "Risk",
                            "value": payload.notification.risk_level.value,
                            "short": True,
                        },
                    ],
                }
            ],
        }
        if channel_override:
            body["channel"] = channel_override
        return self._post_json(
            webhook_url,
            body,
            timeout_seconds=int(payload.channel.timeout_seconds),
        )

    @staticmethod
    def _color(severity: str) -> str:
        if severity == "critical":
            return "#c0392b"
        if severity == "high":
            return "#d35400"
        if severity == "warning":
            return "#f1c40f"
        return "#3498db"
