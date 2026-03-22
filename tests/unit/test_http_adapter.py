import unittest
from unittest.mock import patch

from cockpit.infrastructure.http.http_adapter import HttpAdapter


class FakeHTTPResponse:
    def __init__(self, body: str, *, status: int = 200, reason: str = "OK") -> None:
        self.status = status
        self.reason = reason
        self.headers = {"content-type": "text/plain"}
        self._body = body.encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        del exc_type, exc, tb


class HttpAdapterTests(unittest.TestCase):
    def test_sends_request_and_returns_response_summary(self) -> None:
        adapter = HttpAdapter()

        with patch(
            "cockpit.infrastructure.http.http_adapter.urlopen",
            return_value=FakeHTTPResponse("hello world"),
        ):
            result = adapter.send_request("GET", "https://example.com")

        self.assertTrue(result.success)
        self.assertEqual(result.status_code, 200)
        self.assertIn("hello world", result.body_preview)


if __name__ == "__main__":
    unittest.main()
