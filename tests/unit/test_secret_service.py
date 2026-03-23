from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from cockpit.application.services.secret_service import SecretService
from cockpit.domain.models.secret import VaultProfile
from cockpit.infrastructure.persistence.repositories import WebAdminStateRepository
from cockpit.infrastructure.persistence.sqlite_store import SQLiteStore
from cockpit.infrastructure.secrets.cache_cipher import SecretCacheCipher
from cockpit.infrastructure.secrets.vault_client import VaultAuthResult, VaultLeaseResult


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, username: str, value: str) -> None:
        self.values[(service, username)] = value

    def delete_password(self, service: str, username: str) -> None:
        self.values.pop((service, username), None)


class FakeVaultClient:
    def __init__(self, profile: VaultProfile) -> None:
        self.profile = profile
        self.login_calls: list[tuple[str, object]] = []
        self.kv_reads: list[tuple[str, str, str]] = []
        self.kv_writes: list[tuple[str, str, dict[str, object]]] = []
        self.dynamic_calls: list[tuple[str, str]] = []
        self.transit_calls: list[tuple[str, str]] = []
        self.revoked_self = False
        self.revoked_leases: list[str] = []

    def health(self) -> dict[str, object]:
        return {"initialized": True, "sealed": False}

    def login_token(self, token: str) -> VaultAuthResult:
        self.login_calls.append(("token", token))
        return VaultAuthResult(
            token=token,
            token_accessor="acc-1",
            renewable=True,
            expires_at=datetime(2026, 3, 24, tzinfo=UTC),
            metadata={"display_name": "token"},
        )

    def login_approle(self, *, mount: str, role_id: str, secret_id: str) -> VaultAuthResult:
        self.login_calls.append(("approle", (mount, role_id, secret_id)))
        return VaultAuthResult(
            token="approle-token",
            token_accessor="acc-2",
            renewable=True,
            expires_at=datetime(2026, 3, 24, tzinfo=UTC),
            metadata={"display_name": "approle"},
        )

    def login_jwt(self, *, mount: str, role: str, jwt: str) -> VaultAuthResult:
        self.login_calls.append(("jwt", (mount, role, jwt)))
        return VaultAuthResult(
            token="jwt-token",
            token_accessor="acc-3",
            renewable=True,
            expires_at=datetime(2026, 3, 24, tzinfo=UTC),
            metadata={"display_name": "jwt"},
        )

    def kv_read(self, *, mount: str, path: str, token: str, version: int | None = None) -> dict[str, object]:
        del version
        self.kv_reads.append((mount, path, token))
        return {
            "data": {"password": "vault-secret", "username": "vault-user"},
            "metadata": {"version": 7},
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
        del token, cas
        self.kv_writes.append((mount, path, dict(data)))
        return {"written": True}

    def dynamic_credentials(self, *, mount: str, role: str, token: str) -> VaultLeaseResult:
        self.dynamic_calls.append((mount, role))
        return VaultLeaseResult(
            lease_id="lease-1",
            renewable=True,
            expires_at=datetime(2026, 3, 24, tzinfo=UTC),
            data={"username": "dyn-user", "password": "dyn-pass"},
            metadata={"token": token},
        )

    def transit_encrypt(self, *, mount: str, key_name: str, token: str, plaintext_b64: str) -> dict[str, object]:
        del token, plaintext_b64
        self.transit_calls.append(("encrypt", f"{mount}/{key_name}"))
        return {"data": {"ciphertext": "vault:v1:abcd"}}

    def transit_decrypt(self, *, mount: str, key_name: str, token: str, ciphertext: str) -> dict[str, object]:
        del token, ciphertext
        self.transit_calls.append(("decrypt", f"{mount}/{key_name}"))
        return {"data": {"plaintext": "c2VjcmV0"}}

    def transit_sign(self, *, mount: str, key_name: str, token: str, input_b64: str) -> dict[str, object]:
        del token, input_b64
        self.transit_calls.append(("sign", f"{mount}/{key_name}"))
        return {"data": {"signature": "vault:v1:signature"}}

    def transit_verify(
        self,
        *,
        mount: str,
        key_name: str,
        token: str,
        input_b64: str,
        signature: str,
    ) -> dict[str, object]:
        del token, input_b64, signature
        self.transit_calls.append(("verify", f"{mount}/{key_name}"))
        return {"data": {"valid": True}}

    def renew_self(self, *, token: str, increment_seconds: int | None = None) -> VaultAuthResult:
        del increment_seconds
        return VaultAuthResult(
            token=token,
            token_accessor="acc-renewed",
            renewable=True,
            expires_at=datetime(2026, 3, 25, tzinfo=UTC),
            metadata={"display_name": "renewed"},
        )

    def renew_lease(self, *, lease_id: str, token: str, increment_seconds: int | None = None) -> VaultLeaseResult:
        del token, increment_seconds
        return VaultLeaseResult(
            lease_id=lease_id,
            renewable=True,
            expires_at=datetime(2026, 3, 25, tzinfo=UTC),
            data={"username": "dyn-user", "password": "dyn-pass"},
            metadata={"renewed": True},
        )

    def revoke_lease(self, *, lease_id: str, token: str) -> None:
        del token
        self.revoked_leases.append(lease_id)

    def revoke_self(self, *, token: str) -> None:
        del token
        self.revoked_self = True


class SecretServiceTests(unittest.TestCase):
    def test_manages_local_secret_entries_and_vault_profiles(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = SQLiteStore(root / "cockpit.db")
            clients: dict[str, FakeVaultClient] = {}

            def factory(profile: VaultProfile) -> FakeVaultClient:
                client = clients.get(profile.id)
                if client is None:
                    client = FakeVaultClient(profile)
                    clients[profile.id] = client
                return client

            service = SecretService(
                WebAdminStateRepository(store),
                start=root,
                keyring_backend=FakeKeyring(),
                vault_client_factory=factory,
                cache_cipher=SecretCacheCipher(root / "cache.key"),
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
            profile = service.save_vault_profile(
                profile_id="ops-vault",
                name="Ops Vault",
                address="https://vault.internal:8200",
                auth_type="token",
                allow_local_cache=True,
            )
            vault_entry = service.upsert_entry(
                name="app-db-pass",
                provider="vault",
                vault_profile_id=profile.id,
                vault_kind="kv",
                vault_mount="kv",
                vault_path="apps/api",
                vault_field="password",
            )

            self.assertEqual(env_entry.reference["name"], "ANALYTICS_DB_USER")
            self.assertEqual(file_entry.reference["path"], "secrets/client.pem")
            self.assertEqual(keyring_entry.reference["service"], "cockpit")
            self.assertEqual(vault_entry.reference["profile_id"], "ops-vault")
            self.assertEqual(len(service.list_entries()), 4)
            self.assertEqual(len(service.list_vault_profiles()), 1)
            self.assertEqual(service.diagnostics().vault_profiles, 1)

            rotated = service.rotate_entry("analytics-pass", secret_value="newsecret")
            self.assertEqual(rotated.revision, 2)
            self.assertIsNotNone(rotated.rotated_at)

            service.delete_entry("analytics-pass", purge_value=True)
            self.assertIsNone(service.get_entry("analytics-pass"))
            store.close()

    def test_authenticates_resolves_vault_references_and_tracks_leases(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = SQLiteStore(root / "cockpit.db")
            clients: dict[str, FakeVaultClient] = {}

            def factory(profile: VaultProfile) -> FakeVaultClient:
                client = clients.get(profile.id)
                if client is None:
                    client = FakeVaultClient(profile)
                    clients[profile.id] = client
                return client

            service = SecretService(
                WebAdminStateRepository(store),
                start=root,
                keyring_backend=FakeKeyring(),
                vault_client_factory=factory,
                cache_cipher=SecretCacheCipher(root / "cache.key"),
            )
            service.save_vault_profile(
                profile_id="ops-vault",
                name="Ops Vault",
                address="https://vault.internal:8200",
                auth_type="token",
                allow_local_cache=True,
            )
            session = service.login_vault_profile("ops-vault", token="root-token")
            self.assertEqual(session.profile_id, "ops-vault")

            kv_value = service.resolve_vault_reference(
                {
                    "provider": "vault",
                    "kind": "kv",
                    "profile_id": "ops-vault",
                    "mount": "kv",
                    "path": "apps/api",
                    "field": "password",
                }
            )
            dynamic_value = service.resolve_vault_reference(
                {
                    "provider": "vault",
                    "kind": "dynamic",
                    "profile_id": "ops-vault",
                    "mount": "database",
                    "role": "app",
                    "field": "username",
                }
            )
            transit_result = service.transit_operation(
                profile_id="ops-vault",
                mount="transit",
                key_name="app-key",
                operation="encrypt",
                value="secret",
            )
            renewed = service.renew_vault_lease("lease-1")
            service.rotate_entry("dynamic-test", secret_value="ignored") if False else None

            self.assertEqual(kv_value, "vault-secret")
            self.assertEqual(dynamic_value, "dyn-user")
            self.assertEqual(transit_result["ciphertext"], "vault:v1:abcd")
            self.assertEqual(renewed.lease_id, "lease-1")
            self.assertEqual(len(service.list_vault_leases()), 1)
            self.assertEqual(service.vault_profile_health("ops-vault")["profile_id"], "ops-vault")

            service.logout_vault_profile("ops-vault", revoke=True)
            self.assertTrue(clients["ops-vault"].revoked_self)
            store.close()


if __name__ == "__main__":
    unittest.main()
