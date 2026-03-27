import unittest

from cockpit.core.dispatch.event_bus import EventBus

try:
    from cockpit.ui.panels.ops_panel import OpsPanel
except Exception:  # pragma: no cover - optional textual dependency
    OpsPanel = None  # type: ignore[assignment]


class _FakeSelfHealingService:
    def health_summary(self):
        class Summary:
            def to_dict(self):
                return {
                    "healthy": 3,
                    "degraded": 1,
                    "recovering": 1,
                    "failed": 0,
                    "quarantined": 1,
                }

        return Summary()

    def list_quarantined(self):
        class State:
            def to_dict(self):
                return {
                    "component_id": "ssh-tunnel:pg-main",
                    "quarantine_reason": "cooldown exhausted",
                    "status": "quarantined",
                }

        return [State()]


class _FakeIncidentService:
    def list_incidents(self, **kwargs):
        del kwargs

        class Incident:
            def to_dict(self):
                return {
                    "component_id": "plugin-host:notes",
                    "severity": "critical",
                    "summary": "plugin host quarantined",
                }

        return [Incident()]


class _FakeNotificationService:
    def summary(self):
        return {
            "counts": {
                "queued": 1,
                "delivering": 0,
                "delivered": 2,
                "suppressed": 1,
                "failed": 1,
            },
            "recent": [
                {
                    "status": "failed",
                    "title": "Tunnel unhealthy",
                    "summary": "delivery failed",
                }
            ],
            "recent_failures": [
                {
                    "channel_id": "slack-ops",
                    "attempt_number": 2,
                    "error_message": "timeout",
                }
            ],
        }


class _FakeWatchService:
    def list_states(self):
        class WatchState:
            class Outcome:
                value = "failure"

            last_outcome = Outcome()

            def to_dict(self):
                return {
                    "component_id": "watch:datasource:pg-main",
                    "last_status": "unreachable",
                }

        return [WatchState()]


class _FakeEscalationService:
    def list_active_engagements(self, *, limit=25):
        del limit

        class Engagement:
            def to_dict(self):
                return {
                    "id": "eng-1",
                    "incident_id": "inc-1",
                    "status": "active",
                    "current_step_index": 0,
                    "current_target_ref": "team-1",
                    "next_action_at": "2026-03-24T10:05:00+00:00",
                }

        return [Engagement()]


@unittest.skipIf(OpsPanel is None, "textual is not installed in this environment")
class OpsPanelTests(unittest.TestCase):
    def test_renders_operator_summary(self) -> None:
        panel = OpsPanel(
            event_bus=EventBus(),
            self_healing_service=_FakeSelfHealingService(),
            incident_service=_FakeIncidentService(),
            notification_service=_FakeNotificationService(),
            component_watch_service=_FakeWatchService(),
            escalation_service=_FakeEscalationService(),
        )

        panel.initialize(
            {
                "workspace_name": "Demo",
                "workspace_root": "/tmp/demo",
            }
        )

        rendered = panel._render_text()

        self.assertIn("Active incidents:", rendered)
        self.assertIn("plugin-host:notes", rendered)
        self.assertIn("Active engagements:", rendered)
        self.assertIn("eng-1", rendered)
        self.assertIn("Failed deliveries:", rendered)
        self.assertIn("watch:datasource:pg-main", rendered)
        self.assertEqual(panel.command_context()["selected_engagement_id"], "eng-1")


if __name__ == "__main__":
    unittest.main()
