from dataclasses import dataclass
from threading import Thread
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import time
import unittest

from cockpit.infrastructure.web.admin_server import LocalWebAdminServer


@dataclass
class _NamedObject:
    name: str
    id: str = "obj-1"
    backend: str = "sqlite"
    connection_url: str | None = None
    target_ref: str | None = None
    capabilities: list[str] = None  # type: ignore[assignment]
    manifest: dict[str, object] = None  # type: ignore[assignment]
    requirement: str = "sample"
    version_pin: str | None = None
    enabled: bool = True
    status: str = "installed"

    def __post_init__(self) -> None:
        if self.capabilities is None:
            self.capabilities = ["can_query"]
        if self.manifest is None:
            self.manifest = {"summary": "sample"}


class FakeWebAdminService:
    def __init__(self) -> None:
        self.saved_pages: list[str] = []
        self.created_datasources: list[dict[str, object]] = []
        self.created_secrets: list[dict[str, object]] = []
        self.closed_tunnels: list[str] = []

    def diagnostics(self) -> dict[str, object]:
        return {
            "project_root": "/tmp/cockpit",
            "python": "3.11",
            "platform": "Linux",
            "command_count": 4,
            "panel_types": ["work", "db"],
            "datasources": {"total_profiles": 0, "enabled_profiles": 0, "backends": []},
            "secrets": {"total_entries": 1, "providers": ["env"], "keyring_available": True},
            "plugins": {
                "count": 0,
                "enabled": 0,
                "modules": [],
                "trusted_sources": ["git+https://github.com/"],
                "app_version": "0.1.0",
            },
            "tunnels": [
                {
                    "profile_id": "pg-main",
                    "target_ref": "deploy@example.com",
                    "remote_host": "db.internal",
                    "remote_port": 5432,
                    "local_port": 15432,
                    "alive": True,
                }
            ],
            "tools": {"git": True, "docker": True, "ssh": True},
        }

    def save_last_page(self, page: str) -> None:
        self.saved_pages.append(page)

    def list_datasources(self):
        return []

    def create_datasource(self, payload: dict[str, object]):
        self.created_datasources.append(dict(payload))
        return _NamedObject(name=payload.get("name", "New datasource"))

    def delete_datasource(self, profile_id: str) -> None:
        del profile_id

    def inspect_datasource(self, profile_id: str):
        del profile_id
        return _NamedObject(name="Inspection")

    def execute_datasource(self, profile_id: str, statement: str, *, operation: str):
        del profile_id, statement, operation
        return SimpleResult("Datasource command executed.")

    def last_datasource_result(self):
        return {"profile_id": "pg-main", "result": {"message": "ok"}}

    def list_secrets(self):
        return [_SecretObject()]

    def create_secret(self, payload: dict[str, object]):
        self.created_secrets.append(dict(payload))
        return _SecretObject(name=str(payload.get("name", "analytics-pass")))

    def delete_secret(self, name: str, *, purge_value: bool = False) -> None:
        del name, purge_value

    def list_plugins(self):
        return []

    def install_plugin(self, payload: dict[str, str]):
        del payload
        return _NamedObject(name="Plugin")

    def update_plugin(self, plugin_id: str):
        del plugin_id
        return _NamedObject(name="Plugin")

    def toggle_plugin(self, plugin_id: str, enabled: bool):
        del plugin_id, enabled
        return _NamedObject(name="Plugin")

    def pin_plugin(self, plugin_id: str, version_pin: str | None):
        del plugin_id, version_pin
        return _NamedObject(name="Plugin")

    def remove_plugin(self, plugin_id: str) -> None:
        del plugin_id

    def list_layouts(self):
        return []

    def clone_layout(self, source_layout_id: str, target_layout_id: str, name: str | None = None):
        del source_layout_id, target_layout_id, name
        return _NamedObject(name="Layout")

    def toggle_layout_tab(self, layout_id: str, tab_id: str):
        del layout_id, tab_id
        return _NamedObject(name="Layout")

    def set_layout_ratio(self, layout_id: str, tab_id: str, ratio: float):
        del layout_id, tab_id, ratio
        return _NamedObject(name="Layout")

    def add_panel_to_layout(self, layout_id: str, tab_id: str, panel_id: str, panel_type: str):
        del layout_id, tab_id, panel_id, panel_type
        return _NamedObject(name="Layout")

    def remove_panel_from_layout(self, layout_id: str, tab_id: str, panel_id: str):
        del layout_id, tab_id, panel_id
        return _NamedObject(name="Layout")

    def replace_panel_in_layout(
        self,
        layout_id: str,
        tab_id: str,
        existing_panel_id: str,
        replacement_panel_id: str,
        replacement_panel_type: str,
    ):
        del layout_id, tab_id, existing_panel_id, replacement_panel_id, replacement_panel_type
        return _NamedObject(name="Layout")

    def available_panels(self):
        return []

    def close_tunnel(self, profile_id: str) -> None:
        self.closed_tunnels.append(profile_id)


@dataclass
class _SecretObject:
    name: str = "analytics-pass"
    provider: str = "env"
    reference: dict[str, object] = None  # type: ignore[assignment]
    description: str | None = "DB password"

    def __post_init__(self) -> None:
        if self.reference is None:
            self.reference = {"provider": "env", "name": "ANALYTICS_DB_PASS"}


@dataclass
class SimpleResult:
    message: str


class LocalWebAdminServerTests(unittest.TestCase):
    def test_serves_pages_and_handles_post_actions(self) -> None:
        service = FakeWebAdminService()
        server = LocalWebAdminServer(service, host="127.0.0.1", port=0)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base_url = None
            for _ in range(50):
                base_url = server.listen_url()
                if base_url:
                    break
                time.sleep(0.05)
            self.assertIsNotNone(base_url)
            assert base_url is not None

            with urlopen(f"{base_url}/diagnostics") as response:
                body = response.read().decode("utf-8")
            self.assertIn("Diagnostics", body)
            self.assertIn("trusted_sources", body)

            with urlopen(f"{base_url}/plugins") as response:
                plugin_body = response.read().decode("utf-8")
            self.assertIn("git+https://github.com/", plugin_body)

            with urlopen(f"{base_url}/secrets") as response:
                secrets_body = response.read().decode("utf-8")
            self.assertIn("analytics-pass", secrets_body)

            request = Request(
                f"{base_url}/datasources/create",
                data=urlencode(
                    {
                        "name": "PG",
                        "backend": "postgres",
                        "connection_url": "postgresql://localhost/app",
                        "secret_refs_json": '{"DB_PASS":"env:APP_DB_PASS"}',
                        "options_json": '{"connect_args":{"sslmode":"require"}}',
                        "tags": "analytics, stage",
                    }
                ).encode("utf-8"),
                method="POST",
            )
            with urlopen(request) as response:
                redirected_body = response.read().decode("utf-8")

            self.assertIn("Created datasource PG.", redirected_body)
            self.assertEqual(service.created_datasources[0]["backend"], "postgres")
            self.assertEqual(
                service.created_datasources[0]["secret_refs_json"],
                '{"DB_PASS":"env:APP_DB_PASS"}',
            )

            execute_request = Request(
                f"{base_url}/datasources/execute",
                data=urlencode(
                    {
                        "profile_id": "pg-main",
                        "statement": "SELECT 1",
                        "operation": "query",
                    }
                ).encode("utf-8"),
                method="POST",
            )
            with urlopen(execute_request) as response:
                execute_body = response.read().decode("utf-8")
            self.assertIn("Datasource command executed.", execute_body)

            secret_request = Request(
                f"{base_url}/secrets/create",
                data=urlencode(
                    {
                        "name": "redis-pass",
                        "provider": "env",
                        "env_name": "REDIS_PASSWORD",
                    }
                ).encode("utf-8"),
                method="POST",
            )
            with urlopen(secret_request) as response:
                secret_body = response.read().decode("utf-8")
            self.assertIn("Saved secret reference redis-pass.", secret_body)
            self.assertEqual(service.created_secrets[0]["env_name"], "REDIS_PASSWORD")

            close_tunnel_request = Request(
                f"{base_url}/diagnostics/close-tunnel",
                data=urlencode({"profile_id": "pg-main"}).encode("utf-8"),
                method="POST",
            )
            with urlopen(close_tunnel_request) as response:
                diagnostics_body = response.read().decode("utf-8")
            self.assertIn("Closed tunnel for pg-main.", diagnostics_body)
            self.assertEqual(service.closed_tunnels, ["pg-main"])

            self.assertIn("/diagnostics", service.saved_pages)
            self.assertIn("/plugins", service.saved_pages)
            self.assertIn("/secrets", service.saved_pages)
            self.assertIn("/datasources", service.saved_pages)
        finally:
            server.shutdown()
            thread.join(timeout=2)
