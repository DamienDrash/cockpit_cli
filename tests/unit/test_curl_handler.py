import unittest

from cockpit.application.handlers.base import ConfirmationRequiredError
from cockpit.application.handlers.curl_handlers import SendHttpRequestHandler
from cockpit.domain.commands.command import Command
from cockpit.infrastructure.http.http_adapter import HttpResponseSummary
from cockpit.shared.enums import CommandSource


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


class SendHttpRequestHandlerTests(unittest.TestCase):
    def test_requires_confirmation_for_mutating_methods(self) -> None:
        adapter = FakeHttpAdapter()
        handler = SendHttpRequestHandler(adapter)
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
        handler = SendHttpRequestHandler(adapter)
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


if __name__ == "__main__":
    unittest.main()
