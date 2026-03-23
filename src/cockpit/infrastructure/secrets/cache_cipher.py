"""Encrypted local cache helpers for Vault session material."""

from __future__ import annotations

from pathlib import Path

try:  # pragma: no cover - optional dependency guard
    from cryptography.fernet import Fernet, InvalidToken
except Exception:  # pragma: no cover - optional dependency guard
    Fernet = None
    InvalidToken = Exception


class SecretCacheCipher:
    """Encrypt and decrypt short-lived cached session payloads."""

    def __init__(self, key_path: Path) -> None:
        self._key_path = key_path
        self._fernet = self._build_fernet(key_path)

    @property
    def available(self) -> bool:
        return self._fernet is not None

    def encrypt(self, value: str) -> str:
        if self._fernet is None:
            raise ValueError("cryptography is required for encrypted secret caching.")
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, value: str) -> str:
        if self._fernet is None:
            raise ValueError("cryptography is required for encrypted secret caching.")
        try:
            return self._fernet.decrypt(value.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("Encrypted secret cache could not be decrypted.") from exc

    @staticmethod
    def _build_fernet(key_path: Path) -> Fernet | None:
        if Fernet is None:
            return None
        key_path.parent.mkdir(parents=True, exist_ok=True)
        if not key_path.exists():
            key_path.write_bytes(Fernet.generate_key())
            try:
                key_path.chmod(0o600)
            except OSError:
                pass
        return Fernet(key_path.read_bytes())
