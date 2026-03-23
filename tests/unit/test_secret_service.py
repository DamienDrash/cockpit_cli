from types import SimpleNamespace
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest

from cockpit.application.services.secret_service import SecretService
from cockpit.infrastructure.persistence.repositories import WebAdminStateRepository
from cockpit.infrastructure.persistence.sqlite_store import SQLiteStore


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, username: str, value: str) -> None:
        self.values[(service, username)] = value

    def delete_password(self, service: str, username: str) -> None:
        self.values.pop((service, username), None)


class SecretServiceTests(unittest.TestCase):
    def test_manages_env_file_and_keyring_secret_entries(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = SQLiteStore(Path(temp_dir) / "cockpit.db")
            service = SecretService(
                WebAdminStateRepository(store),
                keyring_backend=FakeKeyring(),
            )

            env_entry = service.upsert_entry(
                name="analytics-user",
                provider="env",
                env_name="ANALYTICS_DB_USER",
                description="DB user",
            )
            file_entry = service.upsert_entry(
                name="analytics-cert",
                provider="file",
                file_path="secrets/client.pem",
            )
            keyring_entry = service.upsert_entry(
                name="analytics-pass",
                provider="keyring",
                keyring_service="cockpit",
                keyring_username="analytics-pass",
                secret_value="topsecret",
            )

            self.assertEqual(env_entry.reference["name"], "ANALYTICS_DB_USER")
            self.assertEqual(file_entry.reference["path"], "secrets/client.pem")
            self.assertEqual(keyring_entry.reference["service"], "cockpit")
            self.assertEqual(service.lookup_reference("analytics-pass"), keyring_entry.reference)
            self.assertEqual(len(service.list_entries()), 3)
            self.assertEqual(service.diagnostics().total_entries, 3)
            self.assertEqual(keyring_entry.revision, 1)

            rotated = service.rotate_entry("analytics-pass", secret_value="newsecret")
            self.assertEqual(rotated.revision, 2)
            self.assertIsNotNone(rotated.rotated_at)
            self.assertEqual(service.diagnostics().rotated_entries, 1)

            service.delete_entry("analytics-pass", purge_value=True)
            self.assertIsNone(service.get_entry("analytics-pass"))
            store.close()
