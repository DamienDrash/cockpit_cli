"""Local web admin HTTP server."""

from __future__ import annotations

from datetime import datetime
import json
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import mimetypes
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from cockpit.admin.web_admin_service import WebAdminService
from cockpit.infrastructure.web.layout_editor.assets import index_path, resolve_asset


def _page(title: str, body: str, *, flash: str | None = None) -> str:
    flash_html = ""
    if flash:
        flash_html = f"<div class='flash'>{escape(flash)}</div>"
    nav = (
        "<nav>"
        "<a href='/'>Home</a>"
        "<a href='/datasources'>Datasources</a>"
        "<a href='/secrets'>Secrets</a>"
        "<a href='/plugins'>Plugins</a>"
        "<a href='/layouts'>Layouts</a>"
        "<a href='/notifications'>Notifications</a>"
        "<a href='/watches'>Watches</a>"
        "<a href='/oncall'>On-Call</a>"
        "<a href='/engagements'>Engagements</a>"
        "<a href='/runbooks'>Runbooks</a>"
        "<a href='/responses'>Responses</a>"
        "<a href='/reviews'>Reviews</a>"
        "<a href='/incidents'>Incidents</a>"
        "<a href='/diagnostics'>Diagnostics</a>"
        "</nav>"
    )
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"<title>{escape(title)}</title>"
        "<style>"
        "body{font-family:system-ui,sans-serif;max-width:1100px;margin:0 auto;padding:2rem;background:#0f1419;color:#f5f7fa}"
        "nav{display:flex;gap:1rem;margin-bottom:1.5rem} nav a{color:#6dd6ff;text-decoration:none}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1rem}"
        ".card{background:#17212b;border:1px solid #2b3a47;border-radius:12px;padding:1rem}"
        "table{width:100%;border-collapse:collapse} th,td{padding:.5rem;border-bottom:1px solid #2b3a47;vertical-align:top}"
        "input,textarea,select,button{width:100%;padding:.6rem;border-radius:8px;border:1px solid #2b3a47;background:#101820;color:#f5f7fa}"
        "button{cursor:pointer;background:#12425d} .flash{margin:1rem 0;padding:.75rem 1rem;background:#16384c;border-left:4px solid #6dd6ff}"
        "form.inline{display:inline} form.inline button{width:auto;padding:.45rem .7rem}"
        "code,pre{background:#101820;padding:.2rem .35rem;border-radius:6px} pre{padding:1rem;overflow:auto}"
        "h1,h2,h3{margin:0 0 .75rem} .muted{color:#9fb4c7}"
        ".layout-preview-wrapper{margin:.75rem 0}"
        ".layout-preview{display:flex;gap:.5rem;min-height:5rem;padding:.75rem;background:#101820;border:1px dashed #2b3a47;border-radius:10px}"
        ".split-horizontal{flex-direction:row}"
        ".split-vertical{flex-direction:column}"
        ".layout-child{flex:1 1 0}"
        ".panel-node{height:100%;min-height:4rem;padding:.75rem;border:1px solid #2b3a47;border-radius:8px;background:#13202b}"
        "</style></head><body>"
        f"<h1>{escape(title)}</h1>{nav}{flash_html}{body}</body></html>"
    )


class LocalWebAdminServer:
    """Small local-only HTTP server for admin-plane workflows."""

    def __init__(
        self, service: WebAdminService, *, host: str = "127.0.0.1", port: int = 8765
    ) -> None:
        self._service = service
        self._host = host
        self._port = int(port)
        self._server: ThreadingHTTPServer | None = None

    def serve_forever(self) -> None:
        service = self._service

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                query = parse_qs(parsed.query)
                flash = query.get("message", [None])[0]
                service.save_last_page(parsed.path)
                if parsed.path.startswith("/api/"):
                    payload = _handle_api_get(service, parsed.path)
                    if payload is None:
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    self._json(payload)
                    return
                if parsed.path == "/layouts/editor" or parsed.path.startswith(
                    "/layouts/editor/"
                ):
                    asset_path = resolve_asset(parsed.path)
                    if asset_path is None and parsed.path in {
                        "/layouts/editor",
                        "/layouts/editor/",
                    }:
                        asset_path = index_path()
                    if asset_path is None or not asset_path.exists():
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    self._asset(asset_path)
                    return
                if parsed.path == "/":
                    self._html(
                        _page("Cockpit Web Admin", _home_body(service), flash=flash)
                    )
                    return
                if parsed.path == "/datasources":
                    self._html(
                        _page("Datasources", _datasource_body(service), flash=flash)
                    )
                    return
                if parsed.path == "/secrets":
                    self._html(_page("Secrets", _secret_body(service), flash=flash))
                    return
                if parsed.path == "/plugins":
                    self._html(_page("Plugins", _plugin_body(service), flash=flash))
                    return
                if parsed.path == "/layouts":
                    self._html(_page("Layouts", _layout_body(service), flash=flash))
                    return
                if parsed.path == "/notifications":
                    notification_id = query.get("notification_id", [None])[0]
                    self._html(
                        _page(
                            "Notifications",
                            _notifications_body(
                                service, notification_id=notification_id
                            ),
                            flash=flash,
                        )
                    )
                    return
                if parsed.path == "/watches":
                    self._html(_page("Watches", _watches_body(service), flash=flash))
                    return
                if parsed.path == "/oncall":
                    self._html(_page("On-Call", _oncall_body(service), flash=flash))
                    return
                if parsed.path == "/engagements":
                    engagement_id = query.get("engagement_id", [None])[0]
                    self._html(
                        _page(
                            "Engagements",
                            _engagements_body(service, engagement_id=engagement_id),
                            flash=flash,
                        )
                    )
                    return
                if parsed.path == "/runbooks":
                    runbook_id = query.get("runbook_id", [None])[0]
                    self._html(
                        _page(
                            "Runbooks",
                            _runbooks_body(service, runbook_id=runbook_id),
                            flash=flash,
                        )
                    )
                    return
                if parsed.path == "/responses":
                    response_run_id = query.get("response_run_id", [None])[0]
                    self._html(
                        _page(
                            "Responses",
                            _responses_body(service, response_run_id=response_run_id),
                            flash=flash,
                        )
                    )
                    return
                if parsed.path == "/reviews":
                    review_id = query.get("review_id", [None])[0]
                    self._html(
                        _page(
                            "Reviews",
                            _reviews_body(service, review_id=review_id),
                            flash=flash,
                        )
                    )
                    return
                if parsed.path == "/incidents":
                    incident_id = query.get("incident_id", [None])[0]
                    self._html(
                        _page(
                            "Incidents",
                            _incident_body(service, incident_id=incident_id),
                            flash=flash,
                        )
                    )
                    return
                if parsed.path == "/diagnostics":
                    self._html(
                        _page("Diagnostics", _diagnostics_body(service), flash=flash)
                    )
                    return
                self.send_error(HTTPStatus.NOT_FOUND)

            def do_POST(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                length = int(self.headers.get("Content-Length", "0") or 0)
                body = self.rfile.read(length).decode("utf-8")
                if parsed.path.startswith("/api/"):
                    try:
                        payload = json.loads(body) if body else {}
                        if not isinstance(payload, dict):
                            raise ValueError("JSON API payloads must be objects.")
                        response = _handle_api_post(service, parsed.path, payload)
                    except Exception as exc:
                        self._json(
                            {"ok": False, "error": str(exc)},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    self._json(response)
                    return
                form = {
                    key: values[-1] for key, values in parse_qs(body).items() if values
                }
                try:
                    redirect_path, message = _handle_post(service, parsed.path, form)
                except Exception as exc:
                    redirect_path, message = _redirect_target(parsed.path), str(exc)
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header(
                    "Location", f"{redirect_path}?{urlencode({'message': message})}"
                )
                self.end_headers()

            def log_message(self, _format: str, *_args: object) -> None:
                return

            def _html(self, body: str) -> None:
                encoded = body.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def _json(
                self, payload: dict[str, object], *, status: HTTPStatus = HTTPStatus.OK
            ) -> None:
                encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def _asset(self, asset_path: Path) -> None:
                payload = asset_path.read_bytes()
                content_type, _encoding = mimetypes.guess_type(str(asset_path))
                self.send_response(HTTPStatus.OK)
                self.send_header(
                    "Content-Type",
                    content_type or "application/octet-stream",
                )
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        with ThreadingHTTPServer((self._host, self._port), Handler) as server:
            self._server = server
            actual_host, actual_port = server.server_address[:2]
            print(f"Cockpit web admin available at http://{actual_host}:{actual_port}")
            try:
                server.serve_forever()
            finally:
                self._server = None

    def shutdown(self) -> None:
        if self._server is not None:
            self._server.shutdown()

    def listen_url(self) -> str | None:
        if self._server is None:
            return None
        actual_host, actual_port = self._server.server_address[:2]
        return f"http://{actual_host}:{actual_port}"


def _redirect_target(path: str) -> str:
    if path.startswith("/datasources"):
        return "/datasources"
    if path.startswith("/secrets"):
        return "/secrets"
    if path.startswith("/plugins"):
        return "/plugins"
    if path.startswith("/layouts"):
        return "/layouts"
    if path.startswith("/notifications"):
        return "/notifications"
    if path.startswith("/watches"):
        return "/watches"
    if path.startswith("/oncall"):
        return "/oncall"
    if path.startswith("/engagements"):
        return "/engagements"
    if path.startswith("/runbooks"):
        return "/runbooks"
    if path.startswith("/responses"):
        return "/responses"
    if path.startswith("/approvals"):
        return "/responses"
    if path.startswith("/reviews"):
        return "/reviews"
    if path.startswith("/incidents"):
        return "/incidents"
    if path.startswith("/diagnostics"):
        return "/diagnostics"
    return "/"


def _handle_post(
    service: WebAdminService, path: str, form: dict[str, str]
) -> tuple[str, str]:
    if path == "/datasources/create":
        profile = service.create_datasource(form)
        return "/datasources", f"Created datasource {profile.name}."
    if path == "/datasources/delete":
        profile_id = form.get("profile_id", "")
        service.delete_datasource(profile_id)
        return "/datasources", f"Deleted datasource {profile_id}."
    if path == "/datasources/execute":
        profile_id = form.get("profile_id", "")
        statement = form.get("statement", "")
        operation = form.get("operation", "query")
        result = service.execute_datasource(
            profile_id,
            statement,
            operation=operation,
            confirmed=form.get("confirmed", "0") == "1",
            elevated_mode=form.get("elevated_mode", "0") == "1",
        )
        return "/datasources", result.message or "Datasource command executed."
    if path == "/secrets/create":
        secret = service.create_secret(form)
        return "/secrets", f"Saved secret reference {secret.name}."
    if path == "/secrets/delete":
        name = form.get("name", "")
        purge_value = form.get("purge_value", "0") == "1"
        service.delete_secret(name, purge_value=purge_value)
        return "/secrets", f"Deleted secret reference {name}."
    if path == "/secrets/rotate":
        name = form.get("name", "")
        rotated = service.rotate_secret(name, secret_value=form.get("secret_value", ""))
        return "/secrets", f"Rotated secret reference {rotated.name}."
    if path == "/secrets/vault/profile/save":
        profile = service.save_vault_profile(form)
        return "/secrets", f"Saved Vault profile {profile.name}."
    if path == "/secrets/vault/profile/delete":
        profile_id = form.get("profile_id", "")
        revoke = form.get("revoke", "0") == "1"
        service.delete_vault_profile(profile_id, revoke=revoke)
        return "/secrets", f"Deleted Vault profile {profile_id}."
    if path == "/secrets/vault/login":
        session = service.login_vault_profile(form.get("profile_id", ""), form)
        return "/secrets", f"Logged into Vault profile {session.profile_id}."
    if path == "/secrets/vault/logout":
        profile_id = form.get("profile_id", "")
        revoke = form.get("revoke", "0") == "1"
        service.logout_vault_profile(profile_id, revoke=revoke)
        return "/secrets", f"Logged out Vault profile {profile_id}."
    if path == "/secrets/vault/health":
        profile_id = form.get("profile_id", "")
        payload = service.vault_profile_health(profile_id)
        health = payload.get("health", {})
        if isinstance(health, dict):
            status = health.get("initialized", health.get("sealed", "unknown"))
        else:
            status = "unknown"
        return "/secrets", f"Vault profile {profile_id} health checked ({status})."
    if path == "/secrets/vault/lease/renew":
        lease_id = form.get("lease_id", "")
        increment_raw = form.get("increment_seconds", "").strip()
        increment = int(increment_raw) if increment_raw.isdigit() else None
        lease = service.renew_vault_lease(lease_id, increment_seconds=increment)
        return "/secrets", f"Renewed lease {lease.lease_id}."
    if path == "/secrets/vault/lease/revoke":
        lease_id = form.get("lease_id", "")
        service.revoke_vault_lease(lease_id)
        return "/secrets", f"Revoked lease {lease_id}."
    if path == "/secrets/vault/transit":
        result = service.transit_operation(form)
        operation = str(result.get("operation", "transit"))
        detail = next(
            (str(value) for key, value in result.items() if key != "operation"), "ok"
        )
        return "/secrets", f"Transit {operation}: {detail}"
    if path == "/plugins/install":
        plugin = service.install_plugin(form)
        return "/plugins", f"Installed plugin {plugin.name}."
    if path == "/plugins/update":
        plugin = service.update_plugin(form.get("plugin_id", ""))
        return "/plugins", f"Updated plugin {plugin.name}."
    if path == "/plugins/toggle":
        enabled = form.get("enabled", "1") == "1"
        plugin = service.toggle_plugin(form.get("plugin_id", ""), enabled)
        return (
            "/plugins",
            f"{'Enabled' if plugin.enabled else 'Disabled'} plugin {plugin.name}.",
        )
    if path == "/plugins/pin":
        plugin = service.pin_plugin(
            form.get("plugin_id", ""), form.get("version_pin") or None
        )
        detail = plugin.version_pin or "none"
        return "/plugins", f"Pinned plugin {plugin.name} to {detail}."
    if path == "/plugins/remove":
        plugin_id = form.get("plugin_id", "")
        service.remove_plugin(plugin_id)
        return "/plugins", f"Removed plugin {plugin_id}."
    if path == "/notifications/channel/save":
        channel = service.save_notification_channel(form)
        return "/notifications", f"Saved notification channel {channel.name}."
    if path == "/notifications/channel/delete":
        channel_id = form.get("channel_id", "")
        service.delete_notification_channel(channel_id)
        return "/notifications", f"Deleted notification channel {channel_id}."
    if path == "/notifications/rule/save":
        rule = service.save_notification_rule(form)
        return "/notifications", f"Saved notification rule {rule.name}."
    if path == "/notifications/rule/delete":
        rule_id = form.get("rule_id", "")
        service.delete_notification_rule(rule_id)
        return "/notifications", f"Deleted notification rule {rule_id}."
    if path == "/notifications/suppression/save":
        rule = service.save_suppression_rule(form)
        return "/notifications", f"Saved suppression rule {rule.name}."
    if path == "/notifications/suppression/delete":
        suppression_id = form.get("suppression_id", "")
        service.delete_suppression_rule(suppression_id)
        return "/notifications", f"Deleted suppression rule {suppression_id}."
    if path == "/watches/datasource/save":
        watch = service.save_datasource_watch(form)
        return "/watches", f"Saved datasource watch {watch.name}."
    if path == "/watches/docker/save":
        watch = service.save_docker_watch(form)
        return "/watches", f"Saved docker watch {watch.name}."
    if path == "/watches/delete":
        watch_id = form.get("watch_id", "")
        service.delete_watch(watch_id)
        return "/watches", f"Deleted watch {watch_id}."
    if path == "/watches/probe":
        payload = service.probe_watch(form.get("watch_id", ""))
        return "/watches", f"Probed watch {payload.get('watch_id', '')}."
    if path == "/oncall/people/save":
        person = service.save_operator_person(form)
        return "/oncall", f"Saved operator {person.display_name}."
    if path == "/oncall/people/delete":
        person_id = form.get("person_id", "")
        service.delete_operator_person(person_id)
        return "/oncall", f"Deleted operator {person_id}."
    if path == "/oncall/teams/save":
        team = service.save_operator_team(form)
        return "/oncall", f"Saved team {team.name}."
    if path == "/oncall/teams/delete":
        team_id = form.get("team_id", "")
        service.delete_operator_team(team_id)
        return "/oncall", f"Deleted team {team_id}."
    if path == "/oncall/memberships/save":
        membership = service.save_team_membership(form)
        return "/oncall", f"Saved membership {membership.id}."
    if path == "/oncall/memberships/delete":
        membership_id = form.get("membership_id", "")
        service.delete_team_membership(membership_id)
        return "/oncall", f"Deleted membership {membership_id}."
    if path == "/oncall/bindings/save":
        binding = service.save_ownership_binding(form)
        return "/oncall", f"Saved ownership binding {binding.name}."
    if path == "/oncall/bindings/delete":
        binding_id = form.get("binding_id", "")
        service.delete_ownership_binding(binding_id)
        return "/oncall", f"Deleted ownership binding {binding_id}."
    if path == "/oncall/schedules/save":
        schedule = service.save_oncall_schedule(form)
        return "/oncall", f"Saved schedule {schedule.name}."
    if path == "/oncall/schedules/delete":
        schedule_id = form.get("schedule_id", "")
        service.delete_oncall_schedule(schedule_id)
        return "/oncall", f"Deleted schedule {schedule_id}."
    if path == "/oncall/rotations/save":
        rotation = service.save_rotation(form)
        return "/oncall", f"Saved rotation {rotation.name}."
    if path == "/oncall/rotations/delete":
        rotation_id = form.get("rotation_id", "")
        service.delete_rotation(rotation_id)
        return "/oncall", f"Deleted rotation {rotation_id}."
    if path == "/oncall/overrides/save":
        override = service.save_override(form)
        return "/oncall", f"Saved override {override.id}."
    if path == "/oncall/overrides/delete":
        override_id = form.get("override_id", "")
        service.delete_override(override_id)
        return "/oncall", f"Deleted override {override_id}."
    if path == "/oncall/policies/save":
        detail = service.save_escalation_policy(form)
        return "/oncall", f"Saved escalation policy {detail.policy.name}."
    if path == "/oncall/policies/delete":
        policy_id = form.get("policy_id", "")
        service.delete_escalation_policy(policy_id)
        return "/oncall", f"Deleted escalation policy {policy_id}."
    if path == "/layouts/clone":
        layout = service.clone_layout(
            form.get("source_layout_id", ""),
            form.get("target_layout_id", ""),
            form.get("name") or None,
        )
        return "/layouts", f"Saved layout variant {layout.id}."
    if path == "/layouts/toggle":
        layout = service.toggle_layout_tab(
            form.get("layout_id", ""), form.get("tab_id", "")
        )
        return "/layouts", f"Toggled layout tab in {layout.id}."
    if path == "/layouts/ratio":
        layout = service.set_layout_ratio(
            form.get("layout_id", ""),
            form.get("tab_id", ""),
            float(form.get("ratio", "0.5")),
        )
        return "/layouts", f"Updated split ratio in {layout.id}."
    if path == "/layouts/add-panel":
        layout = service.add_panel_to_layout(
            form.get("layout_id", ""),
            form.get("tab_id", ""),
            form.get("panel_id", ""),
            form.get("panel_type", ""),
        )
        return "/layouts", f"Added panel to {layout.id}."
    if path == "/layouts/remove-panel":
        layout = service.remove_panel_from_layout(
            form.get("layout_id", ""),
            form.get("tab_id", ""),
            form.get("panel_id", ""),
        )
        return "/layouts", f"Removed panel from {layout.id}."
    if path == "/layouts/replace-panel":
        layout = service.replace_panel_in_layout(
            form.get("layout_id", ""),
            form.get("tab_id", ""),
            form.get("existing_panel_id", ""),
            form.get("replacement_panel_id", ""),
            form.get("replacement_panel_type", ""),
        )
        return "/layouts", f"Replaced panel in {layout.id}."
    if path == "/layouts/move-panel":
        layout = service.move_panel_in_layout(
            form.get("layout_id", ""),
            form.get("tab_id", ""),
            form.get("panel_id", ""),
            form.get("direction", "next"),
        )
        return "/layouts", f"Moved panel in {layout.id}."
    if path == "/incidents/acknowledge":
        incident = service.acknowledge_incident(form.get("incident_id", ""))
        return "/incidents", f"Acknowledged incident {incident.id}."
    if path == "/incidents/close":
        incident = service.close_incident(form.get("incident_id", ""))
        return "/incidents", f"Closed incident {incident.id}."
    if path == "/incidents/reset-quarantine":
        component_id = form.get("component_id", "")
        service.reset_component_quarantine(component_id)
        return "/incidents", f"Reset quarantine for {component_id}."
    if path == "/incidents/retry":
        component_id = form.get("component_id", "")
        retried = service.retry_component_recovery(component_id)
        return "/incidents", (
            f"Queued retry for {component_id}."
            if retried
            else f"No component named {component_id}."
        )
    if path == "/engagements/ack":
        engagement = service.acknowledge_engagement(
            form.get("engagement_id", ""),
            actor=form.get("actor", "web-admin"),
        )
        return "/engagements", f"Acknowledged engagement {engagement.id}."
    if path == "/engagements/repage":
        engagement = service.repage_engagement(
            form.get("engagement_id", ""),
            actor=form.get("actor", "web-admin"),
        )
        return "/engagements", f"Triggered re-page for {engagement.id}."
    if path == "/engagements/handoff":
        engagement = service.handoff_engagement(
            form.get("engagement_id", ""),
            actor=form.get("actor", "web-admin"),
            target_kind=form.get("target_kind", "person"),
            target_ref=form.get("target_ref", ""),
        )
        return "/engagements", f"Handed off engagement {engagement.id}."
    if path == "/responses/start":
        response_run = service.start_response_run(
            incident_id=form.get("incident_id", ""),
            runbook_id=form.get("runbook_id", ""),
            actor=form.get("actor", "web-admin"),
            runbook_version=form.get("runbook_version") or None,
            engagement_id=form.get("engagement_id") or None,
        )
        return "/responses", f"Started response run {response_run.id}."
    if path == "/responses/execute":
        response_run = service.execute_response_run(
            form.get("response_run_id", ""),
            actor=form.get("actor", "web-admin"),
            confirmed=form.get("confirmed", "0") == "1",
            elevated_mode=form.get("elevated_mode", "0") == "1",
            notes=form.get("notes") or None,
        )
        return (
            "/responses",
            response_run.summary or f"Executed response run {response_run.id}.",
        )
    if path == "/responses/retry":
        response_run = service.retry_response_run(
            form.get("response_run_id", ""),
            actor=form.get("actor", "web-admin"),
            confirmed=form.get("confirmed", "0") == "1",
            elevated_mode=form.get("elevated_mode", "0") == "1",
            notes=form.get("notes") or None,
        )
        return (
            "/responses",
            response_run.summary or f"Retried response run {response_run.id}.",
        )
    if path == "/responses/abort":
        response_run = service.abort_response_run(
            form.get("response_run_id", ""),
            actor=form.get("actor", "web-admin"),
            reason=form.get("reason", "web-admin abort"),
        )
        return (
            "/responses",
            response_run.summary or f"Aborted response run {response_run.id}.",
        )
    if path == "/responses/compensate":
        response_run = service.compensate_response_run(
            form.get("response_run_id", ""),
            actor=form.get("actor", "web-admin"),
            confirmed=form.get("confirmed", "0") == "1",
            elevated_mode=form.get("elevated_mode", "0") == "1",
        )
        return (
            "/responses",
            response_run.summary or f"Compensated response run {response_run.id}.",
        )
    if path == "/approvals/decide":
        request_id = form.get("approval_request_id", "")
        decision = form.get("decision", "approve")
        service.decide_approval(
            request_id,
            approver_ref=form.get("approver_ref", "web-admin"),
            decision=decision,
            comment=form.get("comment") or None,
        )
        return "/responses", f"{decision.title()}d approval request {request_id}."
    if path == "/reviews/ensure":
        review = service.ensure_review(
            incident_id=form.get("incident_id", ""),
            response_run_id=form.get("response_run_id") or None,
            owner_ref=form.get("owner_ref") or None,
        )
        return "/reviews", f"Opened review {review.id}."
    if path == "/reviews/finding/add":
        finding = service.add_review_finding(
            form.get("review_id", ""),
            category=form.get("category", "process"),
            severity=form.get("severity", "medium"),
            title=form.get("title", ""),
            detail=form.get("detail", ""),
        )
        return "/reviews", f"Added finding {finding.id}."
    if path == "/reviews/action-item/add":
        action_item = service.add_review_action_item(
            form.get("review_id", ""),
            owner_ref=form.get("owner_ref") or None,
            title=form.get("title", ""),
            detail=form.get("detail", ""),
            due_at=_optional_datetime(form.get("due_at")),
        )
        return "/reviews", f"Added action item {action_item.id}."
    if path == "/reviews/action-item/status":
        action_item = service.set_review_action_item_status(
            form.get("action_item_id", ""),
            status=form.get("status", "open"),
        )
        return "/reviews", f"Updated action item {action_item.id}."
    if path == "/reviews/complete":
        review = service.complete_review(
            form.get("review_id", ""),
            summary=form.get("summary", ""),
            root_cause=form.get("root_cause", ""),
            closure_quality=form.get("closure_quality", "complete"),
        )
        return "/reviews", f"Completed review {review.id}."
    if path == "/diagnostics/close-tunnel":
        profile_id = form.get("profile_id", "")
        service.close_tunnel(profile_id)
        return "/diagnostics", f"Closed tunnel for {profile_id}."
    if path == "/diagnostics/reconnect-tunnel":
        profile_id = form.get("profile_id", "")
        service.reconnect_tunnel(profile_id)
        return "/diagnostics", f"Reconnected tunnel for {profile_id}."
    raise ValueError(f"Unknown admin action '{path}'.")


def _handle_api_get(service: WebAdminService, path: str) -> dict[str, object] | None:
    if path == "/api/layouts":
        return {
            "layouts": service.layout_summaries(),
            "panels": _panel_metadata(service),
        }
    if path == "/api/panels":
        return {
            "panels": _panel_metadata(service),
        }
    if path.startswith("/api/layouts/"):
        layout_id = path.removeprefix("/api/layouts/")
        if not layout_id:
            return None
        return {
            "layout": service.load_layout_document(layout_id),
            "panels": _panel_metadata(service),
        }
    return None


def _handle_api_post(
    service: WebAdminService, path: str, payload: dict[str, object]
) -> dict[str, object]:
    if path == "/api/layouts/validate":
        layout_payload = payload.get("layout", payload)
        if not isinstance(layout_payload, dict):
            raise ValueError("Layout validation requires a layout object.")
        result = service.validate_layout_document(layout_payload)
        return {
            "ok": bool(result.get("ok", False)),
            "errors": result.get("errors", []),
            "layout": result.get("layout", {}),
        }
    if path == "/api/layouts/save":
        layout_payload = payload.get("layout", payload)
        if not isinstance(layout_payload, dict):
            raise ValueError("Layout save requires a layout object.")
        layout = service.save_layout_document(layout_payload)
        return {
            "ok": True,
            "layout": layout.to_dict(),
        }
    if path == "/api/layouts/clone":
        source_layout_id = str(payload.get("source_layout_id", "")).strip()
        target_layout_id = str(payload.get("target_layout_id", "")).strip()
        name = str(payload.get("name", "")).strip() or None
        layout = service.clone_layout(source_layout_id, target_layout_id, name)
        return {
            "ok": True,
            "layout": layout.to_dict(),
        }
    raise ValueError(f"Unknown API action '{path}'.")


def _panel_metadata(service: WebAdminService) -> list[dict[str, str]]:
    return [
        {
            "panel_type": panel_type,
            "panel_id": panel_id,
            "display_name": display_name,
        }
        for panel_type, panel_id, display_name in service.available_panels()
    ]


def _home_body(service: WebAdminService) -> str:
    diagnostics = service.diagnostics()
    datasource_diag = diagnostics["datasources"]
    secret_diag = diagnostics["secrets"]
    plugin_diag = diagnostics["plugins"]
    health_diag = diagnostics["health"]
    active_incidents = diagnostics["active_incidents"]
    notification_diag = diagnostics["notifications"]
    watch_diag = diagnostics["watches"]
    oncall_diag = diagnostics.get("oncall", {})
    engagement_diag = oncall_diag.get("engagements", {})
    response_diag = diagnostics.get("response", {})
    reviews_diag = diagnostics.get("reviews", [])
    return (
        "<div class='grid'>"
        f"<div class='card'><h3>Datasources</h3><p>{escape(str(datasource_diag['total_profiles']))} total / {escape(str(datasource_diag['enabled_profiles']))} enabled</p></div>"
        f"<div class='card'><h3>Secrets</h3><p>{escape(str(secret_diag['total_entries']))} managed / {escape(str(secret_diag.get('rotated_entries', 0)))} rotated / vault profiles={escape(str(secret_diag.get('vault_profiles', 0)))} / active sessions={escape(str(secret_diag.get('active_vault_sessions', 0)))} / keyring={escape(str(secret_diag['keyring_available']))}</p></div>"
        f"<div class='card'><h3>Plugins</h3><p>{escape(str(plugin_diag['count']))} installed / {escape(str(plugin_diag['enabled']))} enabled</p></div>"
        f"<div class='card'><h3>Trusted Plugin Sources</h3><p>{escape(str(len(plugin_diag.get('trusted_sources', []))))} configured</p></div>"
        f"<div class='card'><h3>Panels</h3><p>{escape(', '.join(diagnostics['panel_types']))}</p></div>"
        f"<div class='card'><h3>Health</h3><p>healthy={escape(str(health_diag['healthy']))} recovering={escape(str(health_diag['recovering']))} failed={escape(str(health_diag['failed']))} quarantined={escape(str(health_diag['quarantined']))}</p></div>"
        f"<div class='card'><h3>Incidents</h3><p>{escape(str(len(active_incidents)))} active incident(s)</p></div>"
        f"<div class='card'><h3>Notifications</h3><p>queued={escape(str(notification_diag.get('counts', {}).get('queued', 0)))} failed={escape(str(notification_diag.get('counts', {}).get('failed', 0)))} suppressed={escape(str(notification_diag.get('counts', {}).get('suppressed', 0)))}</p></div>"
        f"<div class='card'><h3>Watches</h3><p>{escape(str(len(watch_diag.get('configs', []))))} configured / {escape(str(len(watch_diag.get('unhealthy', []))))} unhealthy</p></div>"
        f"<div class='card'><h3>On-Call</h3><p>{escape(str(len(oncall_diag.get('people', []))))} people / {escape(str(len(oncall_diag.get('teams', []))))} teams / {escape(str(len(oncall_diag.get('schedules', []))))} schedules</p></div>"
        f"<div class='card'><h3>Engagements</h3><p>{escape(str(engagement_diag.get('counts', {}).get('active', len(engagement_diag.get('active', []))))) if isinstance(engagement_diag.get('counts', {}), dict) else escape(str(len(engagement_diag.get('active', []))))} active / {escape(str(len(engagement_diag.get('blocked', []))))} blocked</p></div>"
        f"<div class='card'><h3>Response Runs</h3><p>{escape(str(len(response_diag.get('active_runs', []))))} active / {escape(str(len(response_diag.get('pending_approvals', []))))} approvals waiting</p></div>"
        f"<div class='card'><h3>Reviews</h3><p>{escape(str(len(reviews_diag)))} review record(s)</p></div>"
        "</div>"
        "<p class='muted'>Use the admin pages to manage datasource profiles, managed secret references, plugin installs, notification policy, health watches, layouts, incidents, response runs, and structured post-incident reviews.</p>"
    )


def _datasource_body(service: WebAdminService) -> str:
    profiles = service.list_datasources()
    last_result = service.last_datasource_result()
    rows = []
    secret_refs_example = escape(
        json.dumps(
            {
                "DB_USER": "env:APP_DB_USER",
                "DB_PASS": "keyring:cockpit:analytics-password",
            },
            indent=2,
        )
    )
    options_example = escape(
        json.dumps(
            {
                "connect_args": {"sslmode": "require"},
                "pool_pre_ping": True,
            },
            indent=2,
        )
    )
    for profile in profiles:
        inspect_result = service.inspect_datasource(profile.id)
        rows.append(
            "<tr>"
            f"<td><strong>{escape(profile.name)}</strong><br><span class='muted'>{escape(profile.id)}</span></td>"
            f"<td>{escape(profile.backend)}<br><span class='muted'>{escape(profile.connection_url or profile.target_ref or '(unset)')}</span></td>"
            f"<td>{escape(inspect_result.message or '')}<br><span class='muted'>risk={escape(profile.risk_level)} target={escape(profile.target_kind.value)}</span></td>"
            f"<td>{escape(', '.join(profile.capabilities))}<br><span class='muted'>{escape(str(len(profile.secret_refs)))} secret ref(s), {escape(str(len(profile.options)))} option(s)</span></td>"
            "<td>"
            f"<form class='inline' method='post' action='/datasources/delete'><input type='hidden' name='profile_id' value='{escape(profile.id)}'><button type='submit'>Delete</button></form>"
            "</td>"
            "</tr>"
        )
    empty_row = '<tr><td colspan="5">No datasource profiles saved.</td></tr>'
    return (
        "<div class='card'><h3>Create datasource</h3>"
        "<form id='create-datasource-form' method='post' action='/datasources/create'>"
        "<div class='grid'>"
        "<div><label>Name</label><input name='name' required></div>"
        "<div><label>Backend</label><select name='backend'>"
        "<option>sqlite</option><option>postgres</option><option>mysql</option><option>mariadb</option>"
        "<option>mssql</option><option>duckdb</option><option>bigquery</option><option>snowflake</option>"
        "<option>mongodb</option><option>redis</option><option>chromadb</option>"
        "</select></div>"
        "<div><label>Connection URL</label><input name='connection_url'></div>"
        "<div><label>Driver</label><input name='driver'></div>"
        "<div><label>Database</label><input name='database_name'></div>"
        "<div><label>Target kind</label><select name='target_kind'><option value='local'>local</option><option value='ssh'>ssh</option></select></div>"
        "<div><label>Target ref</label><input name='target_ref'></div>"
        "<div><label>Risk</label><select name='risk_level'><option>dev</option><option>stage</option><option>prod</option></select></div>"
        "<div><label>Tags</label><input name='tags' placeholder='analytics, read-only'></div>"
        "</div><p><button type='submit'>Save datasource</button></p></form></div>"
        "<div class='card'><h3>Advanced datasource fields</h3>"
        "<p class='muted'>Use <code>${NAME}</code> placeholders in connection URLs and resolve them from env, files, keyring, or literals.</p>"
        "<div class='grid'>"
        f"<div><label>Secret refs JSON</label><textarea name='secret_refs_json' form='create-datasource-form' rows='8' placeholder='{secret_refs_example}'></textarea></div>"
        f"<div><label>Options JSON</label><textarea name='options_json' form='create-datasource-form' rows='8' placeholder='{options_example}'></textarea></div>"
        "</div></div>"
        "<div class='card'><h3>Saved profiles</h3><table><thead><tr><th>Name</th><th>Backend</th><th>Status</th><th>Capabilities</th><th>Actions</th></tr></thead>"
        f"<tbody>{''.join(rows) if rows else empty_row}</tbody></table></div>"
        + _datasource_execute_card(profiles, last_result)
    )


def _datasource_execute_card(
    profiles: list[object],
    last_result: dict[str, object] | None,
) -> str:
    profile_options = "".join(
        f"<option value='{escape(getattr(profile, 'id', ''))}'>{escape(getattr(profile, 'name', getattr(profile, 'id', 'datasource')))} [{escape(getattr(profile, 'backend', ''))}]</option>"
        for profile in profiles
        if isinstance(getattr(profile, "id", None), str)
    )
    last_result_block = ""
    if isinstance(last_result, dict):
        payload = last_result.get("result", {})
        last_result_block = (
            "<div class='card'><h3>Last datasource result</h3>"
            f"<p class='muted'>profile={escape(str(last_result.get('profile_id', '')))}</p>"
            f"<pre>{escape(json.dumps(payload, indent=2, sort_keys=True))}</pre>"
            "</div>"
        )
    return (
        "<div class='card'><h3>Execute datasource statement</h3>"
        "<form method='post' action='/datasources/execute'>"
        "<div class='grid'>"
        f"<div><label>Profile</label><select name='profile_id'>{profile_options}</select></div>"
        "<div><label>Operation</label><select name='operation'><option value='query'>query</option><option value='mutate'>mutate</option></select></div>"
        "</div>"
        "<p><label>Statement</label><textarea name='statement' rows='10' placeholder='SELECT 1'></textarea></p>"
        "<p><label><input type='checkbox' name='confirmed' value='1'> Confirm mutating execution</label></p>"
        "<p><label><input type='checkbox' name='elevated_mode' value='1'> Elevated mode</label></p>"
        "<p class='muted'>Backend examples: SQL uses SQL text, MongoDB uses JSON payloads, Redis uses redis-cli style commands, Chroma uses JSON payloads.</p>"
        "<p><button type='submit'>Execute</button></p></form></div>" + last_result_block
    )


def _secret_body(service: WebAdminService) -> str:
    entries = service.list_secrets()
    profiles = service.list_vault_profiles()
    sessions = {
        session.profile_id: session for session in service.list_vault_sessions()
    }
    leases = service.list_vault_leases()
    rows = []
    for entry in entries:
        rotate_form = ""
        if entry.provider in {"keyring", "vault"}:
            rotate_form = (
                f"<form class='inline' method='post' action='/secrets/rotate'>"
                f"<input type='hidden' name='name' value='{escape(entry.name)}'>"
                "<input name='secret_value' type='password' placeholder='New value'>"
                "<button type='submit'>Rotate</button></form> "
            )
        rows.append(
            "<tr>"
            f"<td><strong>{escape(entry.name)}</strong><br><span class='muted'>{escape(entry.provider)}</span></td>"
            f"<td><code>{escape(_masked_secret_reference(entry.reference))}</code></td>"
            f"<td>{escape(entry.description or '')}<br><span class='muted'>rev={escape(str(entry.revision))} updated={escape(str(entry.updated_at or '(never)'))}</span></td>"
            "<td>"
            f"{rotate_form}"
            f"<form class='inline' method='post' action='/secrets/delete'><input type='hidden' name='name' value='{escape(entry.name)}'><button type='submit'>Delete</button></form> "
            f"<form class='inline' method='post' action='/secrets/delete'><input type='hidden' name='name' value='{escape(entry.name)}'><input type='hidden' name='purge_value' value='1'><button type='submit'>Delete + Purge</button></form>"
            "</td>"
            "</tr>"
        )
    profile_rows = []
    for profile in profiles:
        session = sessions.get(profile.id)
        session_text = "not authenticated"
        if session is not None:
            expiry = escape(str(session.expires_at or "(no ttl)"))
            session_text = (
                f"{escape(session.auth_type)} / {'cached' if session.cached else 'live'}"
                f"<br><span class='muted'>renewable={escape(str(session.renewable))} expires={expiry}</span>"
            )
        profile_rows.append(
            "<tr>"
            f"<td><strong>{escape(profile.name)}</strong><br><span class='muted'>{escape(profile.id)}</span></td>"
            f"<td>{escape(profile.address)}<br><span class='muted'>auth={escape(profile.auth_type)} mount={escape(profile.auth_mount or '(default)')} role={escape(profile.role_name or '(none)')}</span></td>"
            f"<td>{session_text}<br><span class='muted'>cache={escape(str(profile.allow_local_cache))} verify_tls={escape(str(profile.verify_tls))}</span></td>"
            "<td>"
            f"<form class='inline' method='post' action='/secrets/vault/health'><input type='hidden' name='profile_id' value='{escape(profile.id)}'><button type='submit'>Health</button></form> "
            f"<form class='inline' method='post' action='/secrets/vault/logout'><input type='hidden' name='profile_id' value='{escape(profile.id)}'><button type='submit'>Logout</button></form> "
            f"<form class='inline' method='post' action='/secrets/vault/profile/delete'><input type='hidden' name='profile_id' value='{escape(profile.id)}'><button type='submit'>Delete</button></form>"
            "</td>"
            "</tr>"
        )
    lease_rows = []
    for lease in leases:
        lease_rows.append(
            "<tr>"
            f"<td><strong>{escape(lease.lease_id)}</strong><br><span class='muted'>{escape(lease.profile_id)}</span></td>"
            f"<td>{escape(lease.mount)}/{escape(lease.path)}<br><span class='muted'>kind={escape(lease.source_kind)}</span></td>"
            f"<td>renewable={escape(str(lease.renewable))}<br><span class='muted'>expires={escape(str(lease.expires_at or '(none)'))}</span></td>"
            "<td>"
            f"<form class='inline' method='post' action='/secrets/vault/lease/renew'><input type='hidden' name='lease_id' value='{escape(lease.lease_id)}'><input name='increment_seconds' placeholder='seconds' style='width:8rem'><button type='submit'>Renew</button></form> "
            f"<form class='inline' method='post' action='/secrets/vault/lease/revoke'><input type='hidden' name='lease_id' value='{escape(lease.lease_id)}'><button type='submit'>Revoke</button></form>"
            "</td>"
            "</tr>"
        )
    return (
        "<div class='card'><h3>Vault profiles</h3>"
        "<form method='post' action='/secrets/vault/profile/save'>"
        "<div class='grid'>"
        "<div><label>Profile id</label><input name='profile_id' placeholder='ops-vault'></div>"
        "<div><label>Name</label><input name='name' required placeholder='Ops Vault'></div>"
        "<div><label>Address</label><input name='address' required placeholder='https://vault.internal:8200'></div>"
        "<div><label>Auth type</label><select name='auth_type'><option value='token'>token</option><option value='approle'>approle</option><option value='jwt'>jwt</option><option value='oidc'>oidc</option></select></div>"
        "<div><label>Auth mount</label><input name='auth_mount' placeholder='approle or jwt'></div>"
        "<div><label>Role name</label><input name='role_name' placeholder='used for jwt/oidc'></div>"
        "<div><label>Namespace</label><input name='namespace'></div>"
        "<div><label>CA cert path</label><input name='ca_cert_path' placeholder='/etc/ssl/certs/vault-ca.pem'></div>"
        "<div><label>Risk</label><select name='risk_level'><option>dev</option><option>stage</option><option>prod</option></select></div>"
        "<div><label>Tags</label><input name='tags' placeholder='ops, vault'></div>"
        "<div><label>Cache TTL seconds</label><input name='cache_ttl_seconds' value='3600'></div>"
        "<div><label>Description</label><input name='description' placeholder='Primary Vault cluster'></div>"
        "</div>"
        "<p><label><input type='checkbox' name='allow_local_cache' value='1'> Allow encrypted local session cache</label></p>"
        "<p><label><input type='checkbox' name='verify_tls' value='0'> Disable TLS verification</label></p>"
        "<p><button type='submit'>Save Vault profile</button></p></form></div>"
        "<div class='card'><h3>Vault login</h3>"
        "<form method='post' action='/secrets/vault/login'>"
        "<div class='grid'>"
        "<div><label>Profile id</label><input name='profile_id' required placeholder='ops-vault'></div>"
        "<div><label>Token</label><input name='token' type='password'></div>"
        "<div><label>AppRole role_id</label><input name='role_id'></div>"
        "<div><label>AppRole secret_id</label><input name='secret_id' type='password'></div>"
        "<div><label>JWT / OIDC token</label><input name='jwt' type='password'></div>"
        "</div><p><button type='submit'>Login</button></p></form></div>"
        "<div class='card'><h3>Vault transit</h3>"
        "<form method='post' action='/secrets/vault/transit'>"
        "<div class='grid'>"
        "<div><label>Profile id</label><input name='profile_id' required placeholder='ops-vault'></div>"
        "<div><label>Mount</label><input name='mount' value='transit'></div>"
        "<div><label>Key name</label><input name='key_name' required placeholder='app-key'></div>"
        "<div><label>Operation</label><select name='operation'><option value='encrypt'>encrypt</option><option value='decrypt'>decrypt</option><option value='sign'>sign</option><option value='verify'>verify</option></select></div>"
        "<div><label>Value</label><input name='value' required placeholder='plaintext or ciphertext'></div>"
        "<div><label>Signature</label><input name='signature' placeholder='only for verify'></div>"
        "</div><p><button type='submit'>Run transit operation</button></p></form></div>"
        "<div class='card'><h3>Create managed secret reference</h3>"
        "<form method='post' action='/secrets/create'>"
        "<div class='grid'>"
        "<div><label>Name</label><input name='name' required placeholder='analytics-db-pass'></div>"
        "<div><label>Provider</label><select name='provider'><option value='vault'>vault</option><option value='env'>env</option><option value='file'>file</option><option value='keyring'>keyring</option></select></div>"
        "<div><label>Description</label><input name='description' placeholder='Analytics DB password'></div>"
        "<div><label>Tags</label><input name='tags' placeholder='analytics, prod'></div>"
        "<div><label>Vault profile id</label><input name='vault_profile_id' placeholder='ops-vault'></div>"
        "<div><label>Vault kind</label><select name='vault_kind'><option value='kv'>kv</option><option value='dynamic'>dynamic</option></select></div>"
        "<div><label>Vault mount</label><input name='vault_mount' placeholder='kv or database'></div>"
        "<div><label>Vault path</label><input name='vault_path' placeholder='apps/api or fallback role'></div>"
        "<div><label>Vault role</label><input name='vault_role' placeholder='dynamic role'></div>"
        "<div><label>Vault field</label><input name='vault_field' placeholder='password'></div>"
        "<div><label>Vault version</label><input name='vault_version' placeholder='optional'></div>"
        "<div><label>Env var name</label><input name='env_name' placeholder='ANALYTICS_DB_PASS'></div>"
        "<div><label>File path</label><input name='file_path' placeholder='secrets/db-pass.txt'></div>"
        "<div><label>Keyring service</label><input name='keyring_service' placeholder='cockpit'></div>"
        "<div><label>Keyring username</label><input name='keyring_username' placeholder='analytics-db-pass'></div>"
        "</div>"
        "<p><label>Keyring value</label><input name='secret_value' type='password' placeholder='Only used for keyring entries'></p>"
        "<p class='muted'>Use these in datasource secret refs as <code>stored:secret-name</code>. Vault refs are the preferred primary path.</p>"
        "<p><button type='submit'>Save secret reference</button></p></form></div>"
        "<div class='card'><h3>Vault sessions</h3><table><thead><tr><th>Profile</th><th>Target</th><th>Status</th><th>Actions</th></tr></thead>"
        f"<tbody>{''.join(profile_rows) if profile_rows else '<tr><td colspan=4>No Vault profiles saved.</td></tr>'}</tbody></table></div>"
        "<div class='card'><h3>Vault leases</h3><table><thead><tr><th>Lease</th><th>Source</th><th>Status</th><th>Actions</th></tr></thead>"
        f"<tbody>{''.join(lease_rows) if lease_rows else '<tr><td colspan=4>No active Vault leases recorded.</td></tr>'}</tbody></table></div>"
        "<div class='card'><h3>Managed secrets</h3><table><thead><tr><th>Name</th><th>Reference</th><th>Description</th><th>Actions</th></tr></thead>"
        f"<tbody>{''.join(rows) if rows else '<tr><td colspan=4>No managed secrets saved.</td></tr>'}</tbody></table></div>"
    )


def _plugin_body(service: WebAdminService) -> str:
    plugins = service.list_plugins()
    rows = []
    for plugin in plugins:
        summary = plugin.manifest.get("summary", "")
        permissions = plugin.manifest.get("permissions", [])
        runtime_mode = str(plugin.manifest.get("runtime_mode", "hosted"))
        permissions_text = (
            ", ".join(str(item) for item in permissions if isinstance(item, str))
            or "(none)"
        )
        rows.append(
            "<tr>"
            f"<td><strong>{escape(plugin.name)}</strong><br><span class='muted'>{escape(plugin.module)}</span></td>"
            f"<td>{escape(plugin.requirement)}<br><span class='muted'>pin={escape(plugin.version_pin or '(none)')}</span></td>"
            f"<td>{escape(str(plugin.enabled))} / {escape(plugin.status)}</td>"
            f"<td>{escape(str(summary))}<br><span class='muted'>runtime={escape(runtime_mode)} compat={escape(str(plugin.manifest.get('compat_range', '*')))} integrity={escape(str(plugin.manifest.get('current_integrity_sha256', '(none)'))[:12])} perms={escape(permissions_text)}</span></td>"
            "<td>"
            f"<form class='inline' method='post' action='/plugins/update'><input type='hidden' name='plugin_id' value='{escape(plugin.id)}'><button type='submit'>Update</button></form> "
            f"<form class='inline' method='post' action='/plugins/toggle'><input type='hidden' name='plugin_id' value='{escape(plugin.id)}'><input type='hidden' name='enabled' value='{'0' if plugin.enabled else '1'}'><button type='submit'>{'Disable' if plugin.enabled else 'Enable'}</button></form> "
            f"<form class='inline' method='post' action='/plugins/remove'><input type='hidden' name='plugin_id' value='{escape(plugin.id)}'><button type='submit'>Remove</button></form>"
            "</td>"
            "</tr>"
        )
    diagnostics = service.diagnostics()
    plugin_diag = diagnostics["plugins"]
    trusted_sources = plugin_diag.get("trusted_sources", [])
    allowed_permissions = plugin_diag.get("allowed_permissions", [])
    host_running = plugin_diag.get("host_running", 0)
    host_failed = plugin_diag.get("host_failed", 0)
    registered = plugin_diag.get("registered", 0)
    host_payload = plugin_diag.get("hosts", {})
    empty_row = '<tr><td colspan="5">No plugins installed.</td></tr>'
    return (
        "<div class='card'><h3>Install plugin</h3>"
        "<form method='post' action='/plugins/install'>"
        "<div class='grid'>"
        "<div><label>Name</label><input name='name'></div>"
        "<div><label>Module</label><input name='module' required></div>"
        "<div><label>Requirement / repo</label><input name='requirement' required placeholder='package-name or /path/to/plugin or git+https://...'></div>"
        "<div><label>Version pin</label><input name='version_pin' placeholder='1.2.3'></div>"
        "<div><label>Source label</label><input name='source' placeholder='github.com/org/repo'></div>"
        "<div><label>Expected integrity SHA256</label><input name='integrity_sha256' placeholder='optional'></div>"
        "</div><p><button type='submit'>Install plugin</button></p></form></div>"
        "<div class='card'><h3>Plugin trust policy</h3>"
        f"<p class='muted'>Cockpit version: <code>{escape(str(plugin_diag.get('app_version', 'unknown')))}</code></p>"
        f"<pre>{escape(json.dumps(trusted_sources, indent=2))}</pre>"
        f"<p class='muted'>Allowed permissions</p><pre>{escape(json.dumps(allowed_permissions, indent=2))}</pre>"
        f"<p class='muted'>Runtime hosts: running={escape(str(host_running))} failed={escape(str(host_failed))} registered={escape(str(registered))}</p>"
        f"<pre>{escape(json.dumps(host_payload, indent=2, sort_keys=True))}</pre>"
        "</div>"
        "<div class='card'><h3>Installed plugins</h3><table><thead><tr><th>Plugin</th><th>Requirement</th><th>Status</th><th>Summary</th><th>Actions</th></tr></thead>"
        f"<tbody>{''.join(rows) if rows else empty_row}</tbody></table></div>"
    )


def _notifications_body(
    service: WebAdminService, *, notification_id: str | None
) -> str:
    summary = service.notification_summary()
    channels = service.list_notification_channels()
    rules = service.list_notification_rules()
    suppressions = service.list_suppression_rules()
    notifications = service.list_notifications()
    detail = service.notification_detail(notification_id) if notification_id else None

    channel_rows = []
    for channel in channels:
        channel_rows.append(
            "<tr>"
            f"<td><strong>{escape(channel.name)}</strong><br><span class='muted'>{escape(channel.id)}</span></td>"
            f"<td>{escape(channel.kind.value)}</td>"
            f"<td>{escape(str(channel.enabled))}<br><span class='muted'>risk={escape(channel.risk_level.value)} max_attempts={escape(str(channel.max_attempts))}</span></td>"
            f"<td><pre>{escape(json.dumps(channel.target, indent=2, sort_keys=True))}</pre></td>"
            "<td>"
            f"<form class='inline' method='post' action='/notifications/channel/delete'><input type='hidden' name='channel_id' value='{escape(channel.id)}'><button type='submit'>Delete</button></form>"
            "</td>"
            "</tr>"
        )

    rule_rows = []
    for rule in rules:
        rule_rows.append(
            "<tr>"
            f"<td><strong>{escape(rule.name)}</strong><br><span class='muted'>{escape(rule.id)}</span></td>"
            f"<td>{escape(', '.join(item.value for item in rule.event_classes) or '(all)')}</td>"
            f"<td>{escape(', '.join(rule.channel_ids) or '(none)')}</td>"
            f"<td>priority={escape(str(rule.delivery_priority))}<br><span class='muted'>dedupe={escape(str(rule.dedupe_window_seconds))}s enabled={escape(str(rule.enabled))}</span></td>"
            "<td>"
            f"<form class='inline' method='post' action='/notifications/rule/delete'><input type='hidden' name='rule_id' value='{escape(rule.id)}'><button type='submit'>Delete</button></form>"
            "</td>"
            "</tr>"
        )

    suppression_rows = []
    for rule in suppressions:
        suppression_rows.append(
            "<tr>"
            f"<td><strong>{escape(rule.name)}</strong><br><span class='muted'>{escape(rule.id)}</span></td>"
            f"<td>{escape(rule.reason)}</td>"
            f"<td>{escape(str(rule.starts_at or '(immediate)'))}<br><span class='muted'>{escape(str(rule.ends_at or '(open-ended)'))}</span></td>"
            f"<td>{escape(', '.join(item.value for item in rule.event_classes) or '(all)')}</td>"
            "<td>"
            f"<form class='inline' method='post' action='/notifications/suppression/delete'><input type='hidden' name='suppression_id' value='{escape(rule.id)}'><button type='submit'>Delete</button></form>"
            "</td>"
            "</tr>"
        )

    notification_rows = []
    for item in notifications:
        if not isinstance(item, dict):
            continue
        notification_rows.append(
            "<tr>"
            f"<td><strong>{escape(str(item.get('title', '')))}</strong><br><span class='muted'>{escape(str(item.get('id', '')))}</span></td>"
            f"<td>{escape(str(item.get('event_class', '')))}</td>"
            f"<td>{escape(str(item.get('severity', '')))}</td>"
            f"<td>{escape(str(item.get('status', '')))}</td>"
            f"<td>{escape(str(item.get('summary', '')))}</td>"
            "<td>"
            f"<form class='inline' method='get' action='/notifications'><input type='hidden' name='notification_id' value='{escape(str(item.get('id', '')))}'><button type='submit'>View</button></form>"
            "</td>"
            "</tr>"
        )

    detail_block = (
        "<div class='card'><h3>Notification Detail</h3>"
        f"<pre>{escape(json.dumps(detail or {}, indent=2, sort_keys=True))}</pre>"
        "</div>"
        if detail is not None
        else "<div class='card'><h3>Notification Detail</h3><p class='muted'>Select a notification to inspect delivery attempts.</p></div>"
    )

    empty_channels = (
        '<tr><td colspan="5">No notification channels configured.</td></tr>'
    )
    empty_rules = '<tr><td colspan="5">No notification rules configured.</td></tr>'
    empty_suppressions = (
        '<tr><td colspan="5">No suppression rules configured.</td></tr>'
    )
    empty_notifications = '<tr><td colspan="6">No notifications recorded.</td></tr>'

    return (
        "<div class='grid'>"
        f"<div class='card'><h3>Summary</h3><pre>{escape(json.dumps(summary.get('counts', {}), indent=2, sort_keys=True))}</pre></div>"
        f"<div class='card'><h3>Recent delivery failures</h3><pre>{escape(json.dumps(summary.get('recent_failures', []), indent=2, sort_keys=True))}</pre></div>"
        "</div>"
        "<div class='card'><h3>Create notification channel</h3>"
        "<form method='post' action='/notifications/channel/save'>"
        "<div class='grid'>"
        "<div><label>Channel id</label><input name='channel_id' placeholder='optional'></div>"
        "<div><label>Name</label><input name='name' required placeholder='Slack Ops'></div>"
        "<div><label>Kind</label><select name='kind'><option value='internal'>internal</option><option value='webhook'>webhook</option><option value='slack'>slack</option><option value='ntfy'>ntfy</option></select></div>"
        "<div><label>Risk</label><select name='risk_level'><option>dev</option><option>stage</option><option>prod</option></select></div>"
        "<div><label>Timeout seconds</label><input name='timeout_seconds' value='5'></div>"
        "<div><label>Max attempts</label><input name='max_attempts' value='3'></div>"
        "<div><label>Base backoff seconds</label><input name='base_backoff_seconds' value='2'></div>"
        "<div><label>Max backoff seconds</label><input name='max_backoff_seconds' value='30'></div>"
        "</div>"
        "<p><label>Target JSON</label><textarea name='target_json' rows='6' placeholder='{\"url\":\"https://hooks.slack.com/...\"}'></textarea></p>"
        "<p><label>Secret refs JSON</label><textarea name='secret_refs_json' rows='4' placeholder='{\"token\":\"stored:slack-token\"}'></textarea></p>"
        "<p><button type='submit'>Save channel</button></p></form></div>"
        "<div class='card'><h3>Create routing rule</h3>"
        "<form method='post' action='/notifications/rule/save'>"
        "<div class='grid'>"
        "<div><label>Rule id</label><input name='rule_id' placeholder='optional'></div>"
        "<div><label>Name</label><input name='name' required placeholder='Prod incidents to Slack'></div>"
        "<div><label>Event classes CSV</label><input name='event_classes' placeholder='incident_opened,component_quarantined'></div>"
        "<div><label>Component kinds CSV</label><input name='component_kinds' placeholder='ssh_tunnel,plugin_host'></div>"
        "<div><label>Severities CSV</label><input name='severities' placeholder='high,critical'></div>"
        "<div><label>Risk levels CSV</label><input name='risk_levels' placeholder='stage,prod'></div>"
        "<div><label>Incident statuses CSV</label><input name='incident_statuses' placeholder='open,quarantined'></div>"
        "<div><label>Channel ids CSV</label><input name='channel_ids' placeholder='internal-default,nch_123'></div>"
        "<div><label>Priority</label><input name='delivery_priority' value='100'></div>"
        "<div><label>Dedupe window seconds</label><input name='dedupe_window_seconds' value='300'></div>"
        "</div><p><button type='submit'>Save rule</button></p></form></div>"
        "<div class='card'><h3>Create suppression rule</h3>"
        "<form method='post' action='/notifications/suppression/save'>"
        "<div class='grid'>"
        "<div><label>Suppression id</label><input name='suppression_id' placeholder='optional'></div>"
        "<div><label>Name</label><input name='name' required placeholder='Maintenance mute'></div>"
        "<div><label>Reason</label><input name='reason' required placeholder='Planned maintenance window'></div>"
        "<div><label>Starts at</label><input name='starts_at' placeholder='2026-03-24T20:00:00+00:00'></div>"
        "<div><label>Ends at</label><input name='ends_at' placeholder='2026-03-24T22:00:00+00:00'></div>"
        "<div><label>Event classes CSV</label><input name='event_classes' placeholder='component_degraded'></div>"
        "<div><label>Component kinds CSV</label><input name='component_kinds' placeholder='datasource_watch'></div>"
        "<div><label>Severities CSV</label><input name='severities' placeholder='warning,high'></div>"
        "<div><label>Risk levels CSV</label><input name='risk_levels' placeholder='stage,prod'></div>"
        "<div><label>Actor</label><input name='actor' placeholder='operator'></div>"
        "</div><p><button type='submit'>Save suppression rule</button></p></form></div>"
        "<div class='card'><h3>Notification channels</h3><table><thead><tr><th>Channel</th><th>Kind</th><th>Policy</th><th>Target</th><th>Actions</th></tr></thead>"
        f"<tbody>{''.join(channel_rows) if channel_rows else empty_channels}</tbody></table></div>"
        "<div class='card'><h3>Routing rules</h3><table><thead><tr><th>Rule</th><th>Events</th><th>Channels</th><th>Policy</th><th>Actions</th></tr></thead>"
        f"<tbody>{''.join(rule_rows) if rule_rows else empty_rules}</tbody></table></div>"
        "<div class='card'><h3>Suppression rules</h3><table><thead><tr><th>Rule</th><th>Reason</th><th>Window</th><th>Scope</th><th>Actions</th></tr></thead>"
        f"<tbody>{''.join(suppression_rows) if suppression_rows else empty_suppressions}</tbody></table></div>"
        "<div class='card'><h3>Recent notifications</h3><table><thead><tr><th>Notification</th><th>Event</th><th>Severity</th><th>Status</th><th>Summary</th><th>Actions</th></tr></thead>"
        f"<tbody>{''.join(notification_rows) if notification_rows else empty_notifications}</tbody></table></div>"
        + detail_block
    )


def _watches_body(service: WebAdminService) -> str:
    profiles = service.list_datasources()
    watch_configs = service.list_watch_configs()
    watch_states = {
        str(item.get("component_id", "")): item
        for item in service.list_watch_states()
        if isinstance(item, dict)
    }
    datasource_options = "".join(
        f"<option value='{escape(profile.id)}'>{escape(profile.name)} [{escape(profile.backend)}]</option>"
        for profile in profiles
    )
    rows = []
    for watch in watch_configs:
        state = watch_states.get(watch.component_id, {})
        rows.append(
            "<tr>"
            f"<td><strong>{escape(watch.name)}</strong><br><span class='muted'>{escape(watch.id)}</span></td>"
            f"<td>{escape(watch.subject_kind.value)}<br><span class='muted'>{escape(watch.subject_ref)}</span></td>"
            f"<td>{escape(str(watch.enabled))}<br><span class='muted'>probe={escape(str(watch.probe_interval_seconds))}s stale={escape(str(watch.stale_timeout_seconds))}s</span></td>"
            f"<td>{escape(str(state.get('last_status', 'unknown')))}<br><span class='muted'>{escape(str(state.get('last_probe_at', '(never)')))}</span></td>"
            "<td>"
            f"<form class='inline' method='post' action='/watches/probe'><input type='hidden' name='watch_id' value='{escape(watch.id)}'><button type='submit'>Probe</button></form> "
            f"<form class='inline' method='post' action='/watches/delete'><input type='hidden' name='watch_id' value='{escape(watch.id)}'><button type='submit'>Delete</button></form>"
            "</td>"
            "</tr>"
        )
    empty_row = '<tr><td colspan="5">No watches configured.</td></tr>'
    return (
        "<div class='card'><h3>Create datasource watch</h3>"
        "<form method='post' action='/watches/datasource/save'>"
        "<div class='grid'>"
        "<div><label>Watch id</label><input name='watch_id' placeholder='optional'></div>"
        "<div><label>Name</label><input name='name' placeholder='Primary DB Reachability'></div>"
        f"<div><label>Datasource</label><select name='profile_id'>{datasource_options}</select></div>"
        "<div><label>Probe interval seconds</label><input name='probe_interval_seconds' value='30'></div>"
        "<div><label>Stale timeout seconds</label><input name='stale_timeout_seconds' value='90'></div>"
        "</div>"
        "<p><label>Recovery policy override JSON</label><textarea name='recovery_policy_override_json' rows='4'></textarea></p>"
        "<p><label>Monitor config JSON</label><textarea name='monitor_config_json' rows='4'></textarea></p>"
        "<p><button type='submit'>Save datasource watch</button></p></form></div>"
        "<div class='card'><h3>Create docker watch</h3>"
        "<form method='post' action='/watches/docker/save'>"
        "<div class='grid'>"
        "<div><label>Watch id</label><input name='watch_id' placeholder='optional'></div>"
        "<div><label>Name</label><input name='name' placeholder='Web container health'></div>"
        "<div><label>Container ref</label><input name='container_ref' placeholder='web'></div>"
        "<div><label>Target kind</label><select name='target_kind'><option value='local'>local</option><option value='ssh'>ssh</option></select></div>"
        "<div><label>Target ref</label><input name='target_ref' placeholder='deploy@example.com'></div>"
        "<div><label>Probe interval seconds</label><input name='probe_interval_seconds' value='30'></div>"
        "<div><label>Stale timeout seconds</label><input name='stale_timeout_seconds' value='90'></div>"
        "</div>"
        "<p><label>Recovery policy override JSON</label><textarea name='recovery_policy_override_json' rows='4'></textarea></p>"
        "<p><label>Monitor config JSON</label><textarea name='monitor_config_json' rows='4'></textarea></p>"
        "<p><button type='submit'>Save docker watch</button></p></form></div>"
        "<div class='card'><h3>Configured watches</h3><table><thead><tr><th>Watch</th><th>Subject</th><th>Config</th><th>State</th><th>Actions</th></tr></thead>"
        f"<tbody>{''.join(rows) if rows else empty_row}</tbody></table></div>"
    )


def _oncall_body(service: WebAdminService) -> str:
    people = service.list_operator_people()
    teams = service.list_operator_teams()
    memberships = service.list_team_memberships()
    bindings = service.list_ownership_bindings()
    schedules = service.list_oncall_schedules()
    policies = service.list_escalation_policies()
    active_engagements = service.list_engagements(active_only=True)

    team_options = "".join(
        f"<option value='{escape(team.id)}'>{escape(team.name)}</option>"
        for team in teams
    )
    person_options = "".join(
        f"<option value='{escape(person.id)}'>{escape(person.display_name)} ({escape(person.handle)})</option>"
        for person in people
    )
    person_options_with_blank = "<option value=''></option>" + person_options
    policy_options = "<option value=''></option>" + "".join(
        f"<option value='{escape(policy.id)}'>{escape(policy.name)}</option>"
        for policy in policies
    )

    people_rows = []
    for person in people:
        people_rows.append(
            "<tr>"
            f"<td><strong>{escape(person.display_name)}</strong><br><span class='muted'>{escape(person.id)}</span></td>"
            f"<td>{escape(person.handle)}<br><span class='muted'>{escape(person.timezone)}</span></td>"
            f"<td>{escape(str(person.enabled))}</td>"
            f"<td><pre>{escape(json.dumps([target.to_dict() for target in person.contact_targets], indent=2, sort_keys=True))}</pre></td>"
            "<td>"
            f"<form class='inline' method='post' action='/oncall/people/delete'><input type='hidden' name='person_id' value='{escape(person.id)}'><button type='submit'>Delete</button></form>"
            "</td>"
            "</tr>"
        )

    team_rows = []
    for team in teams:
        team_rows.append(
            "<tr>"
            f"<td><strong>{escape(team.name)}</strong><br><span class='muted'>{escape(team.id)}</span></td>"
            f"<td>{escape(str(team.enabled))}</td>"
            f"<td>{escape(team.description or '')}</td>"
            f"<td>{escape(team.default_escalation_policy_id or '(none)')}</td>"
            "<td>"
            f"<form class='inline' method='post' action='/oncall/teams/delete'><input type='hidden' name='team_id' value='{escape(team.id)}'><button type='submit'>Delete</button></form>"
            "</td>"
            "</tr>"
        )

    membership_rows = []
    for membership in memberships:
        membership_rows.append(
            "<tr>"
            f"<td><strong>{escape(membership.team_id)}</strong><br><span class='muted'>{escape(membership.id)}</span></td>"
            f"<td>{escape(membership.person_id)}</td>"
            f"<td>{escape(membership.role.value)}</td>"
            f"<td>{escape(str(membership.enabled))}</td>"
            "<td>"
            f"<form class='inline' method='post' action='/oncall/memberships/delete'><input type='hidden' name='membership_id' value='{escape(membership.id)}'><button type='submit'>Delete</button></form>"
            "</td>"
            "</tr>"
        )

    binding_rows = []
    for binding in bindings:
        binding_rows.append(
            "<tr>"
            f"<td><strong>{escape(binding.name)}</strong><br><span class='muted'>{escape(binding.id)}</span></td>"
            f"<td>{escape(binding.team_id)}</td>"
            f"<td>{escape(getattr(binding.component_kind, 'value', binding.component_kind) if binding.component_kind else '(any)')} / {escape(binding.component_id or '(any)')}</td>"
            f"<td>{escape(getattr(binding.subject_kind, 'value', binding.subject_kind) if binding.subject_kind else '(any)')} / {escape(binding.subject_ref or '(any)')}<br><span class='muted'>risk={escape(getattr(binding.risk_level, 'value', binding.risk_level) if binding.risk_level else '(any)')} policy={escape(binding.escalation_policy_id or '(team default)')}</span></td>"
            "<td>"
            f"<form class='inline' method='post' action='/oncall/bindings/delete'><input type='hidden' name='binding_id' value='{escape(binding.id)}'><button type='submit'>Delete</button></form>"
            "</td>"
            "</tr>"
        )

    schedule_rows = []
    for schedule in schedules:
        rotations = service.list_rotations(schedule.id)
        overrides = service.list_overrides(schedule.id)
        schedule_rows.append(
            "<tr>"
            f"<td><strong>{escape(schedule.name)}</strong><br><span class='muted'>{escape(schedule.id)}</span></td>"
            f"<td>{escape(schedule.team_id)}</td>"
            f"<td>{escape(schedule.coverage_kind.value)}<br><span class='muted'>{escape(schedule.timezone)}</span></td>"
            f"<td>{escape(str(schedule.enabled))}<br><span class='muted'>rotations={escape(str(len(rotations)))} overrides={escape(str(len(overrides)))}</span></td>"
            f"<td><pre>{escape(json.dumps(schedule.schedule_config, indent=2, sort_keys=True))}</pre></td>"
            "<td>"
            f"<form class='inline' method='post' action='/oncall/schedules/delete'><input type='hidden' name='schedule_id' value='{escape(schedule.id)}'><button type='submit'>Delete</button></form>"
            "</td>"
            "</tr>"
        )

    rotation_rows = []
    override_rows = []
    for schedule in schedules:
        for rotation in service.list_rotations(schedule.id):
            rotation_rows.append(
                "<tr>"
                f"<td><strong>{escape(rotation.name)}</strong><br><span class='muted'>{escape(rotation.id)}</span></td>"
                f"<td>{escape(rotation.schedule_id)}</td>"
                f"<td>{escape(rotation.interval_kind.value)} / {escape(str(rotation.interval_count))}</td>"
                f"<td>{escape(str(rotation.enabled))}<br><span class='muted'>{escape(str(rotation.anchor_at or '(none)'))}</span></td>"
                f"<td>{escape(', '.join(rotation.participant_ids))}</td>"
                "<td>"
                f"<form class='inline' method='post' action='/oncall/rotations/delete'><input type='hidden' name='rotation_id' value='{escape(rotation.id)}'><button type='submit'>Delete</button></form>"
                "</td>"
                "</tr>"
            )
        for override in service.list_overrides(schedule.id):
            override_rows.append(
                "<tr>"
                f"<td><strong>{escape(override.id)}</strong></td>"
                f"<td>{escape(override.schedule_id)}</td>"
                f"<td>{escape(override.replacement_person_id)}<br><span class='muted'>replaces={escape(override.replaced_person_id or '(whoever is active)')}</span></td>"
                f"<td>{escape(str(override.starts_at))}<br><span class='muted'>{escape(str(override.ends_at))}</span></td>"
                f"<td>{escape(override.reason)}<br><span class='muted'>priority={escape(str(override.priority))} actor={escape(override.actor or '(system)')}</span></td>"
                "<td>"
                f"<form class='inline' method='post' action='/oncall/overrides/delete'><input type='hidden' name='override_id' value='{escape(override.id)}'><button type='submit'>Delete</button></form>"
                "</td>"
                "</tr>"
            )

    policy_rows = []
    for policy in policies:
        detail = service.escalation_policy_detail(policy.id)
        steps_payload = (
            [step.to_dict() for step in detail.steps] if detail is not None else []
        )
        policy_rows.append(
            "<tr>"
            f"<td><strong>{escape(policy.name)}</strong><br><span class='muted'>{escape(policy.id)}</span></td>"
            f"<td>{escape(str(policy.enabled))}</td>"
            f"<td>ack={escape(str(policy.default_ack_timeout_seconds))}s repeat={escape(str(policy.default_repeat_page_seconds))}s max_repeat={escape(str(policy.max_repeat_pages))}</td>"
            f"<td><pre>{escape(json.dumps(steps_payload, indent=2, sort_keys=True))}</pre></td>"
            "<td>"
            f"<form class='inline' method='post' action='/oncall/policies/delete'><input type='hidden' name='policy_id' value='{escape(policy.id)}'><button type='submit'>Delete</button></form>"
            "</td>"
            "</tr>"
        )

    engagements_preview = (
        "<pre>"
        + escape(json.dumps(active_engagements[:10], indent=2, sort_keys=True))
        + "</pre>"
        if active_engagements
        else "<p class='muted'>No active engagements.</p>"
    )

    empty_people = '<tr><td colspan="5">No operators configured.</td></tr>'
    empty_teams = '<tr><td colspan="5">No teams configured.</td></tr>'
    empty_memberships = '<tr><td colspan="5">No memberships configured.</td></tr>'
    empty_bindings = '<tr><td colspan="5">No ownership bindings configured.</td></tr>'
    empty_schedules = '<tr><td colspan="6">No schedules configured.</td></tr>'
    empty_rotations = '<tr><td colspan="6">No rotations configured.</td></tr>'
    empty_overrides = '<tr><td colspan="6">No overrides configured.</td></tr>'
    empty_policies = '<tr><td colspan="5">No escalation policies configured.</td></tr>'

    return (
        "<div class='grid'>"
        f"<div class='card'><h3>People</h3><p>{escape(str(len(people)))} configured</p></div>"
        f"<div class='card'><h3>Teams</h3><p>{escape(str(len(teams)))} configured</p></div>"
        f"<div class='card'><h3>Schedules</h3><p>{escape(str(len(schedules)))} configured</p></div>"
        f"<div class='card'><h3>Policies</h3><p>{escape(str(len(policies)))} configured</p></div>"
        "</div>"
        "<div class='card'><h3>Create operator</h3>"
        "<form method='post' action='/oncall/people/save'>"
        "<div class='grid'>"
        "<div><label>Operator id</label><input name='person_id' placeholder='optional'></div>"
        "<div><label>Display name</label><input name='display_name' required placeholder='Alice Example'></div>"
        "<div><label>Handle</label><input name='handle' required placeholder='alice'></div>"
        "<div><label>Timezone</label><input name='timezone' value='Europe/Berlin'></div>"
        "</div>"
        "<p><label><input type='checkbox' name='enabled' value='1' checked> Enabled</label></p>"
        '<p><label>Contact targets JSON</label><textarea name=\'contact_targets_json\' rows=\'6\' placeholder=\'[{"channel_id":"slack-alice","label":"Slack","enabled":true,"priority":100}]\'></textarea></p>'
        "<p><label>Metadata JSON</label><textarea name='metadata_json' rows='4' placeholder='{\"role\":\"primary\"}'></textarea></p>"
        "<p><button type='submit'>Save operator</button></p></form></div>"
        "<div class='card'><h3>Create team</h3>"
        "<form method='post' action='/oncall/teams/save'>"
        "<div class='grid'>"
        "<div><label>Team id</label><input name='team_id' placeholder='optional'></div>"
        "<div><label>Name</label><input name='name' required placeholder='Platform Ops'></div>"
        f"<div><label>Default escalation policy</label><select name='default_escalation_policy_id'>{policy_options}</select></div>"
        "<div><label>Description</label><input name='description' placeholder='Primary platform operations'></div>"
        "</div>"
        "<p><label><input type='checkbox' name='enabled' value='1' checked> Enabled</label></p>"
        "<p><button type='submit'>Save team</button></p></form></div>"
        "<div class='card'><h3>Create membership</h3>"
        "<form method='post' action='/oncall/memberships/save'>"
        "<div class='grid'>"
        "<div><label>Membership id</label><input name='membership_id' placeholder='optional'></div>"
        f"<div><label>Team</label><select name='team_id'>{team_options}</select></div>"
        f"<div><label>Person</label><select name='person_id'>{person_options}</select></div>"
        "<div><label>Role</label><select name='role'><option value='member'>member</option><option value='lead'>lead</option></select></div>"
        "</div>"
        "<p><label><input type='checkbox' name='enabled' value='1' checked> Enabled</label></p>"
        "<p><button type='submit'>Save membership</button></p></form></div>"
        "<div class='card'><h3>Create ownership binding</h3>"
        "<form method='post' action='/oncall/bindings/save'>"
        "<div class='grid'>"
        "<div><label>Binding id</label><input name='binding_id' placeholder='optional'></div>"
        "<div><label>Name</label><input name='name' required placeholder='Prod docker ownership'></div>"
        f"<div><label>Team</label><select name='team_id'>{team_options}</select></div>"
        f"<div><label>Escalation policy</label><select name='escalation_policy_id'>{policy_options}</select></div>"
        "<div><label>Component kind</label><input name='component_kind' placeholder='docker_runtime'></div>"
        "<div><label>Component id</label><input name='component_id' placeholder='docker:web'></div>"
        "<div><label>Subject kind</label><input name='subject_kind' placeholder='datasource'></div>"
        "<div><label>Subject ref</label><input name='subject_ref' placeholder='analytics'></div>"
        "<div><label>Risk level</label><select name='risk_level'><option value=''></option><option value='dev'>dev</option><option value='stage'>stage</option><option value='prod'>prod</option></select></div>"
        "</div>"
        "<p><label><input type='checkbox' name='enabled' value='1' checked> Enabled</label></p>"
        "<p><button type='submit'>Save binding</button></p></form></div>"
        "<div class='card'><h3>Create schedule</h3>"
        "<form method='post' action='/oncall/schedules/save'>"
        "<div class='grid'>"
        "<div><label>Schedule id</label><input name='schedule_id' placeholder='optional'></div>"
        f"<div><label>Team</label><select name='team_id'>{team_options}</select></div>"
        "<div><label>Name</label><input name='name' required placeholder='Business Hours'></div>"
        "<div><label>Timezone</label><input name='timezone' value='Europe/Berlin'></div>"
        "<div><label>Coverage</label><select name='coverage_kind'><option value='always'>always</option><option value='weekly_window'>weekly_window</option></select></div>"
        "</div>"
        "<p><label><input type='checkbox' name='enabled' value='1' checked> Enabled</label></p>"
        '<p><label>Schedule config JSON</label><textarea name=\'schedule_config_json\' rows=\'4\' placeholder=\'{"days":[0,1,2,3,4],"start_time":"09:00","end_time":"17:00"}\'></textarea></p>'
        "<p><button type='submit'>Save schedule</button></p></form></div>"
        "<div class='card'><h3>Create rotation</h3>"
        "<form method='post' action='/oncall/rotations/save'>"
        "<div class='grid'>"
        "<div><label>Rotation id</label><input name='rotation_id' placeholder='optional'></div>"
        "<div><label>Schedule id</label><input name='schedule_id' required></div>"
        "<div><label>Name</label><input name='name' required placeholder='Primary rotation'></div>"
        "<div><label>Participants CSV</label><input name='participant_ids' placeholder='opr-1, opr-2'></div>"
        "<div><label>Anchor at</label><input name='anchor_at' placeholder='2026-03-24T09:00:00+01:00'></div>"
        "<div><label>Interval kind</label><select name='interval_kind'><option value='hours'>hours</option><option value='days'>days</option></select></div>"
        "<div><label>Interval count</label><input name='interval_count' value='7'></div>"
        "<div><label>Handoff time</label><input name='handoff_time' placeholder='09:00'></div>"
        "</div>"
        "<p><label><input type='checkbox' name='enabled' value='1' checked> Enabled</label></p>"
        "<p><button type='submit'>Save rotation</button></p></form></div>"
        "<div class='card'><h3>Create override</h3>"
        "<form method='post' action='/oncall/overrides/save'>"
        "<div class='grid'>"
        "<div><label>Override id</label><input name='override_id' placeholder='optional'></div>"
        "<div><label>Schedule id</label><input name='schedule_id' required></div>"
        f"<div><label>Replacement person</label><select name='replacement_person_id'>{person_options}</select></div>"
        f"<div><label>Replaced person</label><select name='replaced_person_id'>{person_options_with_blank}</select></div>"
        "<div><label>Starts at</label><input name='starts_at' placeholder='2026-03-24T18:00:00+01:00'></div>"
        "<div><label>Ends at</label><input name='ends_at' placeholder='2026-03-25T08:00:00+01:00'></div>"
        "<div><label>Priority</label><input name='priority' value='100'></div>"
        "<div><label>Actor</label><input name='actor' placeholder='operator'></div>"
        "</div>"
        "<p><label><input type='checkbox' name='enabled' value='1' checked> Enabled</label></p>"
        "<p><label>Reason</label><input name='reason' required placeholder='Vacation cover'></p>"
        "<p><button type='submit'>Save override</button></p></form></div>"
        "<div class='card'><h3>Create escalation policy</h3>"
        "<form method='post' action='/oncall/policies/save'>"
        "<div class='grid'>"
        "<div><label>Policy id</label><input name='policy_id' placeholder='optional'></div>"
        "<div><label>Name</label><input name='name' required placeholder='Default escalation'></div>"
        "<div><label>Ack timeout seconds</label><input name='default_ack_timeout_seconds' value='900'></div>"
        "<div><label>Repeat page seconds</label><input name='default_repeat_page_seconds' value='300'></div>"
        "<div><label>Max repeat pages</label><input name='max_repeat_pages' value='2'></div>"
        "<div><label>Terminal behavior</label><select name='terminal_behavior'><option value='exhaust'>exhaust</option></select></div>"
        "</div>"
        "<p><label><input type='checkbox' name='enabled' value='1' checked> Enabled</label></p>"
        '<p><label>Steps JSON</label><textarea name=\'steps_json\' rows=\'8\' placeholder=\'[{"step_index":0,"target_kind":"team","target_ref":"team-1","ack_timeout_seconds":900,"repeat_page_seconds":300,"max_repeat_pages":2,"reminder_enabled":true,"stop_on_ack":true}]\'></textarea></p>'
        "<p><button type='submit'>Save escalation policy</button></p></form></div>"
        "<div class='card'><h3>Active engagements</h3>"
        f"{engagements_preview}"
        "</div>"
        "<div class='card'><h3>Operators</h3><table><thead><tr><th>Person</th><th>Handle</th><th>Enabled</th><th>Contacts</th><th>Actions</th></tr></thead>"
        f"<tbody>{''.join(people_rows) if people_rows else empty_people}</tbody></table></div>"
        "<div class='card'><h3>Teams</h3><table><thead><tr><th>Team</th><th>Enabled</th><th>Description</th><th>Policy</th><th>Actions</th></tr></thead>"
        f"<tbody>{''.join(team_rows) if team_rows else empty_teams}</tbody></table></div>"
        "<div class='card'><h3>Memberships</h3><table><thead><tr><th>Team</th><th>Person</th><th>Role</th><th>Enabled</th><th>Actions</th></tr></thead>"
        f"<tbody>{''.join(membership_rows) if membership_rows else empty_memberships}</tbody></table></div>"
        "<div class='card'><h3>Ownership bindings</h3><table><thead><tr><th>Binding</th><th>Team</th><th>Component</th><th>Scope</th><th>Actions</th></tr></thead>"
        f"<tbody>{''.join(binding_rows) if binding_rows else empty_bindings}</tbody></table></div>"
        "<div class='card'><h3>Schedules</h3><table><thead><tr><th>Schedule</th><th>Team</th><th>Coverage</th><th>Status</th><th>Config</th><th>Actions</th></tr></thead>"
        f"<tbody>{''.join(schedule_rows) if schedule_rows else empty_schedules}</tbody></table></div>"
        "<div class='card'><h3>Rotations</h3><table><thead><tr><th>Rotation</th><th>Schedule</th><th>Interval</th><th>Status</th><th>Participants</th><th>Actions</th></tr></thead>"
        f"<tbody>{''.join(rotation_rows) if rotation_rows else empty_rotations}</tbody></table></div>"
        "<div class='card'><h3>Overrides</h3><table><thead><tr><th>Override</th><th>Schedule</th><th>Replacement</th><th>Window</th><th>Reason</th><th>Actions</th></tr></thead>"
        f"<tbody>{''.join(override_rows) if override_rows else empty_overrides}</tbody></table></div>"
        "<div class='card'><h3>Escalation policies</h3><table><thead><tr><th>Policy</th><th>Enabled</th><th>Defaults</th><th>Steps</th><th>Actions</th></tr></thead>"
        f"<tbody>{''.join(policy_rows) if policy_rows else empty_policies}</tbody></table></div>"
    )


def _layout_body(service: WebAdminService) -> str:
    layouts = service.list_layouts()
    panels = service.available_panels()
    header = (
        "<div class='card'>"
        "<h3>Canvas Editor</h3>"
        "<p class='muted'>Open the dedicated visual layout editor for split-tree editing, drag-and-drop moves, and whole-document saves.</p>"
        "<p><a href='/layouts/editor'>Open layout canvas</a></p>"
        "</div>"
    )
    blocks = []
    for layout in layouts:
        tabs = []
        for tab in layout.tabs:
            root_children = []
            for child in tab.root_split.children:
                if hasattr(child, "panel_id"):
                    root_children.append(
                        f"{escape(getattr(child, 'panel_id'))}:{escape(getattr(child, 'panel_type'))}"
                    )
                else:
                    root_children.append("split-node")
            panel_options = "".join(
                f"<option value='{escape(panel_id)}::{escape(panel_type)}'>{escape(display_name)} ({escape(panel_id)})</option>"
                for panel_type, panel_id, display_name in panels
            )
            tabs.append(
                "<div class='card'>"
                f"<h3>{escape(tab.name)} <span class='muted'>({escape(tab.id)})</span></h3>"
                f"<p>orientation={escape(tab.root_split.orientation or 'vertical')} ratio={escape(str(tab.root_split.ratio or 0.5))}</p>"
                f"<p>children: {escape(', '.join(root_children))}</p>"
                f"{_layout_preview(tab.root_split)}"
                "<div class='grid'>"
                f"<form method='post' action='/layouts/toggle'><input type='hidden' name='layout_id' value='{escape(layout.id)}'><input type='hidden' name='tab_id' value='{escape(tab.id)}'><button type='submit'>Toggle orientation</button></form>"
                f"<form method='post' action='/layouts/ratio'><input type='hidden' name='layout_id' value='{escape(layout.id)}'><input type='hidden' name='tab_id' value='{escape(tab.id)}'><label>Ratio</label><input name='ratio' value='{escape(str(tab.root_split.ratio or 0.5))}'><button type='submit'>Set ratio</button></form>"
                f"<form method='post' action='/layouts/add-panel'><input type='hidden' name='layout_id' value='{escape(layout.id)}'><input type='hidden' name='tab_id' value='{escape(tab.id)}'><label>Panel</label><select name='panel_pick'>{panel_options}</select><input type='hidden' name='panel_id' value=''><input type='hidden' name='panel_type' value=''></form>"
                "</div>"
                "<form method='post' action='/layouts/add-panel'>"
                f"<input type='hidden' name='layout_id' value='{escape(layout.id)}'>"
                f"<input type='hidden' name='tab_id' value='{escape(tab.id)}'>"
                "<div class='grid'>"
                f"<div><label>Panel id</label><input name='panel_id' placeholder='logs-panel'></div>"
                f"<div><label>Panel type</label><input name='panel_type' placeholder='logs'></div>"
                "</div><p><button type='submit'>Add panel</button></p></form>"
                "<form method='post' action='/layouts/remove-panel'>"
                f"<input type='hidden' name='layout_id' value='{escape(layout.id)}'>"
                f"<input type='hidden' name='tab_id' value='{escape(tab.id)}'>"
                "<div class='grid'>"
                "<div><label>Panel id</label><input name='panel_id' placeholder='db-panel'></div>"
                "</div><p><button type='submit'>Remove panel</button></p></form>"
                "<form method='post' action='/layouts/replace-panel'>"
                f"<input type='hidden' name='layout_id' value='{escape(layout.id)}'>"
                f"<input type='hidden' name='tab_id' value='{escape(tab.id)}'>"
                "<div class='grid'>"
                "<div><label>Existing panel id</label><input name='existing_panel_id'></div>"
                "<div><label>Replacement panel id</label><input name='replacement_panel_id'></div>"
                "<div><label>Replacement panel type</label><input name='replacement_panel_type'></div>"
                "</div><p><button type='submit'>Replace panel</button></p></form>"
                "<form method='post' action='/layouts/move-panel'>"
                f"<input type='hidden' name='layout_id' value='{escape(layout.id)}'>"
                f"<input type='hidden' name='tab_id' value='{escape(tab.id)}'>"
                "<div class='grid'>"
                "<div><label>Panel id</label><input name='panel_id' placeholder='db-panel'></div>"
                "<div><label>Direction</label><select name='direction'><option value='previous'>previous</option><option value='next'>next</option></select></div>"
                "</div><p><button type='submit'>Move panel</button></p></form>"
                "</div>"
            )
        blocks.append(
            "<div class='card'>"
            f"<h2>{escape(layout.name)} <span class='muted'>({escape(layout.id)})</span></h2>"
            "<form method='post' action='/layouts/clone'><div class='grid'>"
            f"<input type='hidden' name='source_layout_id' value='{escape(layout.id)}'>"
            "<div><label>New layout id</label><input name='target_layout_id'></div>"
            "<div><label>New layout name</label><input name='name'></div>"
            "</div><p><button type='submit'>Clone layout</button></p></form>"
            + "".join(tabs)
            + "</div>"
        )
    body = "".join(blocks) or "<div class='card'>No layouts saved.</div>"
    return header + body


def _diagnostics_body(service: WebAdminService) -> str:
    diagnostics = service.diagnostics()
    tunnels = diagnostics.get("tunnels", [])
    operations = diagnostics.get("operations", {})
    health = diagnostics.get("health", {})
    active_incidents = diagnostics.get("active_incidents", [])
    quarantined = diagnostics.get("quarantined_components", [])
    recent_attempts = diagnostics.get("recent_recovery_attempts", [])
    notifications = diagnostics.get("notifications", {})
    watches = diagnostics.get("watches", {})
    oncall = diagnostics.get("oncall", {})
    response = diagnostics.get("response", {})
    reviews = diagnostics.get("reviews", [])
    runbooks = diagnostics.get("runbooks", [])
    return (
        "<div class='card'><h3>Environment</h3>"
        f"<p>Project root: <code>{escape(str(diagnostics['project_root']))}</code></p>"
        f"<p>Python: <code>{escape(str(diagnostics['python']))}</code></p>"
        f"<p>Platform: <code>{escape(str(diagnostics['platform']))}</code></p>"
        f"<p>Commands: <code>{escape(str(diagnostics['command_count']))}</code></p>"
        f"<p>Panels: <code>{escape(', '.join(diagnostics['panel_types']))}</code></p>"
        "</div>"
        "<div class='card'><h3>Health Summary</h3>"
        f"<pre>{escape(json.dumps(health, indent=2, sort_keys=True))}</pre>"
        "</div>"
        "<div class='card'><h3>Active Incidents</h3>"
        f"{_incident_table(active_incidents, include_actions=False)}"
        "</div>"
        "<div class='card'><h3>Quarantined Components</h3>"
        f"<pre>{escape(json.dumps(quarantined, indent=2, sort_keys=True))}</pre>"
        "</div>"
        "<div class='card'><h3>Recent Recovery Attempts</h3>"
        f"<pre>{escape(json.dumps(recent_attempts, indent=2, sort_keys=True))}</pre>"
        "</div>"
        "<div class='card'><h3>Tooling</h3>"
        f"<pre>{escape(str(diagnostics['tools']))}</pre>"
        "</div>"
        "<div class='card'><h3>Datasources</h3>"
        f"<pre>{escape(str(diagnostics['datasources']))}</pre>"
        "</div>"
        "<div class='card'><h3>Secrets</h3>"
        f"<pre>{escape(str(diagnostics['secrets']))}</pre>"
        "</div>"
        "<div class='card'><h3>Plugins</h3>"
        f"<pre>{escape(str(diagnostics['plugins']))}</pre>"
        "</div>"
        "<div class='card'><h3>Plugin Hosts</h3>"
        f"<pre>{escape(json.dumps(diagnostics.get('plugin_hosts', []), indent=2, sort_keys=True))}</pre>"
        "</div>"
        "<div class='card'><h3>Notifications</h3>"
        f"<pre>{escape(json.dumps(notifications, indent=2, sort_keys=True))}</pre>"
        "</div>"
        "<div class='card'><h3>Watch State</h3>"
        f"<pre>{escape(json.dumps(watches, indent=2, sort_keys=True))}</pre>"
        "</div>"
        "<div class='card'><h3>On-Call</h3>"
        f"<pre>{escape(json.dumps(oncall, indent=2, sort_keys=True))}</pre>"
        "</div>"
        "<div class='card'><h3>Runbooks</h3>"
        f"<pre>{escape(json.dumps(runbooks, indent=2, sort_keys=True))}</pre>"
        "</div>"
        "<div class='card'><h3>Response Diagnostics</h3>"
        f"<pre>{escape(json.dumps(response, indent=2, sort_keys=True))}</pre>"
        "</div>"
        "<div class='card'><h3>Post-Incident Reviews</h3>"
        f"<pre>{escape(json.dumps(reviews, indent=2, sort_keys=True))}</pre>"
        "</div>"
        "<div class='card'><h3>Supervised Tasks</h3>"
        f"<pre>{escape(json.dumps(diagnostics.get('tasks', []), indent=2, sort_keys=True))}</pre>"
        "</div>"
        "<div class='card'><h3>Tunnels</h3>"
        f"{_tunnel_table(tunnels)}"
        "</div>"
        "<div class='card'><h3>Docker Diagnostics</h3>"
        f"<pre>{escape(json.dumps(operations.get('docker', []), indent=2, sort_keys=True))}</pre>"
        "</div>"
        "<div class='card'><h3>DB Diagnostics</h3>"
        f"<pre>{escape(json.dumps(operations.get('db', []), indent=2, sort_keys=True))}</pre>"
        "</div>"
        "<div class='card'><h3>Curl Diagnostics</h3>"
        f"<pre>{escape(json.dumps(operations.get('curl', []), indent=2, sort_keys=True))}</pre>"
        "</div>"
        "<div class='card'><h3>Engagement Diagnostics</h3>"
        f"<pre>{escape(json.dumps(operations.get('engagement', []), indent=2, sort_keys=True))}</pre>"
        "</div>"
        "<div class='card'><h3>Notification Delivery Operations</h3>"
        f"<pre>{escape(json.dumps(operations.get('notification', []), indent=2, sort_keys=True))}</pre>"
        "</div>"
        "<div class='card'><h3>Guard Decisions</h3>"
        f"<pre>{escape(json.dumps(operations.get('recent_guard_decisions', []), indent=2, sort_keys=True))}</pre>"
        "</div>"
    )


def _engagements_body(service: WebAdminService, *, engagement_id: str | None) -> str:
    engagements = service.list_engagements()
    detail = service.engagement_detail(engagement_id) if engagement_id else None
    active_only = service.list_engagements(active_only=True)
    return (
        "<div class='grid'>"
        f"<div class='card'><h3>Active</h3><p>{escape(str(len(active_only)))} active engagement(s)</p></div>"
        f"<div class='card'><h3>Recent</h3><p>{escape(str(len(engagements)))} engagement record(s)</p></div>"
        "</div>"
        "<div class='card'><h3>Engagement Center</h3>"
        "<p class='muted'>Canonical paging and escalation runtime state for active incidents.</p>"
        f"{_engagement_table(engagements, include_actions=True)}"
        "</div>"
        + (
            _engagement_detail_block(detail)
            if detail is not None
            else "<div class='card'><h3>Engagement Detail</h3><p class='muted'>Select an engagement to inspect timeline, deliveries, and handoff controls.</p></div>"
        )
    )


def _engagement_table(engagements: object, *, include_actions: bool) -> str:
    if not isinstance(engagements, list) or not engagements:
        return "<p class='muted'>No engagements recorded.</p>"
    rows = []
    for engagement in engagements:
        if not isinstance(engagement, dict):
            continue
        engagement_id = str(engagement.get("id", ""))
        incident_id = str(engagement.get("incident_id", ""))
        actions = ""
        if include_actions:
            actions = (
                f"<form class='inline' method='get' action='/engagements'><input type='hidden' name='engagement_id' value='{escape(engagement_id)}'><button type='submit'>View</button></form> "
                f"<form class='inline' method='post' action='/engagements/ack'><input type='hidden' name='engagement_id' value='{escape(engagement_id)}'><button type='submit'>Ack</button></form> "
                f"<form class='inline' method='post' action='/engagements/repage'><input type='hidden' name='engagement_id' value='{escape(engagement_id)}'><button type='submit'>Re-page</button></form>"
            )
        rows.append(
            "<tr>"
            f"<td><strong>{escape(engagement_id)}</strong><br><span class='muted'>incident={escape(incident_id)}</span></td>"
            f"<td>{escape(str(engagement.get('status', '')))}</td>"
            f"<td>{escape(str(engagement.get('team_id', '(unassigned)')))}</td>"
            f"<td>{escape(str(engagement.get('current_step_index', '0')))}<br><span class='muted'>{escape(str(engagement.get('current_target_ref', '(none)')))}</span></td>"
            f"<td>{escape(str(engagement.get('ack_deadline_at') or '(none)'))}<br><span class='muted'>next={escape(str(engagement.get('next_action_at') or '(none)'))}</span></td>"
            f"<td>{actions or escape(str(engagement.get('updated_at', '')))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Engagement</th><th>Status</th><th>Team</th><th>Step</th><th>Deadlines</th><th>Actions</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _engagement_detail_block(detail: object) -> str:
    engagement = getattr(detail, "engagement", None)
    if engagement is None:
        return "<div class='card'><h3>Engagement Detail</h3><p class='muted'>Engagement not found.</p></div>"
    incident = getattr(detail, "incident", None)
    timeline = getattr(detail, "timeline", [])
    delivery_links = getattr(detail, "delivery_links", [])
    current_target_ref = escape(str(engagement.current_target_ref or ""))
    incident_line = (
        f"<p class='muted'>Incident: {escape(incident.summary)} ({escape(incident.status.value)})</p>"
        if incident is not None
        else "<p class='muted'>Incident record is no longer available.</p>"
    )
    return (
        "<div class='card'><h3>Engagement Detail</h3>"
        f"<p><strong>{escape(engagement.id)}</strong><br><span class='muted'>incident={escape(engagement.incident_id)} component={escape(engagement.incident_component_id)}</span></p>"
        f"<p>Status: <code>{escape(engagement.status.value)}</code> team=<code>{escape(str(engagement.team_id or '(none)'))}</code> policy=<code>{escape(str(engagement.policy_id or '(none)'))}</code></p>"
        f"<p>Step <code>{escape(str(engagement.current_step_index))}</code> target=<code>{escape(engagement.current_target_kind.value if engagement.current_target_kind else '(none)')}</code> ref=<code>{current_target_ref or '(none)'}</code></p>"
        f"<p>Ack deadline: <code>{escape(str(engagement.ack_deadline_at or '(none)'))}</code> next action: <code>{escape(str(engagement.next_action_at or '(none)'))}</code></p>"
        f"{incident_line}"
        "<div class='grid'>"
        "<div class='card'><h3>Actions</h3>"
        f"<form method='post' action='/engagements/ack'><input type='hidden' name='engagement_id' value='{escape(engagement.id)}'><input type='hidden' name='actor' value='web-admin'><button type='submit'>Acknowledge</button></form>"
        f"<form method='post' action='/engagements/repage'><input type='hidden' name='engagement_id' value='{escape(engagement.id)}'><input type='hidden' name='actor' value='web-admin'><button type='submit'>Re-page</button></form>"
        "<form method='post' action='/engagements/handoff'>"
        f"<input type='hidden' name='engagement_id' value='{escape(engagement.id)}'>"
        "<input type='hidden' name='actor' value='web-admin'>"
        "<div class='grid'>"
        "<div><label>Target kind</label><select name='target_kind'><option value='person'>person</option><option value='team'>team</option><option value='channel'>channel</option></select></div>"
        "<div><label>Target ref</label><input name='target_ref' required placeholder='opr-1 or team-1 or slack-ops'></div>"
        "</div><p><button type='submit'>Hand off</button></p></form>"
        "</div>"
        "<div class='card'><h3>Engagement Snapshot</h3>"
        f"<pre>{escape(json.dumps(engagement.to_dict(), indent=2, sort_keys=True))}</pre>"
        "</div>"
        "</div>"
        "<h3>Timeline</h3>"
        f"<pre>{escape(json.dumps([entry.to_dict() for entry in timeline], indent=2, sort_keys=True))}</pre>"
        "<h3>Delivery Links</h3>"
        f"<pre>{escape(json.dumps([link.to_dict() for link in delivery_links], indent=2, sort_keys=True))}</pre>"
        "</div>"
    )


def _runbooks_body(service: WebAdminService, *, runbook_id: str | None) -> str:
    runbooks = service.list_runbooks()
    incidents = service.list_incidents(
        status="open",
    )
    detail = service.runbook_detail(runbook_id) if runbook_id else None
    incident_options = "".join(
        (
            f"<option value='{escape(incident.id)}'>"
            f"{escape(incident.id)} :: {escape(incident.summary)}"
            "</option>"
        )
        for incident in incidents
    )
    rows = []
    for runbook in runbooks:
        rows.append(
            "<tr>"
            f"<td><strong>{escape(runbook.title)}</strong><br><span class='muted'>{escape(runbook.id)}:{escape(runbook.version)}</span></td>"
            f"<td>{escape(runbook.risk_class.value)}</td>"
            f"<td>{escape(str(len(runbook.steps)))}<br><span class='muted'>{escape(', '.join(runbook.tags) or '(none)')}</span></td>"
            f"<td>{escape(json.dumps(runbook.scope, sort_keys=True))}</td>"
            f"<td><form class='inline' method='get' action='/runbooks'><input type='hidden' name='runbook_id' value='{escape(runbook.id)}'><button type='submit'>View</button></form></td>"
            "</tr>"
        )
    empty_row = '<tr><td colspan="5">No runbooks loaded.</td></tr>'
    return (
        "<div class='grid'>"
        f"<div class='card'><h3>Catalog</h3><p>{escape(str(len(runbooks)))} runbook definition(s)</p></div>"
        f"<div class='card'><h3>Active incidents</h3><p>{escape(str(len(incidents)))} incident(s) available for response start</p></div>"
        "</div>"
        "<div class='card'><h3>Start response run</h3>"
        "<form method='post' action='/responses/start'>"
        "<div class='grid'>"
        f"<div><label>Incident</label><select name='incident_id'>{incident_options}</select></div>"
        "<div><label>Runbook id</label><input name='runbook_id' placeholder='docker-container-unhealthy'></div>"
        "<div><label>Runbook version</label><input name='runbook_version' placeholder='latest optional'></div>"
        "<div><label>Engagement id</label><input name='engagement_id' placeholder='eng-1 optional'></div>"
        "</div>"
        "<p><button type='submit'>Start response</button></p>"
        "</form></div>"
        "<div class='card'><h3>Runbook catalog</h3>"
        "<table><thead><tr><th>Runbook</th><th>Risk</th><th>Steps</th><th>Scope</th><th>Actions</th></tr></thead>"
        f"<tbody>{''.join(rows) if rows else empty_row}</tbody></table>"
        "</div>"
        + (
            _runbook_detail_block(detail)
            if detail is not None
            else "<div class='card'><h3>Runbook Detail</h3><p class='muted'>Select a runbook to inspect its declarative steps and compensation contracts.</p></div>"
        )
    )


def _runbook_detail_block(detail: object) -> str:
    if detail is None:
        return "<div class='card'><h3>Runbook Detail</h3><p class='muted'>Runbook not found.</p></div>"
    payload = detail.to_dict() if hasattr(detail, "to_dict") else {}
    return (
        "<div class='card'><h3>Runbook Detail</h3>"
        f"<p><strong>{escape(getattr(detail, 'title', 'Runbook'))}</strong><br><span class='muted'>{escape(getattr(detail, 'id', ''))}:{escape(getattr(detail, 'version', ''))}</span></p>"
        f"<p>Risk class: <code>{escape(getattr(getattr(detail, 'risk_class', None), 'value', 'unknown'))}</code> steps=<code>{escape(str(len(getattr(detail, 'steps', ()))))}</code></p>"
        "<pre>"
        f"{escape(json.dumps(payload, indent=2, sort_keys=True))}"
        "</pre>"
        "</div>"
    )


def _responses_body(service: WebAdminService, *, response_run_id: str | None) -> str:
    runs = service.list_response_runs()
    active_runs = service.list_response_runs(active_only=True)
    pending_approvals = service.list_pending_approvals()
    detail = service.response_run_detail(response_run_id) if response_run_id else None
    return (
        "<div class='grid'>"
        f"<div class='card'><h3>Active response runs</h3><p>{escape(str(len(active_runs)))} active run(s)</p></div>"
        f"<div class='card'><h3>Pending approvals</h3><p>{escape(str(len(pending_approvals)))} approval request(s)</p></div>"
        "</div>"
        "<div class='card'><h3>Response Center</h3>"
        "<p class='muted'>Structured incident response runs, approval gates, compensation, and generated artifacts.</p>"
        f"{_response_table(runs, include_actions=True)}"
        "</div>"
        "<div class='card'><h3>Pending approvals</h3>"
        f"{_approval_table(pending_approvals)}"
        "</div>"
        + (
            _response_detail_block(detail)
            if detail is not None
            else "<div class='card'><h3>Response Detail</h3><p class='muted'>Select a response run to inspect steps, artifacts, timeline, and review linkage.</p></div>"
        )
    )


def _response_table(runs: object, *, include_actions: bool) -> str:
    if not isinstance(runs, list) or not runs:
        return "<p class='muted'>No response runs recorded.</p>"
    rows = []
    for item in runs:
        if not isinstance(item, dict):
            continue
        run_id = str(item.get("id", ""))
        actions = (
            f"<form class='inline' method='get' action='/responses'><input type='hidden' name='response_run_id' value='{escape(run_id)}'><button type='submit'>View</button></form> "
            f"<form class='inline' method='post' action='/responses/execute'><input type='hidden' name='response_run_id' value='{escape(run_id)}'><button type='submit'>Execute</button></form> "
            f"<form class='inline' method='post' action='/responses/retry'><input type='hidden' name='response_run_id' value='{escape(run_id)}'><button type='submit'>Retry</button></form> "
            f"<form class='inline' method='post' action='/responses/abort'><input type='hidden' name='response_run_id' value='{escape(run_id)}'><button type='submit'>Abort</button></form>"
            if include_actions
            else escape(str(item.get("updated_at", "")))
        )
        rows.append(
            "<tr>"
            f"<td><strong>{escape(run_id)}</strong><br><span class='muted'>incident={escape(str(item.get('incident_id', '')))}</span></td>"
            f"<td>{escape(str(item.get('runbook_id', '')))}<br><span class='muted'>{escape(str(item.get('runbook_version', '')))}</span></td>"
            f"<td>{escape(str(item.get('status', '')))}</td>"
            f"<td>{escape(str(item.get('current_step_index', '0')))}<br><span class='muted'>risk={escape(str(item.get('risk_level', '')))}</span></td>"
            f"<td>{escape(str(item.get('summary') or '(none)'))}</td>"
            f"<td>{actions}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Run</th><th>Runbook</th><th>Status</th><th>Step</th><th>Summary</th><th>Actions</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _approval_table(approvals: object) -> str:
    if not isinstance(approvals, list) or not approvals:
        return "<p class='muted'>No pending approvals.</p>"
    rows = []
    for item in approvals:
        if not isinstance(item, dict):
            continue
        request = item.get("request", {})
        decisions = item.get("decisions", [])
        if not isinstance(request, dict):
            continue
        request_id = str(request.get("id", ""))
        rows.append(
            "<tr>"
            f"<td><strong>{escape(request_id)}</strong><br><span class='muted'>run={escape(str(request.get('response_run_id', '')))}</span></td>"
            f"<td>{escape(str(request.get('status', '')))}</td>"
            f"<td>{escape(str(request.get('required_approver_count', 1)))}<br><span class='muted'>{escape(', '.join(request.get('required_roles', []) or []) or '(any)')}</span></td>"
            f"<td>{escape(str(request.get('reason') or '(none)'))}</td>"
            f"<td>{escape(str(len(decisions) if isinstance(decisions, list) else 0))}</td>"
            "<td>"
            f"<form class='inline' method='post' action='/approvals/decide'><input type='hidden' name='approval_request_id' value='{escape(request_id)}'><input type='hidden' name='decision' value='approve'><button type='submit'>Approve</button></form> "
            f"<form class='inline' method='post' action='/approvals/decide'><input type='hidden' name='approval_request_id' value='{escape(request_id)}'><input type='hidden' name='decision' value='reject'><button type='submit'>Reject</button></form>"
            "</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Approval</th><th>Status</th><th>Threshold</th><th>Reason</th><th>Decisions</th><th>Actions</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _response_detail_block(detail: object) -> str:
    response_run = getattr(detail, "response_run", None)
    if response_run is None:
        return "<div class='card'><h3>Response Detail</h3><p class='muted'>Response run not found.</p></div>"
    incident = getattr(detail, "incident", None)
    runbook = getattr(detail, "runbook", None)
    step_runs = getattr(detail, "step_runs", ())
    approvals = getattr(detail, "approvals", ())
    artifacts = getattr(detail, "artifacts", ())
    compensations = getattr(detail, "compensations", ())
    timeline = getattr(detail, "timeline", ())
    review = getattr(detail, "review", None)
    review_id = escape(review.id) if review is not None else ""
    review_block = (
        f"<p><strong>{escape(review.id)}</strong> status=<code>{escape(review.status.value)}</code> closure=<code>{escape(review.closure_quality.value)}</code></p>"
        if review is not None
        else (
            "<form method='post' action='/reviews/ensure'>"
            f"<input type='hidden' name='incident_id' value='{escape(response_run.incident_id)}'>"
            f"<input type='hidden' name='response_run_id' value='{escape(response_run.id)}'>"
            "<input type='hidden' name='owner_ref' value='web-admin'>"
            "<p><button type='submit'>Open review</button></p>"
            "</form>"
        )
    )
    parts = [
        "<div class='card'><h3>Response Detail</h3>",
        (
            f"<p><strong>{escape(response_run.id)}</strong><br>"
            f"<span class='muted'>incident={escape(response_run.incident_id)} "
            f"runbook={escape(response_run.runbook_id)}:{escape(response_run.runbook_version)}</span></p>"
        ),
        (
            f"<p>Status: <code>{escape(response_run.status.value)}</code> "
            f"current step=<code>{escape(str(response_run.current_step_index))}</code> "
            f"risk=<code>{escape(response_run.risk_level.value)}</code></p>"
        ),
        (
            f"<p>Incident: <code>{escape(getattr(incident, 'id', ''))}</code> "
            f"{escape(getattr(incident, 'summary', '(unknown)'))}</p>"
        ),
        f"<p>Runbook title: <code>{escape(getattr(runbook, 'title', '(unknown)'))}</code></p>",
        "<div class='grid'>",
        "<div class='card'><h3>Actions</h3>",
        (
            f"<form method='post' action='/responses/execute'>"
            f"<input type='hidden' name='response_run_id' value='{escape(response_run.id)}'>"
            "<p><label>Notes</label><textarea name='notes' rows='3'></textarea></p>"
            "<p><label><input type='checkbox' name='confirmed' value='1'> Confirm</label></p>"
            "<p><label><input type='checkbox' name='elevated_mode' value='1'> Elevated mode</label></p>"
            "<p><button type='submit'>Execute current step</button></p></form>"
        ),
        (
            f"<form method='post' action='/responses/retry'>"
            f"<input type='hidden' name='response_run_id' value='{escape(response_run.id)}'>"
            "<p><button type='submit'>Retry current step</button></p></form>"
        ),
        (
            f"<form method='post' action='/responses/compensate'>"
            f"<input type='hidden' name='response_run_id' value='{escape(response_run.id)}'>"
            "<p><label><input type='checkbox' name='confirmed' value='1'> Confirm compensation</label></p>"
            "<p><button type='submit'>Run compensation</button></p></form>"
        ),
        (
            f"<form method='post' action='/responses/abort'>"
            f"<input type='hidden' name='response_run_id' value='{escape(response_run.id)}'>"
            "<p><label>Reason</label><input name='reason' value='web-admin abort'></p>"
            "<p><button type='submit'>Abort response</button></p></form>"
        ),
        "</div>",
        "<div class='card'><h3>Linked review</h3>",
        review_block,
        (
            f"<p><a href='/reviews?review_id={review_id}'>Open review detail</a></p>"
            if review is not None
            else ""
        ),
        "</div>",
        "</div>",
        "<h3>Step Runs</h3>",
        escape(
            json.dumps([item.to_dict() for item in step_runs], indent=2, sort_keys=True)
        ),
        "<h3>Approvals</h3>",
        _approval_table(list(approvals)),
        "<h3>Artifacts</h3>",
        escape(
            json.dumps([item.to_dict() for item in artifacts], indent=2, sort_keys=True)
        ),
        "<h3>Compensations</h3>",
        escape(
            json.dumps(
                [item.to_dict() for item in compensations], indent=2, sort_keys=True
            )
        ),
        "<h3>Timeline</h3>",
        escape(json.dumps(list(timeline), indent=2, sort_keys=True)),
        "</div>",
    ]
    return (
        "".join(
            f"<pre>{part}</pre>" if part.startswith("{") else part for part in parts
        )
        .replace("<h3>Step Runs</h3>", "<h3>Step Runs</h3><pre>")
        .replace("<h3>Approvals</h3>", "</pre><h3>Approvals</h3>")
        .replace("<h3>Artifacts</h3>", "<h3>Artifacts</h3><pre>")
        .replace("<h3>Compensations</h3>", "</pre><h3>Compensations</h3><pre>")
        .replace("<h3>Timeline</h3>", "</pre><h3>Timeline</h3><pre>")
        .replace("</div><pre>", "</pre></div>")
    )


def _reviews_body(service: WebAdminService, *, review_id: str | None) -> str:
    reviews = service.list_reviews()
    detail = service.review_detail(review_id) if review_id else None
    return (
        "<div class='card'><h3>Review Center</h3>"
        "<p class='muted'>Structured post-incident reviews with findings, action items, and closure quality.</p>"
        f"{_review_table(reviews)}"
        "</div>"
        + (
            _review_detail_block(detail)
            if detail is not None
            else "<div class='card'><h3>Review Detail</h3><p class='muted'>Select a review to inspect findings and action items.</p></div>"
        )
    )


def _review_table(reviews: object) -> str:
    if not isinstance(reviews, list) or not reviews:
        return "<p class='muted'>No post-incident reviews recorded.</p>"
    rows = []
    for review in reviews:
        if not hasattr(review, "id"):
            continue
        rows.append(
            "<tr>"
            f"<td><strong>{escape(review.id)}</strong><br><span class='muted'>incident={escape(review.incident_id)}</span></td>"
            f"<td>{escape(review.status.value)}</td>"
            f"<td>{escape(str(review.owner_ref or '(unassigned)'))}</td>"
            f"<td>{escape(review.summary or '(open)')}</td>"
            f"<td><form class='inline' method='get' action='/reviews'><input type='hidden' name='review_id' value='{escape(review.id)}'><button type='submit'>View</button></form></td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Review</th><th>Status</th><th>Owner</th><th>Summary</th><th>Actions</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _review_detail_block(detail: object) -> str:
    review = getattr(detail, "review", None)
    if review is None:
        return "<div class='card'><h3>Review Detail</h3><p class='muted'>Review not found.</p></div>"
    findings = getattr(detail, "findings", ())
    action_items = getattr(detail, "action_items", ())
    return (
        "<div class='card'><h3>Review Detail</h3>"
        f"<p><strong>{escape(review.id)}</strong><br><span class='muted'>incident={escape(review.incident_id)} response={escape(str(review.response_run_id or '(none)'))}</span></p>"
        f"<p>Status: <code>{escape(review.status.value)}</code> owner=<code>{escape(str(review.owner_ref or '(none)'))}</code> closure=<code>{escape(review.closure_quality.value)}</code></p>"
        f"<p>Summary: {escape(review.summary or '(open)')}</p>"
        "<div class='grid'>"
        "<div class='card'><h3>Add finding</h3>"
        "<form method='post' action='/reviews/finding/add'>"
        f"<input type='hidden' name='review_id' value='{escape(review.id)}'>"
        "<div class='grid'>"
        "<div><label>Category</label><select name='category'><option value='process'>process</option><option value='tooling'>tooling</option><option value='automation'>automation</option><option value='communication'>communication</option></select></div>"
        "<div><label>Severity</label><select name='severity'><option value='low'>low</option><option value='medium'>medium</option><option value='high'>high</option><option value='critical'>critical</option></select></div>"
        "</div><p><label>Title</label><input name='title'></p><p><label>Detail</label><textarea name='detail' rows='4'></textarea></p><p><button type='submit'>Add finding</button></p></form>"
        "</div>"
        "<div class='card'><h3>Add action item</h3>"
        "<form method='post' action='/reviews/action-item/add'>"
        f"<input type='hidden' name='review_id' value='{escape(review.id)}'>"
        "<p><label>Owner ref</label><input name='owner_ref' placeholder='opr-1'></p>"
        "<p><label>Title</label><input name='title'></p>"
        "<p><label>Detail</label><textarea name='detail' rows='4'></textarea></p>"
        "<p><label>Due at (ISO)</label><input name='due_at' placeholder='2026-03-25T12:00:00+00:00'></p>"
        "<p><button type='submit'>Add action item</button></p></form>"
        "</div>"
        "</div>"
        "<h3>Findings</h3>"
        f"<pre>{escape(json.dumps([item.to_dict() for item in findings], indent=2, sort_keys=True))}</pre>"
        "<h3>Action Items</h3>"
        f"{_action_item_table(action_items)}"
        "<div class='card'><h3>Complete Review</h3>"
        "<form method='post' action='/reviews/complete'>"
        f"<input type='hidden' name='review_id' value='{escape(review.id)}'>"
        "<p><label>Summary</label><textarea name='summary' rows='4'></textarea></p>"
        "<p><label>Root cause</label><textarea name='root_cause' rows='4'></textarea></p>"
        "<p><label>Closure quality</label><select name='closure_quality'><option value='incomplete'>incomplete</option><option value='partial'>partial</option><option value='complete'>complete</option></select></p>"
        "<p><button type='submit'>Complete review</button></p></form>"
        "</div>"
        "</div>"
    )


def _action_item_table(action_items: object) -> str:
    if not isinstance(action_items, tuple | list) or not action_items:
        return "<p class='muted'>No action items recorded.</p>"
    rows = []
    for item in action_items:
        rows.append(
            "<tr>"
            f"<td><strong>{escape(item.id)}</strong><br><span class='muted'>{escape(item.title)}</span></td>"
            f"<td>{escape(item.status.value)}</td>"
            f"<td>{escape(str(item.owner_ref or '(unassigned)'))}</td>"
            f"<td>{escape(item.detail)}</td>"
            "<td>"
            f"<form class='inline' method='post' action='/reviews/action-item/status'><input type='hidden' name='action_item_id' value='{escape(item.id)}'><input type='hidden' name='status' value='in_progress'><button type='submit'>In progress</button></form> "
            f"<form class='inline' method='post' action='/reviews/action-item/status'><input type='hidden' name='action_item_id' value='{escape(item.id)}'><input type='hidden' name='status' value='closed'><button type='submit'>Close</button></form>"
            "</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Item</th><th>Status</th><th>Owner</th><th>Detail</th><th>Actions</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _incident_body(service: WebAdminService, *, incident_id: str | None) -> str:
    incidents = service.list_incidents()
    detail = service.incident_detail(incident_id) if incident_id else None
    return (
        "<div class='card'><h3>Incident Center</h3>"
        "<p class='muted'>Structured incident records, recovery history, and quarantine visibility for runtime components.</p>"
        f"{_incident_table([incident.to_dict() for incident in incidents], include_actions=True)}"
        "</div>"
        + (
            _incident_detail_block(detail)
            if detail is not None
            else "<div class='card'><h3>Incident Detail</h3><p class='muted'>Select an incident from the list to inspect timeline and recovery history.</p></div>"
        )
    )


def _incident_table(incidents: object, *, include_actions: bool) -> str:
    if not isinstance(incidents, list) or not incidents:
        return "<p class='muted'>No incidents recorded.</p>"
    rows = []
    for incident in incidents:
        if not isinstance(incident, dict):
            continue
        incident_id = str(incident.get("id", ""))
        component_id = str(incident.get("component_id", ""))
        actions = ""
        if include_actions:
            actions = (
                f"<form class='inline' method='get' action='/incidents'><input type='hidden' name='incident_id' value='{escape(incident_id)}'><button type='submit'>View</button></form> "
                f"<form class='inline' method='post' action='/incidents/acknowledge'><input type='hidden' name='incident_id' value='{escape(incident_id)}'><button type='submit'>Ack</button></form> "
                f"<form class='inline' method='post' action='/incidents/close'><input type='hidden' name='incident_id' value='{escape(incident_id)}'><button type='submit'>Close</button></form> "
                f"<form class='inline' method='post' action='/incidents/retry'><input type='hidden' name='component_id' value='{escape(component_id)}'><button type='submit'>Retry</button></form> "
                f"<form class='inline' method='post' action='/incidents/reset-quarantine'><input type='hidden' name='component_id' value='{escape(component_id)}'><button type='submit'>Reset Quarantine</button></form>"
            )
        rows.append(
            "<tr>"
            f"<td><strong>{escape(incident_id)}</strong><br><span class='muted'>{escape(component_id)}</span></td>"
            f"<td>{escape(str(incident.get('component_kind', '')))}</td>"
            f"<td>{escape(str(incident.get('severity', '')))}</td>"
            f"<td>{escape(str(incident.get('status', '')))}</td>"
            f"<td>{escape(str(incident.get('summary', '')))}</td>"
            f"<td>{actions or escape(str(incident.get('updated_at', '')))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Incident</th><th>Component</th><th>Severity</th><th>Status</th><th>Summary</th><th>Actions</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _incident_detail_block(detail: object) -> str:
    incident = getattr(detail, "incident", None)
    if incident is None:
        return "<div class='card'><h3>Incident Detail</h3><p class='muted'>Incident not found.</p></div>"
    timeline = getattr(detail, "timeline", [])
    recovery_attempts = getattr(detail, "recovery_attempts", [])
    health = getattr(detail, "current_health", None)
    return (
        "<div class='card'><h3>Incident Detail</h3>"
        f"<p><strong>{escape(incident.title)}</strong><br><span class='muted'>{escape(incident.id)} / {escape(incident.component_id)}</span></p>"
        f"<p>Status: <code>{escape(incident.status.value)}</code> Severity: <code>{escape(incident.severity.value)}</code></p>"
        f"<p>{escape(incident.summary)}</p>"
        "<h3>Timeline</h3>"
        f"<pre>{escape(json.dumps([entry.to_dict() for entry in timeline], indent=2, sort_keys=True))}</pre>"
        "<h3>Recovery Attempts</h3>"
        f"<pre>{escape(json.dumps([attempt.to_dict() for attempt in recovery_attempts], indent=2, sort_keys=True))}</pre>"
        "<h3>Current Health</h3>"
        f"<pre>{escape(json.dumps(health or {}, indent=2, sort_keys=True))}</pre>"
        "</div>"
    )


def _layout_preview(node: object) -> str:
    if hasattr(node, "panel_id") and hasattr(node, "panel_type"):
        return (
            "<div class='panel-node'>"
            f"<strong>{escape(str(getattr(node, 'panel_id')))}</strong><br>"
            f"<span class='muted'>{escape(str(getattr(node, 'panel_type')))}</span>"
            "</div>"
        )
    orientation = escape(str(getattr(node, "orientation", "vertical") or "vertical"))
    ratio = escape(str(getattr(node, "ratio", 0.5) or 0.5))
    children = getattr(node, "children", [])
    if not isinstance(children, list):
        children = []
    direction_class = (
        "split-horizontal" if orientation == "horizontal" else "split-vertical"
    )
    rendered_children = "".join(
        f"<div class='layout-child'>{_layout_preview(child)}</div>"
        for child in children
    )
    return (
        "<div class='layout-preview-wrapper'>"
        f"<div class='muted'>preview orientation={orientation} ratio={ratio}</div>"
        f"<div class='layout-preview {direction_class}'>{rendered_children}</div>"
        "</div>"
    )


def _optional_datetime(raw_value: object) -> datetime | None:
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    if not text:
        return None
    return datetime.fromisoformat(text)


def _tunnel_table(tunnels: object) -> str:
    if not isinstance(tunnels, list) or not tunnels:
        return "<p class='muted'>No active SSH tunnels.</p>"
    rows = []
    for tunnel in tunnels:
        if not isinstance(tunnel, dict):
            continue
        profile_id = str(tunnel.get("profile_id", ""))
        rows.append(
            "<tr>"
            f"<td>{escape(profile_id)}</td>"
            f"<td>{escape(str(tunnel.get('target_ref', '')))}</td>"
            f"<td>{escape(str(tunnel.get('remote_host', '')))}:{escape(str(tunnel.get('remote_port', '')))}</td>"
            f"<td>127.0.0.1:{escape(str(tunnel.get('local_port', '')))}</td>"
            f"<td>{escape(str(tunnel.get('alive', False)))}<br><span class='muted'>reconnects={escape(str(tunnel.get('reconnect_count', 0)))}</span></td>"
            "<td>"
            f"<form class='inline' method='post' action='/diagnostics/reconnect-tunnel'><input type='hidden' name='profile_id' value='{escape(profile_id)}'><button type='submit'>Reconnect</button></form> "
            f"<form class='inline' method='post' action='/diagnostics/close-tunnel'><input type='hidden' name='profile_id' value='{escape(profile_id)}'><button type='submit'>Close</button></form>"
            f"<div class='muted'>{escape(str(tunnel.get('last_failure', '')))}</div>"
            "</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Profile</th><th>Target</th><th>Remote</th><th>Local</th><th>Alive</th><th>Actions</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _masked_secret_reference(reference: object) -> str:
    if not isinstance(reference, dict):
        return "{}"
    masked = dict(reference)
    provider = masked.get("provider")
    if provider == "keyring":
        username = masked.get("username")
        if isinstance(username, str) and username:
            masked["username"] = _mask_text(username)
    if provider == "file":
        path = masked.get("path")
        if isinstance(path, str) and path:
            masked["path"] = f".../{path.split('/')[-1]}"
    if provider == "env":
        name = masked.get("name")
        if isinstance(name, str) and name:
            masked["name"] = _mask_text(name)
    return json.dumps(masked, sort_keys=True)


def _mask_text(value: str) -> str:
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}***{value[-2:]}"
