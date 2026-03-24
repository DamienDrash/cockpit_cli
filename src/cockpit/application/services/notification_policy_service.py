"""Notification routing policy service."""

from __future__ import annotations

from cockpit.domain.models.notifications import (
    NotificationCandidate,
    NotificationChannel,
    NotificationRecord,
    NotificationRoutingDecision,
    NotificationRule,
)
from cockpit.infrastructure.persistence.ops_repositories import (
    NotificationChannelRepository,
    NotificationRuleRepository,
)
from cockpit.shared.enums import NotificationChannelKind, TargetRiskLevel
from cockpit.shared.utils import make_id, utc_now


class NotificationPolicyService:
    """Resolve notification routes from persisted rules and channels."""

    _DEFAULT_CHANNEL_ID = "internal-default"
    _DEFAULT_RULE_ID = "internal-default-rule"

    def __init__(
        self,
        *,
        channel_repository: NotificationChannelRepository,
        rule_repository: NotificationRuleRepository,
    ) -> None:
        self._channel_repository = channel_repository
        self._rule_repository = rule_repository

    def ensure_defaults(self) -> None:
        if self._channel_repository.get(self._DEFAULT_CHANNEL_ID) is None:
            self._channel_repository.save(
                NotificationChannel(
                    id=self._DEFAULT_CHANNEL_ID,
                    name="Internal",
                    kind=NotificationChannelKind.INTERNAL,
                    enabled=True,
                    target={},
                    risk_level=TargetRiskLevel.DEV,
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
            )
        if self._rule_repository.get(self._DEFAULT_RULE_ID) is None:
            self._rule_repository.save(
                NotificationRule(
                    id=self._DEFAULT_RULE_ID,
                    name="Default Internal Route",
                    enabled=True,
                    channel_ids=(self._DEFAULT_CHANNEL_ID,),
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
            )

    def list_channels(self, *, enabled_only: bool = False) -> list[NotificationChannel]:
        self.ensure_defaults()
        return self._channel_repository.list_all(enabled_only=enabled_only)

    def save_channel(self, channel: NotificationChannel) -> NotificationChannel:
        self._channel_repository.save(channel)
        return self._channel_repository.get(channel.id) or channel

    def delete_channel(self, channel_id: str) -> None:
        if channel_id == self._DEFAULT_CHANNEL_ID:
            raise ValueError("The default internal notification channel cannot be deleted.")
        self._channel_repository.delete(channel_id)

    def list_rules(self, *, enabled_only: bool = False) -> list[NotificationRule]:
        self.ensure_defaults()
        return self._rule_repository.list_all(enabled_only=enabled_only)

    def save_rule(self, rule: NotificationRule) -> NotificationRule:
        self._rule_repository.save(rule)
        return self._rule_repository.get(rule.id) or rule

    def delete_rule(self, rule_id: str) -> None:
        if rule_id == self._DEFAULT_RULE_ID:
            raise ValueError("The default internal routing rule cannot be deleted.")
        self._rule_repository.delete(rule_id)

    def resolve(self, candidate: NotificationCandidate) -> NotificationRoutingDecision:
        self.ensure_defaults()
        matching_rules = [
            rule
            for rule in self._rule_repository.list_all(enabled_only=True)
            if self._matches_rule(candidate, rule)
        ]
        if not matching_rules:
            channels = tuple(
                channel.id
                for channel in self._channel_repository.list_all(enabled_only=True)
                if channel.kind is NotificationChannelKind.INTERNAL
            )
            return NotificationRoutingDecision(
                candidate=candidate,
                channel_ids=channels or (self._DEFAULT_CHANNEL_ID,),
                dedupe_window_seconds=300,
                suppressed=False,
            )

        ordered = sorted(
            matching_rules,
            key=lambda item: (item.delivery_priority, item.updated_at or utc_now()),
        )
        channel_ids: list[str] = []
        dedupe_window_seconds = 300
        for rule in ordered:
            dedupe_window_seconds = max(dedupe_window_seconds, rule.dedupe_window_seconds)
            for channel_id in rule.channel_ids:
                if channel_id not in channel_ids:
                    channel_ids.append(channel_id)
        return NotificationRoutingDecision(
            candidate=candidate,
            channel_ids=tuple(channel_ids),
            dedupe_window_seconds=dedupe_window_seconds,
            suppressed=False,
        )

    def enabled_channels_for_ids(self, channel_ids: tuple[str, ...]) -> list[NotificationChannel]:
        enabled = {
            channel.id: channel for channel in self._channel_repository.list_all(enabled_only=True)
        }
        return [enabled[channel_id] for channel_id in channel_ids if channel_id in enabled]

    @staticmethod
    def new_rule(
        *,
        name: str,
        enabled: bool = True,
        event_classes: tuple = (),
        component_kinds: tuple = (),
        severities: tuple = (),
        risk_levels: tuple = (),
        incident_statuses: tuple = (),
        channel_ids: tuple[str, ...] = (),
        delivery_priority: int = 100,
        dedupe_window_seconds: int = 300,
    ) -> NotificationRule:
        now = utc_now()
        return NotificationRule(
            id=make_id("nrl"),
            name=name,
            enabled=enabled,
            event_classes=event_classes,
            component_kinds=component_kinds,
            severities=severities,
            risk_levels=risk_levels,
            incident_statuses=incident_statuses,
            channel_ids=channel_ids,
            delivery_priority=delivery_priority,
            dedupe_window_seconds=dedupe_window_seconds,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _matches_rule(candidate: NotificationCandidate, rule: NotificationRule) -> bool:
        if rule.event_classes and candidate.event_class not in rule.event_classes:
            return False
        if candidate.component_kind is not None and rule.component_kinds and candidate.component_kind not in rule.component_kinds:
            return False
        if rule.severities and candidate.severity not in rule.severities:
            return False
        if rule.risk_levels and candidate.risk_level not in rule.risk_levels:
            return False
        if candidate.incident_status is not None and rule.incident_statuses and candidate.incident_status not in rule.incident_statuses:
            return False
        return True

    @staticmethod
    def new_channel(
        *,
        name: str,
        kind: NotificationChannelKind,
        enabled: bool = True,
        target: dict[str, object] | None = None,
        secret_refs: dict[str, str] | None = None,
        timeout_seconds: int = 5,
        max_attempts: int = 3,
        base_backoff_seconds: int = 2,
        max_backoff_seconds: int = 30,
        risk_level: TargetRiskLevel = TargetRiskLevel.DEV,
    ) -> NotificationChannel:
        now = utc_now()
        return NotificationChannel(
            id=make_id("nch"),
            name=name,
            kind=kind,
            enabled=enabled,
            target=dict(target or {}),
            secret_refs=dict(secret_refs or {}),
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
            base_backoff_seconds=base_backoff_seconds,
            max_backoff_seconds=max_backoff_seconds,
            risk_level=risk_level,
            created_at=now,
            updated_at=now,
        )
