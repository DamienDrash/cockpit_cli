"""Notification suppression policy service."""

from __future__ import annotations

from datetime import datetime

from cockpit.core.dispatch.event_bus import EventBus
from cockpit.notifications.events import SuppressionRuleChanged
from cockpit.notifications.models import (
    NotificationCandidate,
    NotificationSuppressionRule,
)
from cockpit.ops.repositories import (
    NotificationSuppressionRepository,
)
from cockpit.core.utils import make_id, utc_now


class SuppressionService:
    """Evaluate and manage time-bounded notification suppressions."""

    def __init__(
        self,
        *,
        repository: NotificationSuppressionRepository,
        event_bus: EventBus | None = None,
    ) -> None:
        self._repository = repository
        self._event_bus = event_bus

    def list_rules(
        self, *, enabled_only: bool = False
    ) -> list[NotificationSuppressionRule]:
        return self._repository.list_all(enabled_only=enabled_only)

    def save_rule(
        self, rule: NotificationSuppressionRule
    ) -> NotificationSuppressionRule:
        self._repository.save(rule)
        if self._event_bus is not None:
            self._event_bus.publish(
                SuppressionRuleChanged(
                    suppression_rule_id=rule.id,
                    enabled=rule.enabled,
                    message=f"Suppression rule '{rule.name}' saved.",
                )
            )
        return rule

    def delete_rule(self, suppression_id: str) -> None:
        self._repository.delete(suppression_id)
        if self._event_bus is not None:
            self._event_bus.publish(
                SuppressionRuleChanged(
                    suppression_rule_id=suppression_id,
                    enabled=False,
                    message=f"Suppression rule '{suppression_id}' deleted.",
                )
            )

    def evaluate(
        self,
        candidate: NotificationCandidate,
        *,
        now: datetime | None = None,
    ) -> tuple[bool, str | None]:
        for rule in self._repository.list_active(now=now):
            if self._matches(candidate, rule):
                return True, rule.reason or f"Suppressed by rule {rule.name}."
        return False, None

    @staticmethod
    def new_rule(
        *,
        name: str,
        reason: str,
        enabled: bool = True,
        starts_at: datetime | None = None,
        ends_at: datetime | None = None,
        event_classes: tuple = (),
        component_kinds: tuple = (),
        severities: tuple = (),
        risk_levels: tuple = (),
        actor: str | None = None,
    ) -> NotificationSuppressionRule:
        now = utc_now()
        return NotificationSuppressionRule(
            id=make_id("sup"),
            name=name,
            enabled=enabled,
            reason=reason,
            starts_at=starts_at,
            ends_at=ends_at,
            event_classes=event_classes,
            component_kinds=component_kinds,
            severities=severities,
            risk_levels=risk_levels,
            actor=actor,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _matches(
        candidate: NotificationCandidate, rule: NotificationSuppressionRule
    ) -> bool:
        if rule.event_classes and candidate.event_class not in rule.event_classes:
            return False
        if (
            candidate.component_kind is not None
            and rule.component_kinds
            and candidate.component_kind not in rule.component_kinds
        ):
            return False
        if rule.severities and candidate.severity not in rule.severities:
            return False
        if rule.risk_levels and candidate.risk_level not in rule.risk_levels:
            return False
        return True
