"""Managed secret registry with Vault-first runtime support."""

from __future__ import annotations

from base64 import b64decode, b64encode
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Callable

from cockpit.datasources.models.secret import (
    ManagedSecretEntry,
    VaultLease,
    VaultProfile,
    VaultSession,
)
from cockpit.workspace.repositories import WebAdminStateRepository
from cockpit.infrastructure.secrets.cache_cipher import SecretCacheCipher
from cockpit.datasources.adapters.vault_client import (
    VaultAuthResult,
    VaultHttpClient,
    VaultLeaseResult,
)
from cockpit.core.config import state_dir
from cockpit.core.utils import make_id, utc_now

try:  # pragma: no cover - optional dependency guard
    import keyring
    from keyring.errors import PasswordDeleteError
except Exception:  # pragma: no cover - optional dependency guard
    keyring = None
    PasswordDeleteError = Exception


SECRET_STATE_PREFIX = "secret:"
VAULT_PROFILE_PREFIX = "vault_profile:"
VAULT_LEASE_PREFIX = "vault_lease:"
VAULT_CACHE_PREFIX = "vault_cache:"


@dataclass(slots=True, frozen=True)
class SecretDiagnostics:
    total_entries: int
    providers: list[str]
    keyring_available: bool
    rotated_entries: int
    vault_profiles: int
    active_vault_sessions: int
    cached_vault_sessions: int
    renewable_leases: int
    local_cache_available: bool
    primary_provider: str


class SecretService:
    """Persist managed secret references and provide Vault-backed resolution."""

    def __init__(
        self,
        repository: WebAdminStateRepository,
        *,
        start: Path | None = None,
        keyring_backend: object | None = None,
        vault_client_factory: Callable[[VaultProfile], VaultHttpClient] | None = None,
        cache_cipher: SecretCacheCipher | None = None,
    ) -> None:
        self._repository = repository
        self._keyring = keyring_backend if keyring_backend is not None else keyring
        self._vault_client_factory = vault_client_factory or self._default_vault_client
        cache_path = state_dir(start) / "vault-session.key"
        self._cache_cipher = cache_cipher or SecretCacheCipher(cache_path)
        self._vault_sessions: dict[str, VaultSession] = {}
        self._vault_tokens: dict[str, str] = {}

    def list_entries(self) -> list[ManagedSecretEntry]:
        entries: list[ManagedSecretEntry] = []
        for _key, payload in self._repository.list_prefix(SECRET_STATE_PREFIX):
            entry = self._entry_from_payload(payload)
            if entry is not None:
                entries.append(entry)
        return entries

    def get_entry(self, name: str) -> ManagedSecretEntry | None:
        payload = self._repository.get(self._entry_key(name))
        return self._entry_from_payload(payload) if payload is not None else None

    def lookup_reference(self, name: str) -> dict[str, object] | None:
        entry = self.get_entry(name)
        if entry is None:
            return None
        return dict(entry.reference)

    def upsert_entry(
        self,
        *,
        name: str,
        provider: str,
        description: str | None = None,
        tags: list[str] | None = None,
        env_name: str | None = None,
        file_path: str | None = None,
        keyring_service: str | None = None,
        keyring_username: str | None = None,
        secret_value: str | None = None,
        vault_profile_id: str | None = None,
        vault_kind: str | None = None,
        vault_mount: str | None = None,
        vault_path: str | None = None,
        vault_field: str | None = None,
        vault_version: int | None = None,
        vault_role: str | None = None,
    ) -> ManagedSecretEntry:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("Secret name must not be empty.")
        existing = self.get_entry(normalized_name)
        normalized_provider = provider.strip().lower()
        rotated_at: datetime | None = (
            existing.rotated_at if existing is not None else None
        )
        reference = self._reference_from_inputs(
            provider=normalized_provider,
            env_name=env_name,
            file_path=file_path,
            keyring_service=keyring_service,
            keyring_username=keyring_username,
            secret_value=secret_value,
            vault_profile_id=vault_profile_id,
            vault_kind=vault_kind,
            vault_mount=vault_mount,
            vault_path=vault_path,
            vault_field=vault_field,
            vault_version=vault_version,
            vault_role=vault_role,
        )
        if normalized_provider == "keyring" and secret_value:
            rotated_at = utc_now()
        timestamp = utc_now()
        entry = ManagedSecretEntry(
            name=normalized_name,
            provider=normalized_provider,
            reference=reference,
            description=description.strip()
            if isinstance(description, str) and description.strip()
            else None,
            tags=[
                item.strip()
                for item in (tags or [])
                if isinstance(item, str) and item.strip()
            ],
            created_at=existing.created_at if existing is not None else timestamp,
            updated_at=timestamp,
            rotated_at=rotated_at,
            revision=(existing.revision + 1) if existing is not None else 1,
        )
        self._repository.save(self._entry_key(normalized_name), entry.to_dict())
        return entry

    def rotate_entry(self, name: str, *, secret_value: str) -> ManagedSecretEntry:
        entry = self.get_entry(name)
        if entry is None:
            raise LookupError(f"Managed secret '{name}' was not found.")
        if entry.provider == "keyring":
            service = str(entry.reference.get("service", "")).strip()
            username = str(entry.reference.get("username", "")).strip()
            if not service or not username:
                raise ValueError(
                    "Managed keyring secret is missing its service or username."
                )
            self._set_keyring_value(service, username, secret_value)
        elif entry.provider == "vault":
            reference = dict(entry.reference)
            if str(reference.get("kind", "kv")).strip().lower() != "kv":
                raise ValueError("Only Vault KV secrets support direct rotation.")
            profile_id = str(reference.get("profile_id", "")).strip()
            mount = str(reference.get("mount", "")).strip()
            path = str(reference.get("path", "")).strip()
            field = str(reference.get("field", "")).strip()
            if not profile_id or not mount or not path or not field:
                raise ValueError(
                    "Vault KV secret is missing its profile, mount, path, or field."
                )
            profile = self.require_vault_profile(profile_id)
            self._ensure_vault_session(profile.id)
            token = self._require_token(profile.id)
            self._client_for_profile(profile).kv_write(
                mount=mount,
                path=path,
                token=token,
                data={field: secret_value},
                cas=(
                    int(reference["version"])
                    if isinstance(reference.get("version"), int)
                    else None
                ),
            )
        else:
            raise ValueError(
                "Only keyring-backed or Vault KV secrets support direct rotation."
            )

        rotated = ManagedSecretEntry(
            name=entry.name,
            provider=entry.provider,
            reference=dict(entry.reference),
            description=entry.description,
            tags=list(entry.tags),
            created_at=entry.created_at,
            updated_at=utc_now(),
            rotated_at=utc_now(),
            revision=entry.revision + 1,
        )
        self._repository.save(self._entry_key(name), rotated.to_dict())
        return rotated

    def delete_entry(self, name: str, *, purge_value: bool = False) -> None:
        entry = self.get_entry(name)
        if entry is None:
            return
        if purge_value and entry.provider == "keyring":
            service = str(entry.reference.get("service", "")).strip()
            username = str(entry.reference.get("username", "")).strip()
            if service and username:
                self._delete_keyring_value(service, username)
        self._repository.delete(self._entry_key(name))

    def list_vault_profiles(self) -> list[VaultProfile]:
        profiles: list[VaultProfile] = []
        for _key, payload in self._repository.list_prefix(VAULT_PROFILE_PREFIX):
            profile = self._profile_from_payload(payload)
            if profile is not None:
                profiles.append(profile)
        return profiles

    def get_vault_profile(self, profile_id: str) -> VaultProfile | None:
        payload = self._repository.get(self._vault_profile_key(profile_id))
        return self._profile_from_payload(payload) if payload is not None else None

    def require_vault_profile(self, profile_id: str) -> VaultProfile:
        profile = self.get_vault_profile(profile_id)
        if profile is None:
            raise LookupError(f"Vault profile '{profile_id}' was not found.")
        return profile

    def save_vault_profile(
        self,
        *,
        profile_id: str | None,
        name: str,
        address: str,
        auth_type: str,
        auth_mount: str | None = None,
        role_name: str | None = None,
        namespace: str | None = None,
        description: str | None = None,
        verify_tls: bool = True,
        ca_cert_path: str | None = None,
        allow_local_cache: bool = False,
        cache_ttl_seconds: int = 3600,
        risk_level: str = "dev",
        tags: list[str] | None = None,
    ) -> VaultProfile:
        identifier = (profile_id or make_id("vault")).strip()
        if not identifier:
            raise ValueError("Vault profile id must not be empty.")
        if not name.strip():
            raise ValueError("Vault profile name must not be empty.")
        if not address.strip():
            raise ValueError("Vault address must not be empty.")
        existing = self.get_vault_profile(identifier)
        timestamp = utc_now()
        profile = VaultProfile(
            id=identifier,
            name=name.strip(),
            address=address.strip().rstrip("/"),
            auth_type=auth_type.strip().lower() or "token",
            auth_mount=auth_mount.strip()
            if isinstance(auth_mount, str) and auth_mount.strip()
            else None,
            role_name=role_name.strip()
            if isinstance(role_name, str) and role_name.strip()
            else None,
            namespace=namespace.strip()
            if isinstance(namespace, str) and namespace.strip()
            else None,
            description=description.strip()
            if isinstance(description, str) and description.strip()
            else None,
            verify_tls=bool(verify_tls),
            ca_cert_path=ca_cert_path.strip()
            if isinstance(ca_cert_path, str) and ca_cert_path.strip()
            else None,
            allow_local_cache=bool(allow_local_cache),
            cache_ttl_seconds=max(int(cache_ttl_seconds or 0), 0) or 3600,
            risk_level=risk_level.strip()
            if isinstance(risk_level, str) and risk_level.strip()
            else "dev",
            tags=[
                item.strip()
                for item in (tags or [])
                if isinstance(item, str) and item.strip()
            ],
            created_at=existing.created_at if existing is not None else timestamp,
            updated_at=timestamp,
        )
        self._repository.save(self._vault_profile_key(identifier), profile.to_dict())
        return profile

    def delete_vault_profile(self, profile_id: str, *, revoke: bool = False) -> None:
        if revoke:
            self.logout_vault_profile(profile_id, revoke=True)
        else:
            self._clear_vault_runtime(profile_id)
        self._repository.delete(self._vault_profile_key(profile_id))

    def list_vault_sessions(self) -> list[VaultSession]:
        sessions: list[VaultSession] = []
        for profile in self.list_vault_profiles():
            session = self._vault_sessions.get(profile.id)
            if session is not None:
                sessions.append(session)
                continue
            cached = self._load_cached_session(profile)
            if cached is not None:
                sessions.append(cached)
        return sessions

    def list_vault_leases(self) -> list[VaultLease]:
        leases: list[VaultLease] = []
        for _key, payload in self._repository.list_prefix(VAULT_LEASE_PREFIX):
            lease = self._lease_from_payload(payload)
            if lease is not None:
                leases.append(lease)
        return leases

    def login_vault_profile(
        self,
        profile_id: str,
        *,
        token: str | None = None,
        role_id: str | None = None,
        secret_id: str | None = None,
        jwt: str | None = None,
    ) -> VaultSession:
        profile = self.require_vault_profile(profile_id)
        client = self._client_for_profile(profile)
        auth_type = profile.auth_type
        if auth_type == "token":
            raw_token = (token or "").strip()
            if not raw_token:
                raise ValueError("Vault token auth requires a token.")
            auth_result = client.login_token(raw_token)
        elif auth_type == "approle":
            mount = profile.auth_mount or "approle"
            raw_role_id = (role_id or "").strip()
            raw_secret_id = (secret_id or "").strip()
            if not raw_role_id or not raw_secret_id:
                raise ValueError("Vault AppRole auth requires role_id and secret_id.")
            auth_result = client.login_approle(
                mount=mount,
                role_id=raw_role_id,
                secret_id=raw_secret_id,
            )
        elif auth_type in {"jwt", "oidc"}:
            mount = profile.auth_mount or "jwt"
            role = (profile.role_name or "").strip()
            raw_jwt = (jwt or token or "").strip()
            if not role or not raw_jwt:
                raise ValueError(
                    "Vault JWT/OIDC auth requires a configured role and a JWT token."
                )
            auth_result = client.login_jwt(
                mount=mount,
                role=role,
                jwt=raw_jwt,
            )
        else:
            raise ValueError(f"Unsupported Vault auth type '{auth_type}'.")
        session = self._session_from_auth_result(profile, auth_result)
        self._vault_sessions[profile.id] = session
        self._vault_tokens[profile.id] = auth_result.token
        self._store_cached_session(profile, auth_result, session)
        return session

    def logout_vault_profile(self, profile_id: str, *, revoke: bool = False) -> None:
        session = self._vault_sessions.get(profile_id)
        token = self._vault_tokens.get(profile_id)
        profile = self.get_vault_profile(profile_id)
        if revoke and session is not None and token and profile is not None:
            client = self._client_for_profile(profile)
            client.revoke_self(token=token)
        self._clear_vault_runtime(profile_id)

    def vault_profile_health(self, profile_id: str) -> dict[str, object]:
        profile = self.require_vault_profile(profile_id)
        client = self._client_for_profile(profile)
        payload = client.health()
        session = self._vault_sessions.get(profile_id) or self._load_cached_session(
            profile
        )
        return {
            "profile_id": profile.id,
            "name": profile.name,
            "address": profile.address,
            "auth_type": profile.auth_type,
            "health": payload,
            "session": session.to_dict() if session is not None else None,
        }

    def resolve_vault_reference(
        self,
        reference: dict[str, object],
        *,
        resolution_cache: dict[str, object] | None = None,
    ) -> str:
        profile_id = str(reference.get("profile_id", "")).strip()
        if not profile_id:
            raise ValueError("Vault references require a profile_id.")
        profile = self.require_vault_profile(profile_id)
        client = self._client_for_profile(profile)
        self._ensure_vault_session(profile.id)
        token = self._require_token(profile.id)
        kind = str(reference.get("kind", "kv")).strip().lower() or "kv"
        if kind == "kv":
            mount = str(reference.get("mount", "")).strip()
            path = str(reference.get("path", "")).strip()
            field = str(reference.get("field", "")).strip()
            version = reference.get("version")
            if not mount or not path or not field:
                raise ValueError("Vault KV references require mount, path, and field.")
            payload = client.kv_read(
                mount=mount,
                path=path,
                token=token,
                version=int(version) if isinstance(version, int) else None,
            )
            data = payload.get("data", {})
            if not isinstance(data, dict) or field not in data:
                raise ValueError(
                    f"Vault KV field '{field}' was not found at {mount}/{path}."
                )
            value = data[field]
            return str(value)
        if kind == "dynamic":
            mount = str(reference.get("mount", "")).strip()
            role = str(reference.get("role", "")).strip()
            field = str(reference.get("field", "")).strip()
            if not mount or not role or not field:
                raise ValueError(
                    "Vault dynamic references require mount, role, and field."
                )
            cache_key = f"dynamic::{profile.id}::{mount}::{role}"
            lease_result: VaultLeaseResult | None = None
            if resolution_cache is not None:
                cached = resolution_cache.get(cache_key)
                if isinstance(cached, VaultLeaseResult):
                    lease_result = cached
            if lease_result is None:
                lease_result = client.dynamic_credentials(
                    mount=mount,
                    role=role,
                    token=token,
                )
                self._record_lease(
                    profile.id,
                    kind="dynamic",
                    mount=mount,
                    path=f"creds/{role}",
                    result=lease_result,
                )
                if resolution_cache is not None:
                    resolution_cache[cache_key] = lease_result
            if field not in lease_result.data:
                raise ValueError(
                    f"Vault dynamic field '{field}' was not found in lease {lease_result.lease_id or '(anonymous)'}."
                )
            return str(lease_result.data[field])
        raise ValueError(f"Unsupported Vault reference kind '{kind}'.")

    def transit_operation(
        self,
        *,
        profile_id: str,
        mount: str,
        key_name: str,
        operation: str,
        value: str,
        signature: str | None = None,
    ) -> dict[str, object]:
        profile = self.require_vault_profile(profile_id)
        self._ensure_vault_session(profile.id)
        token = self._require_token(profile.id)
        client = self._client_for_profile(profile)
        normalized_operation = operation.strip().lower()
        if normalized_operation == "encrypt":
            plaintext_b64 = b64encode(value.encode("utf-8")).decode("utf-8")
            payload = client.transit_encrypt(
                mount=mount,
                key_name=key_name,
                token=token,
                plaintext_b64=plaintext_b64,
            )
            data = payload.get("data", {})
            return {"operation": "encrypt", "ciphertext": data.get("ciphertext")}
        if normalized_operation == "decrypt":
            payload = client.transit_decrypt(
                mount=mount,
                key_name=key_name,
                token=token,
                ciphertext=value,
            )
            data = payload.get("data", {})
            plaintext_b64 = str(data.get("plaintext", ""))
            decoded = (
                b64decode(plaintext_b64.encode("utf-8")).decode("utf-8")
                if plaintext_b64
                else ""
            )
            return {"operation": "decrypt", "plaintext": decoded}
        if normalized_operation == "sign":
            input_b64 = b64encode(value.encode("utf-8")).decode("utf-8")
            payload = client.transit_sign(
                mount=mount,
                key_name=key_name,
                token=token,
                input_b64=input_b64,
            )
            data = payload.get("data", {})
            return {"operation": "sign", "signature": data.get("signature")}
        if normalized_operation == "verify":
            input_b64 = b64encode(value.encode("utf-8")).decode("utf-8")
            payload = client.transit_verify(
                mount=mount,
                key_name=key_name,
                token=token,
                input_b64=input_b64,
                signature=signature or "",
            )
            data = payload.get("data", {})
            return {"operation": "verify", "valid": bool(data.get("valid", False))}
        raise ValueError(f"Unsupported transit operation '{operation}'.")

    def renew_vault_lease(
        self, lease_id: str, *, increment_seconds: int | None = None
    ) -> VaultLease:
        lease = self._require_lease(lease_id)
        self._ensure_vault_session(lease.profile_id)
        token = self._require_token(lease.profile_id)
        profile = self.require_vault_profile(lease.profile_id)
        result = self._client_for_profile(profile).renew_lease(
            lease_id=lease_id,
            token=token,
            increment_seconds=increment_seconds,
        )
        renewed = VaultLease(
            lease_id=lease.lease_id,
            profile_id=lease.profile_id,
            source_kind=lease.source_kind,
            mount=lease.mount,
            path=lease.path,
            renewable=result.renewable,
            expires_at=result.expires_at,
            created_at=lease.created_at,
            updated_at=utc_now(),
            metadata={**lease.metadata, **result.metadata},
        )
        self._repository.save(self._vault_lease_key(lease_id), renewed.to_dict())
        return renewed

    def revoke_vault_lease(self, lease_id: str) -> None:
        lease = self._require_lease(lease_id)
        self._ensure_vault_session(lease.profile_id)
        token = self._require_token(lease.profile_id)
        profile = self.require_vault_profile(lease.profile_id)
        self._client_for_profile(profile).revoke_lease(lease_id=lease_id, token=token)
        self._repository.delete(self._vault_lease_key(lease_id))

    def diagnostics(self) -> SecretDiagnostics:
        entries = self.list_entries()
        profiles = self.list_vault_profiles()
        sessions = self.list_vault_sessions()
        leases = self.list_vault_leases()
        return SecretDiagnostics(
            total_entries=len(entries),
            providers=sorted({entry.provider for entry in entries}),
            keyring_available=self._keyring is not None,
            rotated_entries=sum(1 for entry in entries if entry.rotated_at is not None),
            vault_profiles=len(profiles),
            active_vault_sessions=sum(
                1 for session in sessions if session.source == "live"
            ),
            cached_vault_sessions=sum(1 for session in sessions if session.cached),
            renewable_leases=sum(1 for lease in leases if lease.renewable),
            local_cache_available=self._cache_cipher.available,
            primary_provider="vault",
        )

    def _reference_from_inputs(
        self,
        *,
        provider: str,
        env_name: str | None,
        file_path: str | None,
        keyring_service: str | None,
        keyring_username: str | None,
        secret_value: str | None,
        vault_profile_id: str | None,
        vault_kind: str | None,
        vault_mount: str | None,
        vault_path: str | None,
        vault_field: str | None,
        vault_version: int | None,
        vault_role: str | None,
    ) -> dict[str, object]:
        if provider == "env":
            env_key = (env_name or "").strip()
            if not env_key:
                raise ValueError(
                    "Managed env secrets require an environment variable name."
                )
            return {"provider": "env", "name": env_key}
        if provider == "file":
            path = (file_path or "").strip()
            if not path:
                raise ValueError("Managed file secrets require a path.")
            return {"provider": "file", "path": path}
        if provider == "keyring":
            service = (keyring_service or "cockpit").strip()
            username = (keyring_username or "").strip()
            if not service or not username:
                raise ValueError(
                    "Managed keyring secrets require a service and username."
                )
            if secret_value:
                self._set_keyring_value(service, username, secret_value)
            return {"provider": "keyring", "service": service, "username": username}
        if provider == "vault":
            profile_id = (vault_profile_id or "").strip()
            mount = (vault_mount or "").strip()
            kind = (vault_kind or "kv").strip().lower()
            field = (vault_field or "").strip()
            if not profile_id or not mount:
                raise ValueError("Vault secrets require a profile and mount.")
            self.require_vault_profile(profile_id)
            if kind == "kv":
                path = (vault_path or "").strip()
                if not path or not field:
                    raise ValueError("Vault KV secrets require a path and field.")
                reference: dict[str, object] = {
                    "provider": "vault",
                    "kind": "kv",
                    "profile_id": profile_id,
                    "mount": mount,
                    "path": path,
                    "field": field,
                }
                if isinstance(vault_version, int) and vault_version > 0:
                    reference["version"] = vault_version
                return reference
            if kind == "dynamic":
                role = (vault_role or vault_path or "").strip()
                if not role or not field:
                    raise ValueError("Vault dynamic secrets require a role and field.")
                return {
                    "provider": "vault",
                    "kind": "dynamic",
                    "profile_id": profile_id,
                    "mount": mount,
                    "role": role,
                    "field": field,
                }
            raise ValueError(
                "Managed Vault secrets only support kv or dynamic references."
            )
        raise ValueError(
            "Managed secrets only support env, file, keyring, or vault providers."
        )

    @staticmethod
    def _entry_key(name: str) -> str:
        return f"{SECRET_STATE_PREFIX}{name}"

    @staticmethod
    def _vault_profile_key(profile_id: str) -> str:
        return f"{VAULT_PROFILE_PREFIX}{profile_id}"

    @staticmethod
    def _vault_lease_key(lease_id: str) -> str:
        return f"{VAULT_LEASE_PREFIX}{lease_id}"

    @staticmethod
    def _vault_cache_key(profile_id: str) -> str:
        return f"{VAULT_CACHE_PREFIX}{profile_id}"

    def _client_for_profile(self, profile: VaultProfile) -> VaultHttpClient:
        return self._vault_client_factory(profile)

    @staticmethod
    def _default_vault_client(profile: VaultProfile) -> VaultHttpClient:
        return VaultHttpClient(
            address=profile.address,
            namespace=profile.namespace,
            verify_tls=profile.verify_tls,
            ca_cert_path=profile.ca_cert_path,
        )

    def _set_keyring_value(self, service: str, username: str, value: str) -> None:
        if self._keyring is None:
            raise ValueError("The optional 'keyring' dependency is not installed.")
        self._keyring.set_password(service, username, value)

    def _delete_keyring_value(self, service: str, username: str) -> None:
        if self._keyring is None:
            return
        try:
            self._keyring.delete_password(service, username)
        except PasswordDeleteError:
            return

    def _session_from_auth_result(
        self, profile: VaultProfile, auth: VaultAuthResult
    ) -> VaultSession:
        return VaultSession(
            profile_id=profile.id,
            auth_type=profile.auth_type,
            token_accessor=auth.token_accessor,
            renewable=auth.renewable,
            expires_at=auth.expires_at,
            created_at=utc_now(),
            updated_at=utc_now(),
            source="live",
            cached=False,
            last_error=None,
        )

    def _store_cached_session(
        self,
        profile: VaultProfile,
        auth: VaultAuthResult,
        session: VaultSession,
    ) -> None:
        if not profile.allow_local_cache or not self._cache_cipher.available:
            return
        payload = {
            "token": auth.token,
            "token_accessor": auth.token_accessor,
            "renewable": auth.renewable,
            "expires_at": auth.expires_at.isoformat() if auth.expires_at else None,
            "auth_type": profile.auth_type,
            "cached_at": utc_now().isoformat(),
        }
        encrypted = self._cache_cipher.encrypt(json.dumps(payload, sort_keys=True))
        self._repository.save(
            self._vault_cache_key(profile.id),
            {
                "encrypted": encrypted,
                "profile_id": profile.id,
                "expires_at": session.expires_at.isoformat()
                if session.expires_at
                else None,
            },
        )

    def _load_cached_session(self, profile: VaultProfile) -> VaultSession | None:
        payload = self._repository.get(self._vault_cache_key(profile.id))
        if not isinstance(payload, dict):
            return None
        encrypted = payload.get("encrypted")
        if not isinstance(encrypted, str) or not encrypted:
            return None
        if not self._cache_cipher.available:
            return None
        try:
            decrypted = json.loads(self._cache_cipher.decrypt(encrypted))
        except Exception:
            return None
        if not isinstance(decrypted, dict):
            return None
        token = decrypted.get("token")
        if not isinstance(token, str) or not token:
            return None
        expires_at = self._decode_datetime(decrypted.get("expires_at"))
        now = datetime.now(UTC)
        if expires_at is not None and expires_at <= now:
            self._repository.delete(self._vault_cache_key(profile.id))
            return None
        session = VaultSession(
            profile_id=profile.id,
            auth_type=str(decrypted.get("auth_type", profile.auth_type)),
            token_accessor=(
                str(decrypted["token_accessor"])
                if decrypted.get("token_accessor") is not None
                else None
            ),
            renewable=bool(decrypted.get("renewable", False)),
            expires_at=expires_at,
            created_at=self._decode_datetime(decrypted.get("cached_at")) or now,
            updated_at=now,
            source="cache",
            cached=True,
        )
        self._vault_sessions[profile.id] = session
        self._vault_tokens[profile.id] = token
        return session

    def _ensure_vault_session(self, profile_id: str) -> VaultSession:
        session = self._vault_sessions.get(profile_id)
        profile = self.require_vault_profile(profile_id)
        if session is None:
            session = self._load_cached_session(profile)
        if session is None:
            raise RuntimeError(
                f"Vault profile '{profile.name}' is not authenticated. Login through the web admin first."
            )
        token = self._require_token(profile_id)
        if session.expires_at is not None and session.expires_at <= datetime.now(UTC):
            if session.renewable:
                renewed = self._client_for_profile(profile).renew_self(token=token)
                session = self._session_from_auth_result(profile, renewed)
                self._vault_sessions[profile.id] = session
                self._vault_tokens[profile.id] = renewed.token
                self._store_cached_session(profile, renewed, session)
            else:
                self._clear_vault_runtime(profile_id)
                raise RuntimeError(f"Vault session for '{profile.name}' has expired.")
        return session

    def _record_lease(
        self,
        profile_id: str,
        *,
        kind: str,
        mount: str,
        path: str,
        result: VaultLeaseResult,
    ) -> VaultLease:
        lease = VaultLease(
            lease_id=result.lease_id or make_id("lease"),
            profile_id=profile_id,
            source_kind=kind,
            mount=mount,
            path=path,
            renewable=result.renewable,
            expires_at=result.expires_at,
            created_at=utc_now(),
            updated_at=utc_now(),
            metadata=dict(result.metadata),
        )
        self._repository.save(self._vault_lease_key(lease.lease_id), lease.to_dict())
        return lease

    def _require_lease(self, lease_id: str) -> VaultLease:
        payload = self._repository.get(self._vault_lease_key(lease_id))
        lease = self._lease_from_payload(payload)
        if lease is None:
            raise LookupError(f"Vault lease '{lease_id}' was not found.")
        return lease

    def _require_token(self, profile_id: str) -> str:
        token = self._vault_tokens.get(profile_id)
        if not token:
            raise RuntimeError(
                f"Vault session token for '{profile_id}' is not available."
            )
        return token

    def _clear_vault_runtime(self, profile_id: str) -> None:
        self._vault_sessions.pop(profile_id, None)
        self._vault_tokens.pop(profile_id, None)
        self._repository.delete(self._vault_cache_key(profile_id))
        for lease in self.list_vault_leases():
            if lease.profile_id == profile_id:
                self._repository.delete(self._vault_lease_key(lease.lease_id))

    @staticmethod
    def _entry_from_payload(
        payload: dict[str, object] | None,
    ) -> ManagedSecretEntry | None:
        if not isinstance(payload, dict):
            return None
        reference = payload.get("reference", {})
        if not isinstance(reference, dict):
            reference = {}
        name = payload.get("name")
        provider = payload.get("provider")
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(provider, str)
            or not provider
        ):
            return None
        return ManagedSecretEntry(
            name=name,
            provider=provider,
            reference={str(key): value for key, value in reference.items()},
            description=str(payload["description"])
            if payload.get("description") is not None
            else None,
            tags=[
                str(item) for item in payload.get("tags", []) if isinstance(item, str)
            ],
            created_at=SecretService._decode_datetime(payload.get("created_at")),
            updated_at=SecretService._decode_datetime(payload.get("updated_at")),
            rotated_at=SecretService._decode_datetime(payload.get("rotated_at")),
            revision=int(payload.get("revision", 1) or 1),
        )

    @staticmethod
    def _profile_from_payload(payload: dict[str, object] | None) -> VaultProfile | None:
        if not isinstance(payload, dict):
            return None
        profile_id = payload.get("id")
        name = payload.get("name")
        address = payload.get("address")
        auth_type = payload.get("auth_type")
        if not all(
            isinstance(item, str) and item
            for item in (profile_id, name, address, auth_type)
        ):
            return None
        return VaultProfile(
            id=profile_id,
            name=name,
            address=address,
            auth_type=auth_type,
            auth_mount=str(payload["auth_mount"])
            if payload.get("auth_mount") is not None
            else None,
            role_name=str(payload["role_name"])
            if payload.get("role_name") is not None
            else None,
            namespace=str(payload["namespace"])
            if payload.get("namespace") is not None
            else None,
            description=str(payload["description"])
            if payload.get("description") is not None
            else None,
            verify_tls=bool(payload.get("verify_tls", True)),
            ca_cert_path=str(payload["ca_cert_path"])
            if payload.get("ca_cert_path") is not None
            else None,
            allow_local_cache=bool(payload.get("allow_local_cache", False)),
            cache_ttl_seconds=max(
                int(payload.get("cache_ttl_seconds", 3600) or 3600), 1
            ),
            risk_level=str(payload.get("risk_level", "dev")),
            tags=[
                str(item) for item in payload.get("tags", []) if isinstance(item, str)
            ],
            created_at=SecretService._decode_datetime(payload.get("created_at")),
            updated_at=SecretService._decode_datetime(payload.get("updated_at")),
        )

    @staticmethod
    def _lease_from_payload(payload: dict[str, object] | None) -> VaultLease | None:
        if not isinstance(payload, dict):
            return None
        lease_id = payload.get("lease_id")
        profile_id = payload.get("profile_id")
        source_kind = payload.get("source_kind")
        mount = payload.get("mount")
        path = payload.get("path")
        if not all(
            isinstance(item, str) and item
            for item in (lease_id, profile_id, source_kind, mount, path)
        ):
            return None
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        return VaultLease(
            lease_id=lease_id,
            profile_id=profile_id,
            source_kind=source_kind,
            mount=mount,
            path=path,
            renewable=bool(payload.get("renewable", False)),
            expires_at=SecretService._decode_datetime(payload.get("expires_at")),
            created_at=SecretService._decode_datetime(payload.get("created_at")),
            updated_at=SecretService._decode_datetime(payload.get("updated_at")),
            metadata={str(key): value for key, value in metadata.items()},
        )

    @staticmethod
    def _decode_datetime(value: object) -> datetime | None:
        if isinstance(value, str) and value:
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None
