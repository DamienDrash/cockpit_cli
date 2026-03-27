"""Notification delivery adapter contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from cockpit.notifications.models import NotificationChannel, NotificationRecord


@dataclass(slots=True, frozen=True)
class NotificationDeliveryPayload:
    """Normalized payload passed to outbound notification adapters."""

    notification: NotificationRecord
    channel: NotificationChannel
    title: str
    summary: str
    body: str
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "notification": self.notification.to_dict(),
            "channel": self.channel.to_dict(),
            "title": self.title,
            "summary": self.summary,
            "body": self.body,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True, frozen=True)
class NotificationDeliveryResult:
    """Structured result returned by a delivery adapter."""

    success: bool
    message: str
    status_code: int | None = None
    response_payload: dict[str, object] = field(default_factory=dict)


class NotificationAdapterError(RuntimeError):
    """Raised when a notification adapter cannot deliver a payload."""


class NotificationAdapter:
    """Protocol-like base class for outbound delivery adapters."""

    kind = "base"

    def deliver(
        self, payload: NotificationDeliveryPayload
    ) -> NotificationDeliveryResult:
        raise NotImplementedError

    @staticmethod
    def _post_json(
        url: str,
        body: dict[str, object],
        *,
        headers: dict[str, str] | None = None,
        timeout_seconds: int = 5,
    ) -> NotificationDeliveryResult:
        request = Request(
            url=url,
            method="POST",
            headers={"content-type": "application/json", **(headers or {})},
            data=json.dumps(body, sort_keys=True).encode("utf-8"),
        )
        try:
            with urlopen(request, timeout=max(1, int(timeout_seconds))) as response:
                payload = response.read().decode("utf-8", errors="replace")
                return NotificationDeliveryResult(
                    success=True,
                    message=f"POST {url} -> {getattr(response, 'status', 200)}",
                    status_code=int(getattr(response, "status", 200)),
                    response_payload={"body": payload[:4000]},
                )
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            return NotificationDeliveryResult(
                success=False,
                message=f"POST {url} -> {exc.code}",
                status_code=int(exc.code),
                response_payload={"body": raw[:4000]},
            )
        except URLError as exc:
            raise NotificationAdapterError(str(exc.reason)) from exc
