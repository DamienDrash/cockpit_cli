import unittest

from cockpit.application.handlers.base import ConfirmationRequiredError
from cockpit.application.handlers.curl_handlers import SendHttpRequestHandler
from cockpit.domain.commands.command import Command
from cockpit.domain.models.policy import GuardDecision
from cockpit.infrastructure.http.http_adapter import HttpResponseSummary
from cockpit.shared.enums import CommandSource, GuardDecisionOutcome


class FakeHttpAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, str], str | None]] = []

    def send_request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: str | None = None,
        timeout_seconds: int = 10,
    ) -> HttpResponseSummary:
        del timeout_seconds
        self.calls.append((method, url, headers or {}, body))
        return HttpResponseSummary(
            success=True,
            method=method,
            url=url,
            status_code=200,
            reason="OK",
            duration_ms=12,
            headers=headers or {},
            body_preview="ok",
            message=f"{method} {url} -> 200",
        )


class FakeGuardPolicyService:
    def evaluate(self, context):
        if context.action_kind.value == "http_read":
            return GuardDecision(
                command_id=context.command_id,
                action_kind=context.action_kind,
                component_kind=context.component_kind,
                target_risk=context.target_risk,
                outcome=GuardDecisionOutcome.ALLOW,
                explanation="read-only",
            )
        if not context.confirmed:
            return GuardDecision(
                command_id=context.command_id,
                action_kind=context.action_kind,
                component_kind=context.component_kind,
                target_risk=context.target_risk,
                outcome=GuardDecisionOutcome.REQUIRE_CONFIRMATION,
                explanation="confirmation required",
                requires_confirmation=True,
                confirmation_message="Confirm HTTP request.",
            )
        return GuardDecision(
            command_id=context.command_id,
            action_kind=context.action_kind,
            component_kind=context.component_kind,
            target_risk=context.target_risk,
            outcome=GuardDecisionOutcome.ALLOW,
            explanation="allowed",
        )


class FakeOperationsDiagnosticsService:
    def __init__(self) -> None:
        self.calls = []

    def record_operation(self, **payload):
        self.calls.append(payload)


class SendHttpRequestHandlerTests(unittest.TestCase):
    def test_requires_confirmation_for_mutating_methods(self) -> None:
        adapter = FakeHttpAdapter()
        handler = SendHttpRequestHandler(
            adapter,
            guard_policy_service=FakeGuardPolicyService(),
            operations_diagnostics_service=FakeOperationsDiagnosticsService(),
        )
        command = Command(
            id="cmd_1",
            source=CommandSource.SLASH,
            name="curl.send",
            args={"argv": ["POST", "https://prod.example.com/api", "{}"]},
            context={"workspace_name": "payments-prod", "workspace_root": "/srv/payments"},
        )

        with self.assertRaises(ConfirmationRequiredError):
            handler(command)

        self.assertEqual(adapter.calls, [])

    def test_sends_request_and_routes_result_to_curl_panel(self) -> None:
        adapter = FakeHttpAdapter()
        diagnostics = FakeOperationsDiagnosticsService()
        handler = SendHttpRequestHandler(
            adapter,
            guard_policy_service=FakeGuardPolicyService(),
            operations_diagnostics_service=diagnostics,
        )
        command = Command(
            id="cmd_2",
            source=CommandSource.SLASH,
            name="curl.send",
            args={
                "argv": ["GET", "https://example.com/health"],
                "header": "Accept: application/json",
                "confirmed": True,
            },
            context={},
        )

        result = handler(command)

        self.assertTrue(result.success)
        self.assertEqual(
            adapter.calls,
            [("GET", "https://example.com/health", {"Accept": "application/json"}, None)],
        )
        self.assertEqual(result.data["result_panel_id"], "curl-panel")
        self.assertEqual(len(diagnostics.calls), 1)


if __name__ == "__main__":
    unittest.main()
