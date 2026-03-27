"""Provider-dispatched secret reference resolution."""

from __future__ import annotations

from pathlib import Path
import os
import re
from typing import Protocol
from urllib.parse import urlparse

try:  # pragma: no cover - optional dependency
    import keyring
except Exception:  # pragma: no cover - optional dependency
    keyring = None


PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z0-9_]+)\}")


class NamedReferenceLookup(Protocol):
    def __call__(self, name: str) -> object | None: ...


class VaultReferenceLookup(Protocol):
    def __call__(
        self,
        reference: dict[str, object],
        *,
        resolution_cache: dict[str, object] | None = None,
    ) -> str: ...


class SecretProvider(Protocol):
    provider_name: str

    def resolve(
        self,
        ref: dict[str, object],
        *,
        resolution_cache: dict[str, object] | None = None,
    ) -> str: ...


class EnvSecretProvider:
    provider_name = "env"

    def resolve(
        self,
        ref: dict[str, object],
        *,
        resolution_cache: dict[str, object] | None = None,
    ) -> str:
        del resolution_cache
        name = str(ref.get("name") or ref.get("key") or "").strip()
        if not name:
            raise ValueError("Env secret refs require 'name'.")
        value = os.environ.get(name)
        if value is None:
            raise ValueError(f"Environment variable '{name}' is not set.")
        return value


class FileSecretProvider:
    provider_name = "file"

    def __init__(self, *, base_path: Path | None = None) -> None:
        self._base_path = base_path

    def resolve(
        self,
        ref: dict[str, object],
        *,
        resolution_cache: dict[str, object] | None = None,
    ) -> str:
        del resolution_cache
        raw_path = str(ref.get("path") or "").strip()
        if not raw_path:
            raise ValueError("File secret refs require 'path'.")
        path = Path(raw_path).expanduser()
        if not path.is_absolute() and self._base_path is not None:
            path = (self._base_path / path).resolve()
        return path.read_text(encoding="utf-8").strip()


class KeyringSecretProvider:
    provider_name = "keyring"

    def resolve(
        self,
        ref: dict[str, object],
        *,
        resolution_cache: dict[str, object] | None = None,
    ) -> str:
        del resolution_cache
        if keyring is None:
            raise ValueError("The optional 'keyring' dependency is not installed.")
        service = str(ref.get("service") or "").strip()
        username = str(ref.get("username") or ref.get("name") or "").strip()
        if not service or not username:
            raise ValueError("Keyring refs require 'service' and 'username'.")
        value = keyring.get_password(service, username)
        if value is None:
            raise ValueError(
                f"Keyring entry '{service}/{username}' could not be resolved."
            )
        return value


class LiteralSecretProvider:
    provider_name = "literal"

    def resolve(
        self,
        ref: dict[str, object],
        *,
        resolution_cache: dict[str, object] | None = None,
    ) -> str:
        del resolution_cache
        return str(ref.get("value", ""))


class VaultSecretProvider:
    provider_name = "vault"

    def __init__(self, resolver: VaultReferenceLookup) -> None:
        self._resolver = resolver

    def resolve(
        self,
        ref: dict[str, object],
        *,
        resolution_cache: dict[str, object] | None = None,
    ) -> str:
        kind = str(ref.get("kind", "kv")).strip().lower() or "kv"
        if kind == "transit":
            raise ValueError(
                "Vault transit references require an explicit transit operation and cannot be interpolated directly."
            )
        return self._resolver(ref, resolution_cache=resolution_cache)


class SecretResolver:
    """Resolve secret references from registered providers."""

    def __init__(
        self,
        *,
        base_path: Path | None = None,
        named_reference_lookup: NamedReferenceLookup | None = None,
        vault_reference_lookup: VaultReferenceLookup | None = None,
    ) -> None:
        self._base_path = base_path
        self._named_reference_lookup = named_reference_lookup
        self._providers: dict[str, SecretProvider] = {
            "literal": LiteralSecretProvider(),
            "env": EnvSecretProvider(),
            "file": FileSecretProvider(base_path=base_path),
            "keyring": KeyringSecretProvider(),
        }
        if vault_reference_lookup is not None:
            self._providers["vault"] = VaultSecretProvider(vault_reference_lookup)

    def resolve_text(self, text: str | None, refs: dict[str, object]) -> str | None:
        if text is None:
            return None
        resolution_cache: dict[str, object] = {}
        if not refs:
            missing = PLACEHOLDER_RE.search(text)
            if missing is not None:
                raise ValueError(
                    f"Secret reference '{missing.group(1)}' is not defined."
                )
            return text

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            ref = refs.get(name)
            if ref is None:
                raise ValueError(f"Secret reference '{name}' is not defined.")
            return self.resolve_ref(ref, resolution_cache=resolution_cache)

        resolved = PLACEHOLDER_RE.sub(replace, text)
        missing = PLACEHOLDER_RE.search(resolved)
        if missing is not None:
            raise ValueError(f"Secret reference '{missing.group(1)}' is not defined.")
        return resolved

    def resolve_value(self, value: object, refs: dict[str, object]) -> object:
        resolution_cache: dict[str, object] = {}
        return self._resolve_value(value, refs, resolution_cache=resolution_cache)

    def _resolve_value(
        self,
        value: object,
        refs: dict[str, object],
        *,
        resolution_cache: dict[str, object],
    ) -> object:
        if not refs:
            return value
        if isinstance(value, str):
            return self.resolve_text(value, refs)
        if isinstance(value, dict):
            return {
                str(key): self._resolve_value(
                    item, refs, resolution_cache=resolution_cache
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [
                self._resolve_value(item, refs, resolution_cache=resolution_cache)
                for item in value
            ]
        if isinstance(value, tuple):
            return tuple(
                self._resolve_value(item, refs, resolution_cache=resolution_cache)
                for item in value
            )
        return value

    def resolve_ref(
        self,
        ref: object,
        *,
        resolution_cache: dict[str, object] | None = None,
    ) -> str:
        normalized = self._normalize_ref(ref)
        provider_name = (
            str(normalized.get("provider", "literal")).strip().lower() or "literal"
        )
        if provider_name == "stored":
            name = str(normalized.get("name") or normalized.get("key") or "").strip()
            if not name:
                raise ValueError("Stored secret refs require 'name'.")
            if self._named_reference_lookup is None:
                raise ValueError("No managed secret lookup is configured.")
            stored_ref = self._named_reference_lookup(name)
            if stored_ref is None:
                raise ValueError(f"Managed secret '{name}' was not found.")
            return self.resolve_ref(stored_ref, resolution_cache=resolution_cache)
        provider = self._providers.get(provider_name)
        if provider is None:
            raise ValueError(f"Unsupported secret provider '{provider_name}'.")
        return provider.resolve(normalized, resolution_cache=resolution_cache)

    def _normalize_ref(self, ref: object) -> dict[str, object]:
        if isinstance(ref, str):
            return self._resolve_shorthand(ref)
        if not isinstance(ref, dict):
            raise ValueError("Secret references must be strings or mappings.")
        return {str(key): value for key, value in ref.items()}

    def _resolve_shorthand(self, ref: str) -> dict[str, object]:
        if ref.startswith("vault://"):
            return _parse_vault_ref(ref)
        if ref.startswith("vault+dynamic://"):
            return _parse_vault_dynamic_ref(ref)
        if ref.startswith("vault+transit://"):
            return _parse_vault_transit_ref(ref)
        if ref.startswith("env:"):
            return {"provider": "env", "name": ref.split(":", 1)[1]}
        if ref.startswith("file:"):
            return {"provider": "file", "path": ref.split(":", 1)[1]}
        if ref.startswith("literal:"):
            return {"provider": "literal", "value": ref.split(":", 1)[1]}
        if ref.startswith("keyring:"):
            payload = ref.split(":", 2)
            if len(payload) != 3:
                raise ValueError(
                    "Keyring shorthand must look like keyring:SERVICE:USERNAME."
                )
            return {
                "provider": "keyring",
                "service": payload[1],
                "username": payload[2],
            }
        if ref.startswith("stored:"):
            return {"provider": "stored", "name": ref.split(":", 1)[1]}
        return {"provider": "literal", "value": ref}


def _parse_vault_ref(ref: str) -> dict[str, object]:
    parsed = urlparse(ref)
    profile_id = parsed.netloc
    path = parsed.path.lstrip("/")
    if not profile_id or "/" not in path:
        raise ValueError(
            "Vault KV refs must look like vault://PROFILE/MOUNT/PATH#FIELD."
        )
    mount, secret_path = path.split("/", 1)
    if not parsed.fragment:
        raise ValueError("Vault KV refs must include a field fragment.")
    return {
        "provider": "vault",
        "kind": "kv",
        "profile_id": profile_id,
        "mount": mount,
        "path": secret_path,
        "field": parsed.fragment,
    }


def _parse_vault_dynamic_ref(ref: str) -> dict[str, object]:
    parsed = urlparse(ref)
    profile_id = parsed.netloc
    path = parsed.path.lstrip("/")
    if not profile_id or "/" not in path:
        raise ValueError(
            "Vault dynamic refs must look like vault+dynamic://PROFILE/MOUNT/ROLE#FIELD."
        )
    mount, role = path.split("/", 1)
    if not parsed.fragment:
        raise ValueError("Vault dynamic refs must include a field fragment.")
    return {
        "provider": "vault",
        "kind": "dynamic",
        "profile_id": profile_id,
        "mount": mount,
        "role": role,
        "field": parsed.fragment,
    }


def _parse_vault_transit_ref(ref: str) -> dict[str, object]:
    parsed = urlparse(ref)
    profile_id = parsed.netloc
    path = parsed.path.lstrip("/")
    if not profile_id or not path:
        raise ValueError(
            "Vault transit refs must look like vault+transit://PROFILE/KEY or vault+transit://PROFILE/MOUNT/KEY."
        )
    parts = path.split("/", 1)
    if len(parts) == 1:
        mount, key_name = "transit", parts[0]
    else:
        mount, key_name = parts
    return {
        "provider": "vault",
        "kind": "transit",
        "profile_id": profile_id,
        "mount": mount,
        "key_name": key_name,
    }
