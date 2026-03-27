import json
from urllib.error import HTTPError
from urllib.request import Request
import unittest

from cockpit.datasources.adapters.vault_client import VaultHttpClient, VaultHttpError


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def close(self) -> None:
        return None


class VaultHttpClientTests(unittest.TestCase):
    def test_login_approle_and_kv_read_use_expected_endpoints(self) -> None:
        requests: list[tuple[str, str, dict[str, str], str | None]] = []

        def requester(request: Request, *, context=None, timeout: float = 10.0):
            del context, timeout
            body = request.data.decode("utf-8") if request.data else None
            requests.append(
                (request.method, request.full_url, dict(request.header_items()), body)
            )
            if request.full_url.endswith("/v1/auth/approle/login"):
                return _FakeResponse(
                    {
                        "auth": {
                            "client_token": "s.token",
                            "accessor": "acc",
                            "renewable": True,
                            "lease_duration": 3600,
                        }
                    }
                )
            return _FakeResponse(
                {
                    "data": {
                        "data": {"password": "vault-secret"},
                        "metadata": {"version": 3},
                    }
                }
            )

        client = VaultHttpClient(
            address="https://vault.internal:8200",
            namespace="ops",
            requester=requester,
        )

        auth = client.login_approle(
            mount="approle", role_id="role-id", secret_id="secret-id"
        )
        payload = client.kv_read(mount="kv", path="apps/api", token=auth.token)

        self.assertEqual(auth.token, "s.token")
        self.assertEqual(payload["data"]["password"], "vault-secret")
        self.assertEqual(requests[0][0], "POST")
        self.assertIn("/v1/auth/approle/login", requests[0][1])
        self.assertIn("x-vault-namespace", {key.lower() for key in requests[0][2]})
        self.assertEqual(requests[1][0], "GET")
        self.assertIn("/v1/kv/data/apps/api", requests[1][1])

    def test_surfaces_vault_errors(self) -> None:
        def requester(request: Request, *, context=None, timeout: float = 10.0):
            del context, timeout
            raise HTTPError(
                request.full_url,
                400,
                "Bad Request",
                hdrs=None,
                fp=_FakeResponse({"errors": ["permission denied"]}),
            )

        client = VaultHttpClient(
            address="https://vault.internal:8200", requester=requester
        )

        with self.assertRaisesRegex(VaultHttpError, "permission denied"):
            client.health()


if __name__ == "__main__":
    unittest.main()
