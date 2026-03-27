"""Thin Vault HTTP client for auth, KV, transit, and lease operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import ssl
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(slots=True)
class VaultAuthResult:
    token: str
    token_accessor: str | None
    renewable: bool
    expires_at: datetime | None
    metadata: dict[str, object]


@dataclass(slots=True)
class VaultLeaseResult:
    lease_id: str
    renewable: bool
    expires_at: datetime | None
    data: dict[str, object]
    metadata: dict[str, object]


class VaultHttpError(RuntimeError):
    """Raised when Vault responds with an error."""


class VaultRequester(Protocol):
    def __call__(
        self,
        request: Request,
        *,
        context: ssl.SSLContext | None = None,
        timeout: float = 10.0,
    ) -> object: ...


class VaultHttpClient:
    """Minimal Vault HTTP wrapper with explicit typed operations."""

    def __init__(
        self,
        *,
        address: str,
        namespace: str | None = None,
        verify_tls: bool = True,
        ca_cert_path: str | None = None,
        requester: VaultRequester | None = None,
    ) -> None:
        self._address = address.rstrip("/")
        self._namespace = (
            namespace.strip()
            if isinstance(namespace, str) and namespace.strip()
            else None
        )
        self._verify_tls = verify_tls
        self._ca_cert_path = (
            ca_cert_path.strip()
            if isinstance(ca_cert_path, str) and ca_cert_path.strip()
            else None
        )
        self._requester = requester or self._default_requester

    def health(self) -> dict[str, object]:
        return self._request_json(
            "GET",
            "/v1/sys/health",
            query={"standbyok": "true", "perfstandbyok": "true"},
        )

    def login_token(self, token: str) -> VaultAuthResult:
        payload = self._request_json(
            "GET",
            "/v1/auth/token/lookup-self",
            token=token,
        )
        data = payload.get("data", {})
        if not isinstance(data, dict):
            raise VaultHttpError("Vault token lookup did not return token metadata.")
        ttl = int(data.get("ttl", 0) or 0)
        return VaultAuthResult(
            token=token,
            token_accessor=str(data.get("accessor"))
            if data.get("accessor") is not None
            else None,
            renewable=bool(data.get("renewable", False)),
            expires_at=_expires_at(ttl),
            metadata={str(key): value for key, value in data.items()},
        )

    def login_approle(
        self, *, mount: str, role_id: str, secret_id: str
    ) -> VaultAuthResult:
        payload = self._request_json(
            "POST",
            f"/v1/auth/{mount}/login",
            body={"role_id": role_id, "secret_id": secret_id},
        )
        return _auth_result_from_payload(payload)

    def login_jwt(self, *, mount: str, role: str, jwt: str) -> VaultAuthResult:
        payload = self._request_json(
            "POST",
            f"/v1/auth/{mount}/login",
            body={"role": role, "jwt": jwt},
        )
        return _auth_result_from_payload(payload)

    def kv_read(
        self,
        *,
        mount: str,
        path: str,
        token: str,
        version: int | None = None,
    ) -> dict[str, object]:
        query = (
            {"version": str(version)}
            if isinstance(version, int) and version > 0
            else None
        )
        payload = self._request_json(
            "GET",
            f"/v1/{mount}/data/{path}",
            token=token,
            query=query,
        )
        data = payload.get("data", {})
        if not isinstance(data, dict):
            raise VaultHttpError("Vault KV read did not return a data object.")
        secret_data = data.get("data", {})
        metadata = data.get("metadata", {})
        if not isinstance(secret_data, dict):
            secret_data = {}
        if not isinstance(metadata, dict):
            metadata = {}
        return {
            "data": secret_data,
            "metadata": metadata,
        }

    def kv_write(
        self,
        *,
        mount: str,
        path: str,
        token: str,
        data: dict[str, object],
        cas: int | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {"data": dict(data)}
        if isinstance(cas, int) and cas >= 0:
            payload["options"] = {"cas": cas}
        return self._request_json(
            "POST",
            f"/v1/{mount}/data/{path}",
            token=token,
            body=payload,
        )

    def dynamic_credentials(
        self,
        *,
        mount: str,
        role: str,
        token: str,
    ) -> VaultLeaseResult:
        payload = self._request_json(
            "GET",
            f"/v1/{mount}/creds/{role}",
            token=token,
        )
        return _lease_result_from_payload(
            payload,
            mount=mount,
            path=f"creds/{role}",
        )

    def transit_encrypt(
        self,
        *,
        mount: str,
        key_name: str,
        token: str,
        plaintext_b64: str,
    ) -> dict[str, object]:
        return self._request_json(
            "POST",
            f"/v1/{mount}/encrypt/{key_name}",
            token=token,
            body={"plaintext": plaintext_b64},
        )

    def transit_decrypt(
        self,
        *,
        mount: str,
        key_name: str,
        token: str,
        ciphertext: str,
    ) -> dict[str, object]:
        return self._request_json(
            "POST",
            f"/v1/{mount}/decrypt/{key_name}",
            token=token,
            body={"ciphertext": ciphertext},
        )

    def transit_sign(
        self,
        *,
        mount: str,
        key_name: str,
        token: str,
        input_b64: str,
    ) -> dict[str, object]:
        return self._request_json(
            "POST",
            f"/v1/{mount}/sign/{key_name}",
            token=token,
            body={"input": input_b64},
        )

    def transit_verify(
        self,
        *,
        mount: str,
        key_name: str,
        token: str,
        input_b64: str,
        signature: str,
    ) -> dict[str, object]:
        return self._request_json(
            "POST",
            f"/v1/{mount}/verify/{key_name}",
            token=token,
            body={"input": input_b64, "signature": signature},
        )

    def renew_self(
        self, *, token: str, increment_seconds: int | None = None
    ) -> VaultAuthResult:
        body: dict[str, object] = {}
        if isinstance(increment_seconds, int) and increment_seconds > 0:
            body["increment"] = increment_seconds
        payload = self._request_json(
            "POST",
            "/v1/auth/token/renew-self",
            token=token,
            body=body or None,
        )
        return _auth_result_from_payload(payload, default_token=token)

    def renew_lease(
        self,
        *,
        lease_id: str,
        token: str,
        increment_seconds: int | None = None,
    ) -> VaultLeaseResult:
        body: dict[str, object] = {"lease_id": lease_id}
        if isinstance(increment_seconds, int) and increment_seconds > 0:
            body["increment"] = increment_seconds
        payload = self._request_json(
            "PUT",
            "/v1/sys/leases/renew",
            token=token,
            body=body,
        )
        return _lease_result_from_payload(payload, mount="sys", path="leases/renew")

    def revoke_lease(self, *, lease_id: str, token: str) -> None:
        self._request_json(
            "PUT",
            "/v1/sys/leases/revoke",
            token=token,
            body={"lease_id": lease_id},
        )

    def revoke_self(self, *, token: str) -> None:
        self._request_json(
            "POST",
            "/v1/auth/token/revoke-self",
            token=token,
        )

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        body: dict[str, object] | None = None,
        query: dict[str, str] | None = None,
    ) -> dict[str, object]:
        url = f"{self._address}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(url, data=data, method=method.upper())
        request.add_header("Accept", "application/json")
        if body is not None:
            request.add_header("Content-Type", "application/json")
        if token:
            request.add_header("X-Vault-Token", token)
        if self._namespace:
            request.add_header("X-Vault-Namespace", self._namespace)
        context = self._ssl_context()
        try:
            response = self._requester(request, context=context, timeout=10.0)
            try:
                raw_body = response.read().decode("utf-8")
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
        except HTTPError as exc:
            try:
                error_body = exc.read().decode("utf-8", errors="replace")
            finally:
                close = getattr(exc, "close", None)
                if callable(close):
                    close()
            raise VaultHttpError(_error_message(error_body, exc.reason)) from exc
        except URLError as exc:
            raise VaultHttpError(str(exc.reason)) from exc
        payload = json.loads(raw_body) if raw_body else {}
        if not isinstance(payload, dict):
            raise VaultHttpError("Vault response must be a JSON object.")
        return payload

    def _ssl_context(self) -> ssl.SSLContext | None:
        if self._address.startswith("http://"):
            return None
        if not self._verify_tls:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            return context
        if self._ca_cert_path:
            return ssl.create_default_context(
                cafile=str(Path(self._ca_cert_path).expanduser())
            )
        return ssl.create_default_context()

    @staticmethod
    def _default_requester(
        request: Request,
        *,
        context: ssl.SSLContext | None = None,
        timeout: float = 10.0,
    ) -> object:
        return urlopen(request, context=context, timeout=timeout)


def _expires_at(ttl_seconds: int) -> datetime | None:
    if ttl_seconds <= 0:
        return None
    return datetime.now(UTC) + timedelta(seconds=ttl_seconds)


def _auth_result_from_payload(
    payload: dict[str, object],
    *,
    default_token: str | None = None,
) -> VaultAuthResult:
    auth = payload.get("auth", {})
    if not isinstance(auth, dict):
        raise VaultHttpError("Vault auth response did not return an auth object.")
    token = str(auth.get("client_token") or default_token or "").strip()
    if not token:
        raise VaultHttpError("Vault auth response did not contain a client token.")
    lease_duration = int(auth.get("lease_duration", 0) or 0)
    return VaultAuthResult(
        token=token,
        token_accessor=(
            str(auth.get("accessor")) if auth.get("accessor") is not None else None
        ),
        renewable=bool(auth.get("renewable", False)),
        expires_at=_expires_at(lease_duration),
        metadata={str(key): value for key, value in auth.items()},
    )


def _lease_result_from_payload(
    payload: dict[str, object],
    *,
    mount: str,
    path: str,
) -> VaultLeaseResult:
    data = payload.get("data", {})
    if not isinstance(data, dict):
        data = {}
    lease_duration = int(payload.get("lease_duration", 0) or 0)
    return VaultLeaseResult(
        lease_id=str(payload.get("lease_id", "")),
        renewable=bool(payload.get("renewable", False)),
        expires_at=_expires_at(lease_duration),
        data={str(key): value for key, value in data.items()},
        metadata={"mount": mount, "path": path},
    )


def _error_message(body: str, default: object) -> str:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body.strip() or str(default)
    if isinstance(payload, dict):
        errors = payload.get("errors", [])
        if isinstance(errors, list):
            message = "; ".join(str(item) for item in errors if str(item).strip())
            if message:
                return message
    return body.strip() or str(default)
