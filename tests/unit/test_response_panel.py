import unittest

from cockpit.application.dispatch.event_bus import EventBus

try:
    from cockpit.ui.panels.response_panel import ResponsePanel
except Exception:  # pragma: no cover - optional textual dependency
    ResponsePanel = None  # type: ignore[assignment]


class _FakeResponseRun:
    id = "rrn-1"
    incident_id = "inc-1"
    current_step_index = 0
    status = type("Status", (), {"value": "ready"})()
    summary = "Ready."

    def to_dict(self):
        return {
            "id": self.id,
            "incident_id": self.incident_id,
            "status": self.status.value,
            "current_step_index": self.current_step_index,
            "runbook_id": "docker-restart",
            "runbook_version": "1.0.0",
        }


class _FakeStepRun:
    id = "rsp-1"
    step_key = "restart"
    attempt_count = 1
    output_summary = "ok"
    status = type("Status", (), {"value": "succeeded"})()


class _FakeReview:
    id = "rvw-1"
    summary = "Follow-up open."
    status = type("Status", (), {"value": "open"})()
    closure_quality = type("Quality", (), {"value": "partial"})()


class _FakeDetail:
    response_run = _FakeResponseRun()
    step_runs = (_FakeStepRun(),)
    approvals = (
        {
            "request": {
                "id": "apr-1",
                "status": "pending",
                "required_approver_count": 1,
                "reason": "Need approval",
            },
            "decisions": [],
        },
    )
    artifacts = ()
    compensations = ()
    timeline = ()
    review = _FakeReview()


class _FakeResponseRunService:
    def list_active_runs(self, *, limit=8):
        del limit
        return [_FakeResponseRun()]

    def get_response_detail(self, run_id):
        del run_id
        return _FakeDetail()


class _FakePostIncidentService:
    pass


@unittest.skipIf(ResponsePanel is None, "textual is not installed in this environment")
class ResponsePanelTests(unittest.TestCase):
    def test_renders_response_summary_and_context(self) -> None:
        panel = ResponsePanel(
            event_bus=EventBus(),
            response_run_service=_FakeResponseRunService(),
            postincident_service=_FakePostIncidentService(),
        )
        panel.initialize(
            {
                "workspace_root": "/tmp/demo",
                "workspace_id": "wrk-1",
                "session_id": "ses-1",
            }
        )

        rendered = panel._render_text()

        self.assertIn("Active response runs:", rendered)
        self.assertIn("rrn-1", rendered)
        self.assertIn("Pending approvals:", rendered)
        self.assertIn("rvw-1", rendered)
        context = panel.command_context()
        self.assertEqual(context["selected_response_run_id"], "rrn-1")
        self.assertEqual(context["selected_approval_request_id"], "apr-1")
        self.assertEqual(context["selected_review_id"], "rvw-1")


if __name__ == "__main__":
    unittest.main()
