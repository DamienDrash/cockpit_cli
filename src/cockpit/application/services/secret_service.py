"""Managed secret metadata and optional keyring-backed values."""

from __future__ import annotations

from dataclasses import dataclass

from cockpit.domain.models.secret import ManagedSecretEntry
from cockpit.infrastructure.persistence.repositories import WebAdminStateRepository

try:  # pragma: no cover - optional dependency guard
    import keyring
    from keyring.errors import PasswordDeleteError
except Exception:  # pragma: no cover - optional dependency guard
    keyring = None
    PasswordDeleteError = Exception


SECRET_STATE_PREFIX = "secret:"


@dataclass(slots=True, frozen=True)
class SecretDiagnostics:
    total_entries: int
    providers: list[str]
    keyring_available: bool


class SecretService:
    """Persist managed secret references and optional keyring values."""

    def __init__(
        self,
        repository: WebAdminStateRepository,
        *,
        keyring_backend: object | None = None,
    ) -> None:
        self._repository = repository
        self._keyring = keyring_backend if keyring_backend is not None else keyring

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
    ) -> ManagedSecretEntry:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("Secret name must not be empty.")
        normalized_provider = provider.strip().lower()
        if normalized_provider == "env":
            env_key = (env_name or "").strip()
            if not env_key:
                raise ValueError("Managed env secrets require an environment variable name.")
            reference = {"provider": "env", "name": env_key}
        elif normalized_provider == "file":
            path = (file_path or "").strip()
            if not path:
                raise ValueError("Managed file secrets require a path.")
            reference = {"provider": "file", "path": path}
        elif normalized_provider == "keyring":
            service = (keyring_service or "cockpit").strip()
            username = (keyring_username or normalized_name).strip()
            if not service or not username:
                raise ValueError("Managed keyring secrets require a service and username.")
            if secret_value:
                self._set_keyring_value(service, username, secret_value)
            reference = {
                "provider": "keyring",
                "service": service,
                "username": username,
            }
        else:
            raise ValueError("Managed secrets only support env, file, or keyring providers.")

        entry = ManagedSecretEntry(
            name=normalized_name,
            provider=normalized_provider,
            reference=reference,
            description=description.strip() if isinstance(description, str) and description.strip() else None,
            tags=[item.strip() for item in (tags or []) if isinstance(item, str) and item.strip()],
        )
        self._repository.save(self._entry_key(normalized_name), entry.to_dict())
        return entry

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

    def diagnostics(self) -> SecretDiagnostics:
        entries = self.list_entries()
        return SecretDiagnostics(
            total_entries=len(entries),
            providers=sorted({entry.provider for entry in entries}),
            keyring_available=self._keyring is not None,
        )

    @staticmethod
    def _entry_key(name: str) -> str:
        return f"{SECRET_STATE_PREFIX}{name}"

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

    @staticmethod
    def _entry_from_payload(payload: dict[str, object] | None) -> ManagedSecretEntry | None:
        if not isinstance(payload, dict):
            return None
        reference = payload.get("reference", {})
        if not isinstance(reference, dict):
            reference = {}
        name = payload.get("name")
        provider = payload.get("provider")
        if not isinstance(name, str) or not name or not isinstance(provider, str) or not provider:
            return None
        return ManagedSecretEntry(
            name=name,
            provider=provider,
            reference={str(key): value for key, value in reference.items()},
            description=(
                str(payload["description"])
                if payload.get("description") is not None
                else None
            ),
            tags=[str(item) for item in payload.get("tags", []) if isinstance(item, str)],
        )
