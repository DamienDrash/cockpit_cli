"""Local web admin HTTP server."""

from __future__ import annotations

import json
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import mimetypes
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from cockpit.application.services.web_admin_service import WebAdminService
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

    def __init__(self, service: WebAdminService, *, host: str = "127.0.0.1", port: int = 8765) -> None:
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
                if parsed.path == "/layouts/editor" or parsed.path.startswith("/layouts/editor/"):
                    asset_path = resolve_asset(parsed.path)
                    if asset_path is None and parsed.path in {"/layouts/editor", "/layouts/editor/"}:
                        asset_path = index_path()
                    if asset_path is None or not asset_path.exists():
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    self._asset(asset_path)
                    return
                if parsed.path == "/":
                    self._html(_page("Cockpit Web Admin", _home_body(service), flash=flash))
                    return
                if parsed.path == "/datasources":
                    self._html(_page("Datasources", _datasource_body(service), flash=flash))
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
                if parsed.path == "/diagnostics":
                    self._html(_page("Diagnostics", _diagnostics_body(service), flash=flash))
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
                        self._json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                        return
                    self._json(response)
                    return
                form = {key: values[-1] for key, values in parse_qs(body).items() if values}
                try:
                    redirect_path, message = _handle_post(service, parsed.path, form)
                except Exception as exc:
                    redirect_path, message = _redirect_target(parsed.path), str(exc)
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", f"{redirect_path}?{urlencode({'message': message})}")
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

            def _json(self, payload: dict[str, object], *, status: HTTPStatus = HTTPStatus.OK) -> None:
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
    if path.startswith("/diagnostics"):
        return "/diagnostics"
    return "/"


def _handle_post(service: WebAdminService, path: str, form: dict[str, str]) -> tuple[str, str]:
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
        result = service.execute_datasource(profile_id, statement, operation=operation)
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
    if path == "/plugins/install":
        plugin = service.install_plugin(form)
        return "/plugins", f"Installed plugin {plugin.name}."
    if path == "/plugins/update":
        plugin = service.update_plugin(form.get("plugin_id", ""))
        return "/plugins", f"Updated plugin {plugin.name}."
    if path == "/plugins/toggle":
        enabled = form.get("enabled", "1") == "1"
        plugin = service.toggle_plugin(form.get("plugin_id", ""), enabled)
        return "/plugins", f"{'Enabled' if plugin.enabled else 'Disabled'} plugin {plugin.name}."
    if path == "/plugins/pin":
        plugin = service.pin_plugin(form.get("plugin_id", ""), form.get("version_pin") or None)
        detail = plugin.version_pin or "none"
        return "/plugins", f"Pinned plugin {plugin.name} to {detail}."
    if path == "/plugins/remove":
        plugin_id = form.get("plugin_id", "")
        service.remove_plugin(plugin_id)
        return "/plugins", f"Removed plugin {plugin_id}."
    if path == "/layouts/clone":
        layout = service.clone_layout(
            form.get("source_layout_id", ""),
            form.get("target_layout_id", ""),
            form.get("name") or None,
        )
        return "/layouts", f"Saved layout variant {layout.id}."
    if path == "/layouts/toggle":
        layout = service.toggle_layout_tab(form.get("layout_id", ""), form.get("tab_id", ""))
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


def _handle_api_post(service: WebAdminService, path: str, payload: dict[str, object]) -> dict[str, object]:
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
    return (
        "<div class='grid'>"
        f"<div class='card'><h3>Datasources</h3><p>{escape(str(datasource_diag['total_profiles']))} total / {escape(str(datasource_diag['enabled_profiles']))} enabled</p></div>"
        f"<div class='card'><h3>Secrets</h3><p>{escape(str(secret_diag['total_entries']))} managed / {escape(str(secret_diag.get('rotated_entries', 0)))} rotated / keyring={escape(str(secret_diag['keyring_available']))}</p></div>"
        f"<div class='card'><h3>Plugins</h3><p>{escape(str(plugin_diag['count']))} installed / {escape(str(plugin_diag['enabled']))} enabled</p></div>"
        f"<div class='card'><h3>Trusted Plugin Sources</h3><p>{escape(str(len(plugin_diag.get('trusted_sources', []))))} configured</p></div>"
        f"<div class='card'><h3>Panels</h3><p>{escape(', '.join(diagnostics['panel_types']))}</p></div>"
        "</div>"
        "<p class='muted'>Use the admin pages to manage datasource profiles, managed secret references, plugin installs, layout variants, and runtime diagnostics.</p>"
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
        f"<tbody>{''.join(rows) if rows else '<tr><td colspan=\"5\">No datasource profiles saved.</td></tr>'}</tbody></table></div>"
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
        "<p class='muted'>Backend examples: SQL uses SQL text, MongoDB uses JSON payloads, Redis uses redis-cli style commands, Chroma uses JSON payloads.</p>"
        "<p><button type='submit'>Execute</button></p></form></div>"
        + last_result_block
    )


def _secret_body(service: WebAdminService) -> str:
    entries = service.list_secrets()
    rows = []
    for entry in entries:
        rotate_form = ""
        if entry.provider == "keyring":
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
    return (
        "<div class='card'><h3>Create managed secret reference</h3>"
        "<form method='post' action='/secrets/create'>"
        "<div class='grid'>"
        "<div><label>Name</label><input name='name' required placeholder='analytics-db-pass'></div>"
        "<div><label>Provider</label><select name='provider'><option value='env'>env</option><option value='file'>file</option><option value='keyring'>keyring</option></select></div>"
        "<div><label>Description</label><input name='description' placeholder='Analytics DB password'></div>"
        "<div><label>Tags</label><input name='tags' placeholder='analytics, prod'></div>"
        "<div><label>Env var name</label><input name='env_name' placeholder='ANALYTICS_DB_PASS'></div>"
        "<div><label>File path</label><input name='file_path' placeholder='secrets/db-pass.txt'></div>"
        "<div><label>Keyring service</label><input name='keyring_service' placeholder='cockpit'></div>"
        "<div><label>Keyring username</label><input name='keyring_username' placeholder='analytics-db-pass'></div>"
        "</div>"
        "<p><label>Keyring value</label><input name='secret_value' type='password' placeholder='Only used for keyring entries'></p>"
        "<p class='muted'>Use these in datasource secret refs as <code>stored:secret-name</code>.</p>"
        "<p><button type='submit'>Save secret reference</button></p></form></div>"
        "<div class='card'><h3>Managed secrets</h3><table><thead><tr><th>Name</th><th>Reference</th><th>Description</th><th>Actions</th></tr></thead>"
        f"<tbody>{''.join(rows) if rows else '<tr><td colspan=\"4\">No managed secrets saved.</td></tr>'}</tbody></table></div>"
    )


def _plugin_body(service: WebAdminService) -> str:
    plugins = service.list_plugins()
    rows = []
    for plugin in plugins:
        summary = plugin.manifest.get("summary", "")
        permissions = plugin.manifest.get("permissions", [])
        runtime_mode = str(plugin.manifest.get("runtime_mode", "hosted"))
        permissions_text = ", ".join(
            str(item) for item in permissions if isinstance(item, str)
        ) or "(none)"
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
        f"<tbody>{''.join(rows) if rows else '<tr><td colspan=\"5\">No plugins installed.</td></tr>'}</tbody></table></div>"
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
                    root_children.append(f"{escape(getattr(child, 'panel_id'))}:{escape(getattr(child, 'panel_type'))}")
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
    return (
        "<div class='card'><h3>Environment</h3>"
        f"<p>Project root: <code>{escape(str(diagnostics['project_root']))}</code></p>"
        f"<p>Python: <code>{escape(str(diagnostics['python']))}</code></p>"
        f"<p>Platform: <code>{escape(str(diagnostics['platform']))}</code></p>"
        f"<p>Commands: <code>{escape(str(diagnostics['command_count']))}</code></p>"
        f"<p>Panels: <code>{escape(', '.join(diagnostics['panel_types']))}</code></p>"
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
        "<div class='card'><h3>Tunnels</h3>"
        f"{_tunnel_table(tunnels)}"
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
    direction_class = "split-horizontal" if orientation == "horizontal" else "split-vertical"
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
