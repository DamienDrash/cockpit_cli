"""ntfy notification delivery."""

from __future__ import annotations

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from cockpit.notifications.adapters.base import (
    NotificationAdapter,
    NotificationAdapterError,
    NotificationDeliveryPayload,
    NotificationDeliveryResult,
)


class NtfyNotificationAdapter(NotificationAdapter):
    """Deliver notifications to an ntfy topic."""

    kind = "ntfy"

    def deliver(
        self, payload: NotificationDeliveryPayload
    ) -> NotificationDeliveryResult:
        topic_url = str(payload.channel.target.get("url", "")).strip()
        if not topic_url:
            raise NotificationAdapterError("ntfy channels require a target.url.")
        headers = {
            "Title": payload.title,
            "Tags": payload.notification.severity.value,
            "Priority": self._priority(payload.notification.severity.value),
            "X-Cockpit-Event": payload.notification.event_class.value,
        }
        auth_headers = payload.channel.target.get("headers", {})
        if isinstance(auth_headers, dict):
            headers.update(
                {str(key): str(value) for key, value in auth_headers.items()}
            )
        request = Request(
            url=topic_url,
            method="POST",
            headers=headers,
            data=payload.body.encode("utf-8"),
        )
        try:
            with urlopen(
                request, timeout=max(1, int(payload.channel.timeout_seconds))
            ) as response:
                body = response.read().decode("utf-8", errors="replace")
                return NotificationDeliveryResult(
                    success=True,
                    message=f"POST {topic_url} -> {getattr(response, 'status', 200)}",
                    status_code=int(getattr(response, "status", 200)),
                    response_payload={"body": body[:4000]},
                )
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            return NotificationDeliveryResult(
                success=False,
                message=f"POST {topic_url} -> {exc.code}",
                status_code=int(exc.code),
                response_payload={"body": raw[:4000]},
            )
        except URLError as exc:
            raise NotificationAdapterError(str(exc.reason)) from exc

    @staticmethod
    def _priority(severity: str) -> str:
        if severity == "critical":
            return "5"
        if severity == "high":
            return "4"
        if severity == "warning":
            return "3"
        return "2"
