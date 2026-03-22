"""Secret reference resolution for datasource profiles."""

from __future__ import annotations

from pathlib import Path
import os
import re

try:  # pragma: no cover - optional dependency
    import keyring
except Exception:  # pragma: no cover - optional dependency
    keyring = None


PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z0-9_]+)\}")


class SecretResolver:
    """Resolve secret references from env, files, keyring, or literals."""

    def __init__(self, *, base_path: Path | None = None) -> None:
        self._base_path = base_path

    def resolve_text(self, text: str | None, refs: dict[str, object]) -> str | None:
        if text is None:
            return None
        if not refs:
            missing = PLACEHOLDER_RE.search(text)
            if missing is not None:
                raise ValueError(f"Secret reference '{missing.group(1)}' is not defined.")
            return text

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            ref = refs.get(name)
            if ref is None:
                raise ValueError(f"Secret reference '{name}' is not defined.")
            return self.resolve_ref(ref)

        resolved = PLACEHOLDER_RE.sub(replace, text)
        missing = PLACEHOLDER_RE.search(resolved)
        if missing is not None:
            raise ValueError(f"Secret reference '{missing.group(1)}' is not defined.")
        return resolved

    def resolve_value(self, value: object, refs: dict[str, object]) -> object:
        if not refs:
            return value
        if isinstance(value, str):
            return self.resolve_text(value, refs)
        if isinstance(value, dict):
            return {
                str(key): self.resolve_value(item, refs)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self.resolve_value(item, refs) for item in value]
        if isinstance(value, tuple):
            return tuple(self.resolve_value(item, refs) for item in value)
        return value

    def resolve_ref(self, ref: object) -> str:
        if isinstance(ref, str):
            return self._resolve_shorthand(ref)
        if not isinstance(ref, dict):
            raise ValueError("Secret references must be strings or mappings.")
        provider = str(ref.get("provider", "literal")).strip().lower()
        if provider == "literal":
            return str(ref.get("value", ""))
        if provider == "env":
            name = str(ref.get("name") or ref.get("key") or "").strip()
            if not name:
                raise ValueError("Env secret refs require 'name'.")
            value = os.environ.get(name)
            if value is None:
                raise ValueError(f"Environment variable '{name}' is not set.")
            return value
        if provider == "file":
            raw_path = str(ref.get("path") or "").strip()
            if not raw_path:
                raise ValueError("File secret refs require 'path'.")
            path = Path(raw_path).expanduser()
            if not path.is_absolute() and self._base_path is not None:
                path = (self._base_path / path).resolve()
            return path.read_text(encoding="utf-8").strip()
        if provider == "keyring":
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
        raise ValueError(f"Unsupported secret provider '{provider}'.")

    def _resolve_shorthand(self, ref: str) -> str:
        if ref.startswith("env:"):
            return self.resolve_ref({"provider": "env", "name": ref.split(":", 1)[1]})
        if ref.startswith("file:"):
            return self.resolve_ref({"provider": "file", "path": ref.split(":", 1)[1]})
        if ref.startswith("literal:"):
            return ref.split(":", 1)[1]
        if ref.startswith("keyring:"):
            payload = ref.split(":", 2)
            if len(payload) != 3:
                raise ValueError("Keyring shorthand must look like keyring:SERVICE:USERNAME.")
            return self.resolve_ref(
                {
                    "provider": "keyring",
                    "service": payload[1],
                    "username": payload[2],
                }
            )
        return ref
