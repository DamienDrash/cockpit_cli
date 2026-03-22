"""Local web admin HTTP server."""

from __future__ import annotations

from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

from cockpit.application.services.web_admin_service import WebAdminService


def _page(title: str, body: str, *, flash: str | None = None) -> str:
    flash_html = ""
    if flash:
        flash_html = f"<div class='flash'>{escape(flash)}</div>"
    nav = (
        "<nav>"
        "<a href='/'>Home</a>"
        "<a href='/datasources'>Datasources</a>"
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
                if parsed.path == "/":
                    self._html(_page("Cockpit Web Admin", _home_body(service), flash=flash))
                    return
                if parsed.path == "/datasources":
                    self._html(_page("Datasources", _datasource_body(service), flash=flash))
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
    if path.startswith("/plugins"):
        return "/plugins"
    if path.startswith("/layouts"):
        return "/layouts"
    return "/"


def _handle_post(service: WebAdminService, path: str, form: dict[str, str]) -> tuple[str, str]:
    if path == "/datasources/create":
        profile = service.create_datasource(form)
        return "/datasources", f"Created datasource {profile.name}."
    if path == "/datasources/delete":
        profile_id = form.get("profile_id", "")
        service.delete_datasource(profile_id)
        return "/datasources", f"Deleted datasource {profile_id}."
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
    raise ValueError(f"Unknown admin action '{path}'.")


def _home_body(service: WebAdminService) -> str:
    diagnostics = service.diagnostics()
    datasource_diag = diagnostics["datasources"]
    plugin_diag = diagnostics["plugins"]
    return (
        "<div class='grid'>"
        f"<div class='card'><h3>Datasources</h3><p>{escape(str(datasource_diag['total_profiles']))} total / {escape(str(datasource_diag['enabled_profiles']))} enabled</p></div>"
        f"<div class='card'><h3>Plugins</h3><p>{escape(str(plugin_diag['count']))} installed / {escape(str(plugin_diag['enabled']))} enabled</p></div>"
        f"<div class='card'><h3>Panels</h3><p>{escape(', '.join(diagnostics['panel_types']))}</p></div>"
        "</div>"
        "<p class='muted'>Use the admin pages to manage datasource profiles, plugin installs, layout variants, and runtime diagnostics.</p>"
    )


def _datasource_body(service: WebAdminService) -> str:
    profiles = service.list_datasources()
    rows = []
    for profile in profiles:
        inspect_result = service.inspect_datasource(profile.id)
        rows.append(
            "<tr>"
            f"<td><strong>{escape(profile.name)}</strong><br><span class='muted'>{escape(profile.id)}</span></td>"
            f"<td>{escape(profile.backend)}<br><span class='muted'>{escape(profile.connection_url or profile.target_ref or '(unset)')}</span></td>"
            f"<td>{escape(inspect_result.message or '')}</td>"
            f"<td>{escape(', '.join(profile.capabilities))}</td>"
            "<td>"
            f"<form class='inline' method='post' action='/datasources/delete'><input type='hidden' name='profile_id' value='{escape(profile.id)}'><button type='submit'>Delete</button></form>"
            "</td>"
            "</tr>"
        )
    return (
        "<div class='card'><h3>Create datasource</h3>"
        "<form method='post' action='/datasources/create'>"
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
        "</div><p><button type='submit'>Save datasource</button></p></form></div>"
        "<div class='card'><h3>Saved profiles</h3><table><thead><tr><th>Name</th><th>Backend</th><th>Status</th><th>Capabilities</th><th>Actions</th></tr></thead>"
        f"<tbody>{''.join(rows) if rows else '<tr><td colspan=\"5\">No datasource profiles saved.</td></tr>'}</tbody></table></div>"
    )


def _plugin_body(service: WebAdminService) -> str:
    plugins = service.list_plugins()
    rows = []
    for plugin in plugins:
        summary = plugin.manifest.get("summary", "")
        rows.append(
            "<tr>"
            f"<td><strong>{escape(plugin.name)}</strong><br><span class='muted'>{escape(plugin.module)}</span></td>"
            f"<td>{escape(plugin.requirement)}<br><span class='muted'>pin={escape(plugin.version_pin or '(none)')}</span></td>"
            f"<td>{escape(str(plugin.enabled))} / {escape(plugin.status)}</td>"
            f"<td>{escape(str(summary))}</td>"
            "<td>"
            f"<form class='inline' method='post' action='/plugins/update'><input type='hidden' name='plugin_id' value='{escape(plugin.id)}'><button type='submit'>Update</button></form> "
            f"<form class='inline' method='post' action='/plugins/toggle'><input type='hidden' name='plugin_id' value='{escape(plugin.id)}'><input type='hidden' name='enabled' value='{'0' if plugin.enabled else '1'}'><button type='submit'>{'Disable' if plugin.enabled else 'Enable'}</button></form> "
            f"<form class='inline' method='post' action='/plugins/remove'><input type='hidden' name='plugin_id' value='{escape(plugin.id)}'><button type='submit'>Remove</button></form>"
            "</td>"
            "</tr>"
        )
    return (
        "<div class='card'><h3>Install plugin</h3>"
        "<form method='post' action='/plugins/install'>"
        "<div class='grid'>"
        "<div><label>Name</label><input name='name'></div>"
        "<div><label>Module</label><input name='module' required></div>"
        "<div><label>Requirement / repo</label><input name='requirement' required placeholder='package-name or /path/to/plugin or git+https://...'></div>"
        "<div><label>Version pin</label><input name='version_pin' placeholder='1.2.3'></div>"
        "<div><label>Source label</label><input name='source'></div>"
        "</div><p><button type='submit'>Install plugin</button></p></form></div>"
        "<div class='card'><h3>Installed plugins</h3><table><thead><tr><th>Plugin</th><th>Requirement</th><th>Status</th><th>Summary</th><th>Actions</th></tr></thead>"
        f"<tbody>{''.join(rows) if rows else '<tr><td colspan=\"5\">No plugins installed.</td></tr>'}</tbody></table></div>"
    )


def _layout_body(service: WebAdminService) -> str:
    layouts = service.list_layouts()
    panels = service.available_panels()
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
    return "".join(blocks) or "<div class='card'>No layouts saved.</div>"


def _diagnostics_body(service: WebAdminService) -> str:
    diagnostics = service.diagnostics()
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
        "<div class='card'><h3>Plugins</h3>"
        f"<pre>{escape(str(diagnostics['plugins']))}</pre>"
        "</div>"
    )
