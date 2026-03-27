"""Managed secret and Vault metadata models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from cockpit.core.utils import serialize_contract


@dataclass(slots=True)
class ManagedSecretEntry:
    name: str
    provider: str
    reference: dict[str, object]
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    rotated_at: datetime | None = None
    revision: int = 1

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class VaultProfile:
    id: str
    name: str
    address: str
    auth_type: str
    auth_mount: str | None = None
    role_name: str | None = None
    namespace: str | None = None
    description: str | None = None
    verify_tls: bool = True
    ca_cert_path: str | None = None
    allow_local_cache: bool = False
    cache_ttl_seconds: int = 3600
    risk_level: str = "dev"
    tags: list[str] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class VaultSession:
    profile_id: str
    auth_type: str
    token_accessor: str | None = None
    renewable: bool = False
    expires_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    source: str = "live"
    cached: bool = False
    last_error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)


@dataclass(slots=True)
class VaultLease:
    lease_id: str
    profile_id: str
    source_kind: str
    mount: str
    path: str
    renewable: bool = False
    expires_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return serialize_contract(self)
