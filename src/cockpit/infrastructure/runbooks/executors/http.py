"""HTTP response step executor."""

from __future__ import annotations

from cockpit.infrastructure.http.http_adapter import HttpAdapter
from cockpit.infrastructure.runbooks.executors.base import (
    ExecutorArtifact,
    ExecutorContext,
    ExecutorResult,
)


class HttpStepExecutor:
    """Execute a structured HTTP step through the existing HTTP adapter."""

    def __init__(self, http_adapter: HttpAdapter) -> None:
        self._http_adapter = http_adapter

    def execute(self, context: ExecutorContext) -> ExecutorResult:
        method = str(context.resolved_config.get("method", "GET")).upper()
        url = str(context.resolved_config.get("url", ""))
        headers = context.resolved_config.get("headers", {})
        body = context.resolved_config.get("body")
        timeout_seconds = int(context.resolved_config.get("timeout_seconds", 10) or 10)
        response = self._http_adapter.send_request(
            method,
            url,
            headers=headers if isinstance(headers, dict) else {},
            body=str(body) if body is not None else None,
            timeout_seconds=timeout_seconds,
        )
        summary = response.message or f"{method} {url}"
        return ExecutorResult(
            success=response.success,
            summary=summary,
            payload=response.to_dict(),
            artifacts=(
                ExecutorArtifact(
                    kind="http_response",
                    label=f"{method} {url}",
                    summary=summary,
                    payload=response.to_dict(),
                ),
            ),
            error_message=None if response.success else summary,
        )
