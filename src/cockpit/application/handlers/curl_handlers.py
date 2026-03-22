"""HTTP request command handlers."""

from __future__ import annotations

from cockpit.application.handlers.base import (
    CommandContextError,
    ConfirmationRequiredError,
    DispatchResult,
)
from cockpit.domain.commands.command import Command
from cockpit.infrastructure.http.http_adapter import HttpAdapter
from cockpit.shared.enums import SessionTargetKind
from cockpit.shared.risk import classify_target_risk, risk_presentation


MUTATING_HTTP_METHODS = {"DELETE", "PATCH", "POST", "PUT"}


class SendHttpRequestHandler:
    """Execute a structured HTTP request for the Curl panel."""

    def __init__(self, http_adapter: HttpAdapter) -> None:
        self._http_adapter = http_adapter

    def __call__(self, command: Command) -> DispatchResult:
        method, url, body = self._resolve_request(command)
        headers = self._parse_headers(command.args)
        target_kind = self._target_kind(command.context.get("target_kind"))
        target_ref = self._optional_str(command.context.get("target_ref"))
        workspace_root = self._optional_str(command.context.get("workspace_root")) or ""
        workspace_name = self._optional_str(command.context.get("workspace_name")) or "workspace"

        if method in MUTATING_HTTP_METHODS and not self._is_confirmed(command):
            risk_level = classify_target_risk(
                target_kind=target_kind,
                target_ref=target_ref,
                workspace_name=workspace_name,
                workspace_root=workspace_root or url,
            )
            risk_label = risk_presentation(risk_level).label
            raise ConfirmationRequiredError(
                f"Confirm {method} request to {url} ({risk_label}).",
                payload={
                    "pending_command_name": command.name,
                    "pending_args": dict(command.args),
                    "pending_context": dict(command.context),
                    "confirmation_message": (
                        f"Send {method} request to {url}? "
                        "Press Enter/Y to confirm or Esc/N to cancel."
                    ),
                },
            )

        result = self._http_adapter.send_request(
            method,
            url,
            headers=headers,
            body=body,
        )
        return DispatchResult(
            success=result.success,
            message=result.message,
            data={
                "result_panel_id": "curl-panel",
                "result_payload": {
                    "response": result.to_dict(),
                    "draft_method": method,
                    "draft_url": url,
                    "draft_body": body or "",
                },
            },
        )

    def _resolve_request(self, command: Command) -> tuple[str, str, str | None]:
        argv = command.args.get("argv", [])
        if not isinstance(argv, list):
            argv = []
        draft_method = self._optional_str(command.context.get("draft_method")) or "GET"
        draft_url = self._optional_str(command.context.get("draft_url")) or ""
        method = (
            str(argv[0]).upper()
            if len(argv) >= 1 and isinstance(argv[0], str)
            else draft_method.upper()
        )
        url = (
            str(argv[1])
            if len(argv) >= 2 and isinstance(argv[1], str)
            else draft_url
        )
        if not url:
            raise CommandContextError("A request URL is required.")
        body = command.args.get("body")
        if isinstance(body, str):
            return method, url, body
        if len(argv) >= 3:
            return method, url, " ".join(str(token) for token in argv[2:])
        return method, url, self._optional_str(command.context.get("draft_body"))

    @staticmethod
    def _parse_headers(args: dict[str, object]) -> dict[str, str]:
        raw_headers = args.get("headers", args.get("header"))
        if not isinstance(raw_headers, str) or not raw_headers:
            return {}
        headers: dict[str, str] = {}
        for item in raw_headers.split("|"):
            if ":" not in item:
                continue
            key, value = item.split(":", 1)
            key = key.strip()
            value = value.strip()
            if key:
                headers[key] = value
        return headers

    @staticmethod
    def _is_confirmed(command: Command) -> bool:
        confirmed = command.args.get("confirmed")
        return bool(confirmed is True or confirmed == "true")

    @staticmethod
    def _optional_str(value: object) -> str | None:
        return value if isinstance(value, str) else None

    @staticmethod
    def _target_kind(value: object) -> SessionTargetKind:
        if isinstance(value, SessionTargetKind):
            return value
        if isinstance(value, str):
            try:
                return SessionTargetKind(value)
            except ValueError:
                return SessionTargetKind.LOCAL
        return SessionTargetKind.LOCAL
