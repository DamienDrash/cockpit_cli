"""Central notification routing, suppression, and delivery service."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import json

from cockpit.core.dispatch.event_bus import EventBus
from cockpit.notifications.services.policy_service import (
    NotificationPolicyService,
)
from cockpit.notifications.services.suppression_service import SuppressionService
from cockpit.ops.events.health import (
    ComponentHealthChanged,
    ComponentQuarantined,
    IncidentOpened,
    IncidentStatusChanged,
)
from cockpit.notifications.events import (
    NotificationDelivered,
    NotificationDeliveryFailed,
    NotificationDeliveryStarted,
    NotificationQueued,
    NotificationStatusChanged,
    NotificationSuppressed,
)
from cockpit.notifications.models import (
    NotificationCandidate,
    NotificationDeliveryAttempt,
    NotificationRecord,
)
from cockpit.notifications.adapters.base import (
    NotificationAdapter,
    NotificationAdapterError,
    NotificationDeliveryPayload,
)
from cockpit.ops.repositories import (
    NotificationDeliveryRepository,
    NotificationRepository,
    OperationDiagnosticsRepository,
)
from cockpit.datasources.adapters.secret_resolver import SecretResolver
from cockpit.core.enums import (
    ComponentKind,
    IncidentSeverity,
    IncidentStatus,
    NotificationChannelKind,
    NotificationDeliveryStatus,
    NotificationEventClass,
    NotificationStatus,
    OperationFamily,
    TargetRiskLevel,
)
from cockpit.core.utils import make_id, utc_now


class NotificationService:
    """Persist, route, suppress, and deliver operator notifications."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        notification_repository: NotificationRepository,
        delivery_repository: NotificationDeliveryRepository,
        notification_policy_service: NotificationPolicyService,
        suppression_service: SuppressionService,
        secret_resolver: SecretResolver,
        operation_diagnostics_repository: OperationDiagnosticsRepository,
        adapters: dict[NotificationChannelKind, NotificationAdapter],
    ) -> None:
        self._event_bus = event_bus
        self._notification_repository = notification_repository
        self._delivery_repository = delivery_repository
        self._notification_policy_service = notification_policy_service
        self._suppression_service = suppression_service
        self._secret_resolver = secret_resolver
        self._operation_diagnostics_repository = operation_diagnostics_repository
        self._adapters = dict(adapters)

        self._event_bus.subscribe(IncidentOpened, self._on_incident_opened)
        self._event_bus.subscribe(
            IncidentStatusChanged, self._on_incident_status_changed
        )
        self._event_bus.subscribe(ComponentQuarantined, self._on_component_quarantined)
        self._event_bus.subscribe(
            ComponentHealthChanged, self._on_component_health_changed
        )

    def list_notifications(
        self,
        *,
        limit: int = 50,
        statuses: tuple[NotificationStatus, ...] | None = None,
    ) -> list[NotificationRecord]:
        return self._notification_repository.list_recent(limit=limit, statuses=statuses)

    def list_failed_deliveries(
        self, *, limit: int = 25
    ) -> list[NotificationDeliveryAttempt]:
        return self._delivery_repository.list_recent_failures(limit=limit)

    def notification_detail(self, notification_id: str) -> dict[str, object] | None:
        notification = self._notification_repository.get(notification_id)
        if notification is None:
            return None
        return {
            "notification": notification.to_dict(),
            "deliveries": [
                attempt.to_dict()
                for attempt in self._delivery_repository.list_for_notification(
                    notification_id
                )
            ],
        }

    def summary(self) -> dict[str, object]:
        return {
            "counts": self._notification_repository.count_by_status(),
            "recent": [item.to_dict() for item in self.list_notifications(limit=10)],
            "recent_failures": [
                item.to_dict() for item in self.list_failed_deliveries(limit=10)
            ],
        }

    def run_due_deliveries(self) -> None:
        for attempt in self._delivery_repository.list_due_attempts():
            self._deliver_attempt(attempt)

    def send(self, candidate: NotificationCandidate) -> NotificationRecord | None:
        """Persist and route a notification candidate immediately."""

        return self._enqueue(candidate)

    def _on_incident_opened(self, event: IncidentOpened) -> None:
        self._enqueue(
            NotificationCandidate(
                event_class=NotificationEventClass.INCIDENT_OPENED,
                severity=event.severity,
                risk_level=self._risk_for_component(
                    event.component_kind,
                    component_id=event.component_id,
                ),
                title=event.title,
                summary=f"Incident opened for {event.component_id}.",
                dedupe_key=f"{event.component_id}:incident_opened",
                incident_id=event.incident_id,
                component_id=event.component_id,
                component_kind=event.component_kind,
                incident_status=IncidentStatus.OPEN,
                source_event_id=event.event_id,
                payload=event.to_dict(),
            )
        )

    def _on_incident_status_changed(self, event: IncidentStatusChanged) -> None:
        self._enqueue(
            NotificationCandidate(
                event_class=NotificationEventClass.INCIDENT_STATUS_CHANGED,
                severity=self._severity_for_incident_status(event.new_status),
                risk_level=self._risk_for_component(
                    event.component_kind,
                    component_id=event.component_id,
                ),
                title=f"Incident {event.new_status.value}",
                summary=event.message,
                dedupe_key=f"{event.component_id}:incident_status:{event.new_status.value}",
                incident_id=event.incident_id,
                component_id=event.component_id,
                component_kind=event.component_kind,
                incident_status=event.new_status,
                source_event_id=event.event_id,
                payload=event.to_dict(),
            )
        )

    def _on_component_quarantined(self, event: ComponentQuarantined) -> None:
        self._enqueue(
            NotificationCandidate(
                event_class=NotificationEventClass.COMPONENT_QUARANTINED,
                severity=IncidentSeverity.CRITICAL,
                risk_level=self._risk_for_component(
                    event.component_kind,
                    component_id=event.component_id,
                ),
                title=f"Component quarantined: {event.component_id}",
                summary=event.reason,
                dedupe_key=f"{event.component_id}:quarantined",
                component_id=event.component_id,
                component_kind=event.component_kind,
                source_event_id=event.event_id,
                payload=event.to_dict(),
            )
        )

    def _on_component_health_changed(self, event: ComponentHealthChanged) -> None:
        event_class = self._event_class_for_status(event.new_status)
        if event_class is None:
            return
        self._enqueue(
            NotificationCandidate(
                event_class=event_class,
                severity=self._severity_for_health_status(event.new_status),
                risk_level=self._risk_for_component(
                    event.component_kind,
                    component_id=event.component_id,
                ),
                title=f"Component {event.new_status.value}: {event.component_id}",
                summary=event.reason,
                dedupe_key=f"{event.component_id}:health:{event.new_status.value}",
                component_id=event.component_id,
                component_kind=event.component_kind,
                source_event_id=event.event_id,
                payload=event.to_dict(),
            )
        )

    def _enqueue(self, candidate: NotificationCandidate) -> NotificationRecord | None:
        routing = self._notification_policy_service.resolve(candidate)
        if self._notification_repository.recent_by_dedupe_key(
            candidate.dedupe_key,
            within_seconds=routing.dedupe_window_seconds,
        ):
            return None
        suppressed, suppression_reason = self._suppression_service.evaluate(candidate)
        notification = NotificationRecord(
            id=make_id("ntf"),
            event_class=candidate.event_class,
            severity=candidate.severity,
            risk_level=candidate.risk_level,
            title=candidate.title,
            summary=candidate.summary,
            status=NotificationStatus.SUPPRESSED
            if suppressed
            else NotificationStatus.QUEUED,
            dedupe_key=candidate.dedupe_key,
            incident_id=candidate.incident_id,
            component_id=candidate.component_id,
            component_kind=candidate.component_kind,
            incident_status=candidate.incident_status,
            source_event_id=candidate.source_event_id,
            suppression_reason=suppression_reason,
            payload=dict(candidate.payload),
            created_at=utc_now(),
        )
        self._notification_repository.save(notification)
        self._event_bus.publish(
            NotificationQueued(
                notification_id=notification.id,
                event_class=notification.event_class,
                severity=notification.severity,
                risk_level=notification.risk_level,
                suppressed=suppressed,
            )
        )
        if suppressed:
            self._event_bus.publish(
                NotificationSuppressed(
                    notification_id=notification.id,
                    event_class=notification.event_class,
                    reason=suppression_reason or "Suppressed by rule.",
                )
            )
            self._record_delivery_operation(
                notification=notification,
                channel_id="suppressed",
                success=True,
                summary=notification.suppression_reason or "notification suppressed",
                payload={"suppressed": True},
            )
            return notification

        routed_channel_ids = (
            candidate.forced_channel_ids
            if candidate.forced_channel_ids
            else routing.channel_ids
        )
        channels = self._notification_policy_service.enabled_channels_for_ids(
            routed_channel_ids
        )
        if not channels:
            notification.status = NotificationStatus.FAILED
            notification.suppression_reason = (
                "No enabled channels matched the routing decision."
            )
            self._notification_repository.save(notification)
            return notification
        for channel in channels:
            attempt = NotificationDeliveryAttempt(
                id=make_id("ndl"),
                notification_id=notification.id,
                channel_id=channel.id,
                attempt_number=1,
                status=NotificationDeliveryStatus.SCHEDULED,
                scheduled_for=utc_now(),
            )
            self._delivery_repository.save(attempt)
        self.run_due_deliveries()
        return notification

    def _deliver_attempt(self, attempt: NotificationDeliveryAttempt) -> None:
        notification = self._notification_repository.get(attempt.notification_id)
        if notification is None:
            return
        channels = {
            channel.id: channel
            for channel in self._notification_policy_service.list_channels(
                enabled_only=True
            )
        }
        channel = channels.get(attempt.channel_id)
        if channel is None:
            attempt.status = NotificationDeliveryStatus.FAILED
            attempt.finished_at = utc_now()
            attempt.error_class = "missing_channel"
            attempt.error_message = f"Channel '{attempt.channel_id}' is not enabled."
            self._delivery_repository.save(attempt)
            self._sync_notification_status(notification.id)
            return

        attempt.status = NotificationDeliveryStatus.RUNNING
        attempt.started_at = utc_now()
        self._delivery_repository.save(attempt)
        self._event_bus.publish(
            NotificationDeliveryStarted(
                delivery_id=attempt.id,
                notification_id=attempt.notification_id,
                channel_id=attempt.channel_id,
                channel_kind=channel.kind,
                attempt_number=attempt.attempt_number,
            )
        )

        if channel.kind is NotificationChannelKind.INTERNAL:
            attempt.status = NotificationDeliveryStatus.SUCCEEDED
            attempt.finished_at = utc_now()
            attempt.response_payload = {
                "message": "internal notification available in Cockpit views"
            }
            self._delivery_repository.save(attempt)
            self._event_bus.publish(
                NotificationDelivered(
                    delivery_id=attempt.id,
                    notification_id=attempt.notification_id,
                    channel_id=attempt.channel_id,
                    channel_kind=channel.kind,
                    status=attempt.status,
                )
            )
            self._record_delivery_operation(
                notification=notification,
                channel_id=channel.id,
                success=True,
                summary="internal notification stored",
                payload=attempt.response_payload,
            )
            self._sync_notification_status(notification.id)
            return

        try:
            resolved_target = self._secret_resolver.resolve_value(
                channel.target, channel.secret_refs
            )
            if not isinstance(resolved_target, dict):
                raise NotificationAdapterError(
                    "Resolved notification target must be a mapping."
                )
            resolved_channel = replace(channel, target=resolved_target)
            adapter = self._adapter_for(resolved_channel.kind)
            result = adapter.deliver(self._payload_for(notification, resolved_channel))
            attempt.finished_at = utc_now()
            attempt.response_payload = dict(result.response_payload)
            if result.success:
                attempt.status = NotificationDeliveryStatus.SUCCEEDED
                self._event_bus.publish(
                    NotificationDelivered(
                        delivery_id=attempt.id,
                        notification_id=attempt.notification_id,
                        channel_id=attempt.channel_id,
                        channel_kind=resolved_channel.kind,
                        status=attempt.status,
                    )
                )
            else:
                attempt.status = NotificationDeliveryStatus.FAILED
                attempt.error_class = "delivery_failed"
                attempt.error_message = result.message
                self._event_bus.publish(
                    NotificationDeliveryFailed(
                        delivery_id=attempt.id,
                        notification_id=attempt.notification_id,
                        channel_id=attempt.channel_id,
                        channel_kind=resolved_channel.kind,
                        status=attempt.status,
                        error_message=result.message,
                    )
                )
                self._schedule_retry_if_needed(attempt, resolved_channel)
            self._delivery_repository.save(attempt)
            self._record_delivery_operation(
                notification=notification,
                channel_id=resolved_channel.id,
                success=result.success,
                summary=result.message,
                payload=result.response_payload,
            )
        except Exception as exc:
            attempt.status = NotificationDeliveryStatus.FAILED
            attempt.finished_at = utc_now()
            attempt.error_class = exc.__class__.__name__
            attempt.error_message = str(exc)
            self._delivery_repository.save(attempt)
            self._event_bus.publish(
                NotificationDeliveryFailed(
                    delivery_id=attempt.id,
                    notification_id=attempt.notification_id,
                    channel_id=attempt.channel_id,
                    channel_kind=channel.kind,
                    status=attempt.status,
                    error_message=str(exc),
                )
            )
            self._schedule_retry_if_needed(attempt, channel)
            self._record_delivery_operation(
                notification=notification,
                channel_id=channel.id,
                success=False,
                summary=str(exc),
                payload={"error_class": exc.__class__.__name__},
            )
        self._sync_notification_status(notification.id)

    def _schedule_retry_if_needed(
        self,
        attempt: NotificationDeliveryAttempt,
        channel,
    ) -> None:
        if attempt.attempt_number >= int(channel.max_attempts):
            return
        backoff_seconds = min(
            int(channel.max_backoff_seconds),
            int(channel.base_backoff_seconds)
            * (2 ** max(0, attempt.attempt_number - 1)),
        )
        next_attempt = NotificationDeliveryAttempt(
            id=make_id("ndl"),
            notification_id=attempt.notification_id,
            channel_id=attempt.channel_id,
            attempt_number=attempt.attempt_number + 1,
            status=NotificationDeliveryStatus.SCHEDULED,
            scheduled_for=utc_now() + timedelta(seconds=max(1, backoff_seconds)),
        )
        self._delivery_repository.save(next_attempt)

    def _sync_notification_status(self, notification_id: str) -> None:
        notification = self._notification_repository.get(notification_id)
        if notification is None or notification.status is NotificationStatus.SUPPRESSED:
            return
        attempts = self._delivery_repository.list_for_notification(notification_id)
        previous_status = notification.status
        statuses = {attempt.status for attempt in attempts}
        if not attempts:
            notification.status = NotificationStatus.QUEUED
        elif statuses <= {
            NotificationDeliveryStatus.SUCCEEDED,
            NotificationDeliveryStatus.SUPPRESSED,
        }:
            notification.status = NotificationStatus.DELIVERED
        elif (
            NotificationDeliveryStatus.RUNNING in statuses
            or NotificationDeliveryStatus.SCHEDULED in statuses
        ):
            notification.status = NotificationStatus.DELIVERING
        elif statuses == {NotificationDeliveryStatus.FAILED}:
            notification.status = NotificationStatus.FAILED
        else:
            notification.status = NotificationStatus.DELIVERING
        self._notification_repository.save(notification)
        if notification.status is not previous_status:
            self._event_bus.publish(
                NotificationStatusChanged(
                    notification_id=notification.id,
                    previous_status=previous_status,
                    new_status=notification.status,
                    message=f"Notification {notification.id} is now {notification.status.value}.",
                )
            )

    def _payload_for(
        self, notification: NotificationRecord, channel
    ) -> NotificationDeliveryPayload:
        body = json.dumps(notification.payload, indent=2, sort_keys=True)
        return NotificationDeliveryPayload(
            notification=notification,
            channel=channel,
            title=notification.title,
            summary=notification.summary,
            body=body,
            metadata={
                "incident_id": notification.incident_id,
                "component_id": notification.component_id,
                "component_kind": notification.component_kind.value
                if notification.component_kind
                else None,
            },
        )

    def _record_delivery_operation(
        self,
        *,
        notification: NotificationRecord,
        channel_id: str,
        success: bool,
        summary: str,
        payload: dict[str, object],
    ) -> None:
        self._operation_diagnostics_repository.record(
            operation_family=OperationFamily.NOTIFICATION,
            component_id=f"notification:{notification.id}",
            subject_ref=channel_id,
            success=success,
            severity=notification.severity.value,
            summary=summary,
            payload={
                "notification_id": notification.id,
                "event_class": notification.event_class.value,
                **payload,
            },
        )

    def _adapter_for(self, kind: NotificationChannelKind) -> NotificationAdapter:
        adapter = self._adapters.get(kind)
        if adapter is None:
            raise NotificationAdapterError(
                f"No adapter is registered for channel kind '{kind.value}'."
            )
        return adapter

    @staticmethod
    def _event_class_for_status(status) -> NotificationEventClass | None:
        if status.value == "healthy":
            return NotificationEventClass.COMPONENT_RECOVERED
        if status.value in {"degraded", "failed", "recovering"}:
            return NotificationEventClass.COMPONENT_DEGRADED
        return None

    @staticmethod
    def _severity_for_health_status(status) -> IncidentSeverity:
        if status.value == "healthy":
            return IncidentSeverity.INFO
        if status.value == "failed":
            return IncidentSeverity.HIGH
        return IncidentSeverity.WARNING

    @staticmethod
    def _severity_for_incident_status(status: IncidentStatus) -> IncidentSeverity:
        if status is IncidentStatus.QUARANTINED:
            return IncidentSeverity.CRITICAL
        if status in {IncidentStatus.RESOLVED, IncidentStatus.CLOSED}:
            return IncidentSeverity.INFO
        if status is IncidentStatus.RECOVERING:
            return IncidentSeverity.WARNING
        return IncidentSeverity.HIGH

    @staticmethod
    def _risk_for_component(
        component_kind: ComponentKind,
        *,
        component_id: str | None = None,
    ) -> TargetRiskLevel:
        haystack = f"{component_kind.value} {component_id or ''}".lower()
        if "prod" in haystack:
            return TargetRiskLevel.PROD
        if "stage" in haystack or "ssh" in haystack:
            return TargetRiskLevel.STAGE
        return TargetRiskLevel.DEV
