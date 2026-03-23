"""HTTP request command handlers."""

from __future__ import annotations

from cockpit.application.handlers.base import (
    CommandContextError,
    ConfirmationRequiredError,
    DispatchResult,
    PolicyViolationError,
)
from cockpit.application.services.guard_policy_service import GuardPolicyService
from cockpit.application.services.operations_diagnostics_service import (
    OperationsDiagnosticsService,
)
from cockpit.domain.commands.command import Command
from cockpit.domain.models.policy import GuardContext
from cockpit.infrastructure.http.http_adapter import HttpAdapter
from cockpit.shared.enums import (
    ComponentKind,
    GuardActionKind,
    GuardDecisionOutcome,
    OperationFamily,
    SessionTargetKind,
)
from cockpit.shared.risk import classify_target_risk, risk_presentation


MUTATING_HTTP_METHODS = {"DELETE", "PATCH", "POST", "PUT"}


class SendHttpRequestHandler:
    """Execute a structured HTTP request for the Curl panel."""

    def __init__(
        self,
        http_adapter: HttpAdapter,
        *,
        guard_policy_service: GuardPolicyService,
        operations_diagnostics_service: OperationsDiagnosticsService,
    ) -> None:
        self._http_adapter = http_adapter
        self._guard_policy_service = guard_policy_service
        self._operations_diagnostics_service = operations_diagnostics_service

    def __call__(self, command: Command) -> DispatchResult:
        method, url, body = self._resolve_request(command)
        headers = self._parse_headers(command.args)
        target_kind = self._target_kind(command.context.get("target_kind"))
        target_ref = self._optional_str(command.context.get("target_ref"))
        workspace_root = self._optional_str(command.context.get("workspace_root")) or ""
        workspace_name = self._optional_str(command.context.get("workspace_name")) or "workspace"

        risk_level = classify_target_risk(
            target_kind=target_kind,
            target_ref=target_ref,
            workspace_name=workspace_name,
            workspace_root=workspace_root or url,
        )
        placeholders = self._extract_placeholders(url, body, headers)
        decision = self._guard_policy_service.evaluate(
            GuardContext(
                command_id=command.id,
                action_kind=self._guard_action_kind(method),
                component_kind=ComponentKind.HTTP_REQUEST,
                target_risk=risk_level,
                workspace_id=self._optional_str(command.context.get("workspace_id")),
                session_id=self._optional_str(command.context.get("session_id")),
                workspace_name=workspace_name,
                target_ref=target_ref,
                confirmed=self._is_confirmed(command),
                elevated_mode=self._is_elevated(command),
                subject_ref=url,
                description=f"{method} {url}",
                metadata={
                    "method": method,
                    "url": url,
                    "subject_ref": url,
                    "placeholder_names": placeholders,
                },
            )
        )
        if decision.outcome is GuardDecisionOutcome.REQUIRE_CONFIRMATION:
            risk_label = risk_presentation(risk_level).label
            raise ConfirmationRequiredError(
                f"Confirm {method} request to {url} ({risk_label}).",
                payload={
                    "pending_command_name": command.name,
                    "pending_args": dict(command.args),
                    "pending_context": dict(command.context),
                    "confirmation_message": (
                        f"{decision.confirmation_message or f'Send {method} request to {url}?'} "
                        "Press Enter/Y to confirm or Esc/N to cancel."
                    ),
                    "guard_decision": decision.to_dict(),
                },
            )
        if decision.outcome in {
            GuardDecisionOutcome.REQUIRE_ELEVATED_MODE,
            GuardDecisionOutcome.BLOCK,
        }:
            raise PolicyViolationError(
                decision.explanation,
                payload={"guard_decision": decision.to_dict()},
            )

        result = self._http_adapter.send_request(
            method,
            url,
            headers=headers,
            body=body,
        )
        self._operations_diagnostics_service.record_operation(
            family=OperationFamily.CURL,
            component_id=f"http:{self._subject_key(url)}",
            subject_ref=url,
            success=result.success,
            severity="info" if result.success else "high",
            summary=result.message or f"{method} {url}",
            payload={
                "method": method,
                "url": url,
                "status_code": result.status_code,
                "duration_ms": result.duration_ms,
                "reason": result.reason,
                "message": result.message,
                "risk_level": risk_level.value,
                "guard_outcome": decision.outcome.value,
                "placeholder_names": placeholders,
            },
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
    def _is_elevated(command: Command) -> bool:
        elevated = command.args.get("elevated_mode", command.args.get("elevated"))
        return bool(elevated is True or elevated == "true")

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

    @staticmethod
    def _guard_action_kind(method: str) -> GuardActionKind:
        normalized = method.upper()
        if normalized == "DELETE":
            return GuardActionKind.HTTP_DESTRUCTIVE
        if normalized in MUTATING_HTTP_METHODS:
            return GuardActionKind.HTTP_MUTATION
        return GuardActionKind.HTTP_READ

    @staticmethod
    def _extract_placeholders(
        url: str,
        body: str | None,
        headers: dict[str, str],
    ) -> list[str]:
        haystack = "\n".join([url, body or "", *headers.values()])
        placeholders: list[str] = []
        index = 0
        while True:
            start = haystack.find("${", index)
            if start < 0:
                break
            end = haystack.find("}", start + 2)
            if end < 0:
                break
            name = haystack[start + 2 : end].strip()
            if name and name not in placeholders:
                placeholders.append(name)
            index = end + 1
        return placeholders

    @staticmethod
    def _subject_key(url: str) -> str:
        return url.replace("://", "_").replace("/", "_")
