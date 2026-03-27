from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cockpit.notifications.services.policy_service import (
    NotificationPolicyService,
)
from cockpit.notifications.models import NotificationCandidate
from cockpit.ops.repositories import (
    NotificationChannelRepository,
    NotificationRuleRepository,
)
from cockpit.core.persistence.sqlite_store import SQLiteStore
from cockpit.core.enums import (
    ComponentKind,
    IncidentSeverity,
    NotificationChannelKind,
    NotificationEventClass,
    TargetRiskLevel,
)


class NotificationPolicyServiceTests(unittest.TestCase):
    def test_defaults_to_internal_route_when_no_specific_rule_matches(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            service = NotificationPolicyService(
                channel_repository=NotificationChannelRepository(store),
                rule_repository=NotificationRuleRepository(store),
            )

            decision = service.resolve(
                NotificationCandidate(
                    event_class=NotificationEventClass.INCIDENT_OPENED,
                    severity=IncidentSeverity.HIGH,
                    risk_level=TargetRiskLevel.STAGE,
                    title="Incident opened",
                    summary="ssh tunnel unhealthy",
                    dedupe_key="ssh-tunnel:main:incident_opened",
                    component_id="ssh-tunnel:main",
                    component_kind=ComponentKind.SSH_TUNNEL,
                )
            )

            self.assertEqual(decision.channel_ids, ("internal-default",))
            self.assertGreaterEqual(decision.dedupe_window_seconds, 300)

    def test_matches_specific_rule_and_preserves_priority_dedupe(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            service = NotificationPolicyService(
                channel_repository=NotificationChannelRepository(store),
                rule_repository=NotificationRuleRepository(store),
            )
            channel = service.new_channel(
                name="Slack Ops",
                kind=NotificationChannelKind.SLACK,
                target={"url": "https://hooks.slack.test"},
                risk_level=TargetRiskLevel.PROD,
            )
            service.save_channel(channel)
            service.save_rule(
                service.new_rule(
                    name="Prod quarantine route",
                    event_classes=(NotificationEventClass.COMPONENT_QUARANTINED,),
                    component_kinds=(ComponentKind.PLUGIN_HOST,),
                    severities=(IncidentSeverity.CRITICAL,),
                    risk_levels=(TargetRiskLevel.PROD,),
                    channel_ids=(channel.id,),
                    delivery_priority=10,
                    dedupe_window_seconds=900,
                )
            )

            decision = service.resolve(
                NotificationCandidate(
                    event_class=NotificationEventClass.COMPONENT_QUARANTINED,
                    severity=IncidentSeverity.CRITICAL,
                    risk_level=TargetRiskLevel.PROD,
                    title="Plugin host quarantined",
                    summary="plugin host crashed repeatedly",
                    dedupe_key="plugin-host:notes:quarantined",
                    component_id="plugin-host:notes",
                    component_kind=ComponentKind.PLUGIN_HOST,
                )
            )

            self.assertIn(channel.id, decision.channel_ids)
            self.assertIn("internal-default", decision.channel_ids)
            self.assertEqual(decision.dedupe_window_seconds, 900)


if __name__ == "__main__":
    unittest.main()
