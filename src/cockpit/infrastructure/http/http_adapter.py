"""HTTP request adapter for the Curl panel."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(slots=True, frozen=True)
class HttpResponseSummary:
    success: bool
    method: str
    url: str
    status_code: int | None = None
    reason: str | None = None
    duration_ms: int = 0
    headers: dict[str, str] = field(default_factory=dict)
    body_preview: str = ""
    message: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class HttpAdapter:
    """Execute structured HTTP requests."""

    def send_request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: str | None = None,
        timeout_seconds: int = 10,
    ) -> HttpResponseSummary:
        encoded_body = body.encode("utf-8") if body is not None else None
        request = Request(
            url=url,
            method=method.upper(),
            headers=headers or {},
            data=encoded_body,
        )
        started = monotonic()
        try:
            with urlopen(request, timeout=max(1, int(timeout_seconds))) as response:
                payload = response.read().decode("utf-8", errors="replace")
                duration_ms = int((monotonic() - started) * 1000)
                status_code = getattr(response, "status", None)
                reason = getattr(response, "reason", None)
                return HttpResponseSummary(
                    success=True,
                    method=method.upper(),
                    url=url,
                    status_code=int(status_code) if status_code is not None else None,
                    reason=str(reason) if reason is not None else None,
                    duration_ms=duration_ms,
                    headers=dict(response.headers.items()),
                    body_preview=payload[:4000],
                    message=f"{method.upper()} {url} -> {status_code}",
                )
        except HTTPError as exc:
            duration_ms = int((monotonic() - started) * 1000)
            payload = exc.read().decode("utf-8", errors="replace")
            return HttpResponseSummary(
                success=False,
                method=method.upper(),
                url=url,
                status_code=exc.code,
                reason=exc.reason,
                duration_ms=duration_ms,
                headers=dict(exc.headers.items()) if exc.headers else {},
                body_preview=payload[:4000],
                message=f"{method.upper()} {url} -> {exc.code}",
            )
        except URLError as exc:
            duration_ms = int((monotonic() - started) * 1000)
            return HttpResponseSummary(
                success=False,
                method=method.upper(),
                url=url,
                duration_ms=duration_ms,
                message=str(exc.reason),
            )
