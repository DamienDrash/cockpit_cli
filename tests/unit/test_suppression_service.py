from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cockpit.notifications.services.suppression_service import SuppressionService
from cockpit.notifications.models import NotificationCandidate
from cockpit.ops.repositories import (
    NotificationSuppressionRepository,
)
from cockpit.core.persistence.sqlite_store import SQLiteStore
from cockpit.core.enums import (
    ComponentKind,
    IncidentSeverity,
    NotificationEventClass,
    TargetRiskLevel,
)


class SuppressionServiceTests(unittest.TestCase):
    def test_suppresses_matching_candidate_inside_window(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            service = SuppressionService(
                repository=NotificationSuppressionRepository(store),
            )
            now = datetime(2026, 3, 24, 12, 0, tzinfo=UTC)
            service.save_rule(
                service.new_rule(
                    name="Maintenance",
                    reason="planned maintenance window",
                    starts_at=now - timedelta(minutes=5),
                    ends_at=now + timedelta(minutes=5),
                    event_classes=(NotificationEventClass.COMPONENT_DEGRADED,),
                    component_kinds=(ComponentKind.DATASOURCE_WATCH,),
                    severities=(IncidentSeverity.WARNING,),
                    risk_levels=(TargetRiskLevel.STAGE,),
                )
            )

            suppressed, reason = service.evaluate(
                NotificationCandidate(
                    event_class=NotificationEventClass.COMPONENT_DEGRADED,
                    severity=IncidentSeverity.WARNING,
                    risk_level=TargetRiskLevel.STAGE,
                    title="Datasource degraded",
                    summary="watch probe failed",
                    dedupe_key="watch:datasource:pg-main:degraded",
                    component_id="watch:datasource:pg-main",
                    component_kind=ComponentKind.DATASOURCE_WATCH,
                ),
                now=now,
            )

            self.assertTrue(suppressed)
            self.assertEqual(reason, "planned maintenance window")

    def test_does_not_suppress_outside_window(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            service = SuppressionService(
                repository=NotificationSuppressionRepository(store),
            )
            now = datetime(2026, 3, 24, 12, 0, tzinfo=UTC)
            service.save_rule(
                service.new_rule(
                    name="Expired",
                    reason="expired suppression",
                    starts_at=now - timedelta(minutes=10),
                    ends_at=now - timedelta(minutes=1),
                    event_classes=(NotificationEventClass.COMPONENT_DEGRADED,),
                )
            )

            suppressed, reason = service.evaluate(
                NotificationCandidate(
                    event_class=NotificationEventClass.COMPONENT_DEGRADED,
                    severity=IncidentSeverity.WARNING,
                    risk_level=TargetRiskLevel.DEV,
                    title="Transient degradation",
                    summary="probe failed once",
                    dedupe_key="watch:datasource:pg-main:degraded",
                ),
                now=now,
            )

            self.assertFalse(suppressed)
            self.assertIsNone(reason)


if __name__ == "__main__":
    unittest.main()
