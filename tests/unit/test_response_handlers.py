import unittest

from cockpit.core.dispatch.handler_base import CommandContextError
from cockpit.ops.handlers.response_handlers import (
    DecideApprovalHandler,
    ExecuteResponseStepHandler,
    StartResponseRunHandler,
)
from cockpit.core.command import Command
from cockpit.core.enums import ApprovalDecisionKind, CommandSource


class _FakeResponseRunService:
    def __init__(self) -> None:
        self.started = []
        self.executed = []
        self.decisions = []

    def start_run(self, **kwargs):
        self.started.append(kwargs)
        return type("Run", (), {"id": "rrn-1"})()

    def execute_current_step(self, run_id, **kwargs):
        self.executed.append({"run_id": run_id, **kwargs})
        return type("Run", (), {"id": run_id, "summary": "Executed."})()

    def decide_approval(self, request_id, **kwargs):
        self.decisions.append({"request_id": request_id, **kwargs})
        return type("Run", (), {"id": "rrn-1", "summary": "Approved."})()


class ResponseHandlersTests(unittest.TestCase):
    def test_start_handler_requires_incident_and_runbook(self) -> None:
        service = _FakeResponseRunService()
        handler = StartResponseRunHandler(service)

        with self.assertRaises(CommandContextError):
            handler(
                Command(
                    id="cmd-1",
                    source=CommandSource.SLASH,
                    name="response.start",
                    args={"argv": ["inc-1"]},
                )
            )

        result = handler(
            Command(
                id="cmd-2",
                source=CommandSource.SLASH,
                name="response.start",
                args={"argv": ["inc-1", "docker-restart"]},
            )
        )
        self.assertTrue(result.success)
        self.assertEqual(service.started[0]["runbook_id"], "docker-restart")

    def test_execute_handler_uses_selected_run_from_context(self) -> None:
        service = _FakeResponseRunService()
        handler = ExecuteResponseStepHandler(service)

        result = handler(
            Command(
                id="cmd-3",
                source=CommandSource.KEYBINDING,
                name="response.execute",
                context={"selected_response_run_id": "rrn-2"},
            )
        )

        self.assertTrue(result.success)
        self.assertEqual(service.executed[0]["run_id"], "rrn-2")

    def test_decide_handler_uses_selected_approval_from_context(self) -> None:
        service = _FakeResponseRunService()
        handler = DecideApprovalHandler(
            service,
            decision=ApprovalDecisionKind.APPROVE,
        )

        result = handler(
            Command(
                id="cmd-4",
                source=CommandSource.KEYBINDING,
                name="approval.approve",
                context={"selected_approval_request_id": "apr-2"},
            )
        )

        self.assertTrue(result.success)
        self.assertEqual(service.decisions[0]["request_id"], "apr-2")
        self.assertEqual(service.decisions[0]["decision"], ApprovalDecisionKind.APPROVE)


if __name__ == "__main__":
    unittest.main()
