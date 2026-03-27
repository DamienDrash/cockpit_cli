"""Connection profile loading and resolution."""

from __future__ import annotations

from dataclasses import dataclass, field

from cockpit.workspace.config_loader import ConfigLoader


@dataclass(slots=True, frozen=True)
class ConnectionProfile:
    alias: str
    target_ref: str
    default_path: str = "."
    description: str | None = None
    shell: str | None = None
    env: dict[str, str] = field(default_factory=dict)


class ConnectionService:
    """Resolve user-defined connection profiles from declarative config."""

    def __init__(self, config_loader: ConfigLoader) -> None:
        self._config_loader = config_loader
        self._profiles: dict[str, ConnectionProfile] | None = None

    def get(self, alias: str) -> ConnectionProfile | None:
        return self._load_profiles().get(alias)

    def list_profiles(self) -> list[ConnectionProfile]:
        return sorted(self._load_profiles().values(), key=lambda profile: profile.alias)

    def is_configured(self, alias: str) -> bool:
        return alias in self._load_profiles()

    def _load_profiles(self) -> dict[str, ConnectionProfile]:
        if self._profiles is not None:
            return self._profiles

        payload = self._config_loader.load_connections()
        raw_connections = payload.get("connections", {})
        profiles: dict[str, ConnectionProfile] = {}
        if isinstance(raw_connections, dict):
            for alias, raw_profile in raw_connections.items():
                if (
                    not isinstance(alias, str)
                    or not alias
                    or not isinstance(raw_profile, dict)
                ):
                    continue
                target_ref = raw_profile.get("target") or raw_profile.get("target_ref")
                if not isinstance(target_ref, str) or not target_ref:
                    continue
                raw_env = raw_profile.get("env", {})
                env = {
                    str(key): str(value)
                    for key, value in raw_env.items()
                    if isinstance(raw_env, dict)
                }
                profiles[alias] = ConnectionProfile(
                    alias=alias,
                    target_ref=target_ref,
                    default_path=str(raw_profile.get("default_path", ".")),
                    description=(
                        str(raw_profile["description"])
                        if raw_profile.get("description") is not None
                        else None
                    ),
                    shell=(
                        str(raw_profile["shell"])
                        if raw_profile.get("shell") is not None
                        else None
                    ),
                    env=env,
                )

        self._profiles = profiles
        return profiles
