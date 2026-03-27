"""SQLite-backed repositories for the core platform spine."""

from __future__ import annotations

from datetime import datetime
import json

from cockpit.core.command import CommandAuditEntry, CommandHistoryEntry
from cockpit.datasources.models.datasource import DataSourceProfile
from cockpit.workspace.models.layout import Layout, PanelRef, SplitNode, TabLayout
from cockpit.plugins.models import InstalledPlugin
from cockpit.workspace.models.session import Session
from cockpit.workspace.models.workspace import SessionTarget, Workspace
from cockpit.core.persistence.snapshot_codec import (
    SnapshotDecodeResult,
    decode_snapshot,
    encode_snapshot,
)
from cockpit.core.persistence.sqlite_store import SQLiteStore
from cockpit.core.enums import SessionStatus, SessionTargetKind, SnapshotKind
from cockpit.core.utils import make_id, utc_now


def _load_json(raw_value: str) -> dict[str, object]:
    payload = json.loads(raw_value)
    if not isinstance(payload, dict):
        msg = "Expected JSON object payload."
        raise TypeError(msg)
    return payload


def _decode_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class WorkspaceRepository:
    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, workspace: Workspace) -> None:
        payload = workspace.to_dict()
        self._store.execute(
            """
            INSERT INTO workspaces (
                id,
                name,
                root_path,
                target_kind,
                target_ref,
                default_layout_id,
                tags_json,
                metadata_json,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                root_path = excluded.root_path,
                target_kind = excluded.target_kind,
                target_ref = excluded.target_ref,
                default_layout_id = excluded.default_layout_id,
                tags_json = excluded.tags_json,
                metadata_json = excluded.metadata_json,
                payload_json = excluded.payload_json
            """,
            (
                workspace.id,
                workspace.name,
                workspace.root_path,
                workspace.target.kind.value,
                workspace.target.ref,
                workspace.default_layout_id,
                json.dumps(workspace.tags, sort_keys=True),
                json.dumps(workspace.metadata, sort_keys=True),
                json.dumps(payload, sort_keys=True),
            ),
        )

    def get(self, workspace_id: str) -> Workspace | None:
        row = self._store.fetchone(
            "SELECT payload_json FROM workspaces WHERE id = ?",
            (workspace_id,),
        )
        if row is None:
            return None
        return _workspace_from_payload(_load_json(row["payload_json"]))

    def list_all(self) -> list[Workspace]:
        rows = self._store.fetchall("SELECT payload_json FROM workspaces ORDER BY name")
        return [
            _workspace_from_payload(_load_json(row["payload_json"])) for row in rows
        ]


class LayoutRepository:
    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, layout: Layout) -> None:
        payload = layout.to_dict()
        self._store.execute(
            """
            INSERT INTO layouts (id, name, focus_path_json, payload_json, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                focus_path_json = excluded.focus_path_json,
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            (
                layout.id,
                layout.name,
                json.dumps(layout.focus_path, sort_keys=True),
                json.dumps(payload, sort_keys=True),
                utc_now().isoformat(),
            ),
        )

    def get(self, layout_id: str) -> Layout | None:
        row = self._store.fetchone(
            "SELECT payload_json FROM layouts WHERE id = ?",
            (layout_id,),
        )
        if row is None:
            return None
        return _layout_from_payload(_load_json(row["payload_json"]))

    def list_all(self) -> list[Layout]:
        rows = self._store.fetchall(
            "SELECT payload_json FROM layouts ORDER BY updated_at DESC, name ASC"
        )
        return [_layout_from_payload(_load_json(row["payload_json"])) for row in rows]


class SessionRepository:
    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, session: Session) -> None:
        payload = session.to_dict()
        self._store.execute(
            """
            INSERT INTO sessions (
                id,
                workspace_id,
                name,
                status,
                active_tab_id,
                focused_panel_id,
                snapshot_ref,
                payload_json,
                created_at,
                updated_at,
                last_opened_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                workspace_id = excluded.workspace_id,
                name = excluded.name,
                status = excluded.status,
                active_tab_id = excluded.active_tab_id,
                focused_panel_id = excluded.focused_panel_id,
                snapshot_ref = excluded.snapshot_ref,
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at,
                last_opened_at = excluded.last_opened_at
            """,
            (
                session.id,
                session.workspace_id,
                session.name,
                session.status.value,
                session.active_tab_id,
                session.focused_panel_id,
                session.snapshot_ref,
                json.dumps(payload, sort_keys=True),
                session.created_at.isoformat(),
                session.updated_at.isoformat(),
                session.last_opened_at.isoformat() if session.last_opened_at else None,
            ),
        )

    def get(self, session_id: str) -> Session | None:
        row = self._store.fetchone(
            "SELECT payload_json FROM sessions WHERE id = ?",
            (session_id,),
        )
        if row is None:
            return None
        return _session_from_payload(_load_json(row["payload_json"]))

    def get_latest_for_workspace(self, workspace_id: str) -> Session | None:
        row = self._store.fetchone(
            """
            SELECT payload_json
            FROM sessions
            WHERE workspace_id = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (workspace_id,),
        )
        if row is None:
            return None
        return _session_from_payload(_load_json(row["payload_json"]))

    def get_latest(self) -> Session | None:
        row = self._store.fetchone(
            """
            SELECT payload_json
            FROM sessions
            ORDER BY updated_at DESC
            LIMIT 1
            """
        )
        if row is None:
            return None
        return _session_from_payload(_load_json(row["payload_json"]))


class SnapshotRepository:
    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(
        self,
        *,
        session_id: str,
        snapshot_kind: SnapshotKind,
        payload: dict[str, object],
        snapshot_ref: str | None = None,
    ) -> str:
        ref = snapshot_ref or make_id("snap")
        raw_payload = encode_snapshot(snapshot_kind, payload)
        decoded = decode_snapshot(raw_payload)
        assert decoded.envelope is not None
        envelope = decoded.envelope
        self._store.execute(
            """
            INSERT INTO snapshots (
                ref,
                session_id,
                snapshot_kind,
                schema_version,
                payload_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(ref) DO UPDATE SET
                session_id = excluded.session_id,
                snapshot_kind = excluded.snapshot_kind,
                schema_version = excluded.schema_version,
                payload_json = excluded.payload_json,
                created_at = excluded.created_at
            """,
            (
                ref,
                session_id,
                snapshot_kind.value,
                envelope.schema_version,
                raw_payload,
                envelope.created_at.isoformat(),
            ),
        )
        return ref

    def load(self, snapshot_ref: str) -> SnapshotDecodeResult:
        row = self._store.fetchone(
            "SELECT payload_json FROM snapshots WHERE ref = ?",
            (snapshot_ref,),
        )
        if row is None:
            return SnapshotDecodeResult(
                success=False,
                error=f"Snapshot '{snapshot_ref}' was not found.",
            )
        return decode_snapshot(row["payload_json"])


class CommandHistoryRepository:
    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def record(self, entry: CommandHistoryEntry) -> None:
        payload = entry.to_dict()
        self._store.execute(
            """
            INSERT INTO command_history (
                command_id,
                name,
                source,
                success,
                message,
                recorded_at,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(command_id) DO UPDATE SET
                name = excluded.name,
                source = excluded.source,
                success = excluded.success,
                message = excluded.message,
                recorded_at = excluded.recorded_at,
                payload_json = excluded.payload_json
            """,
            (
                entry.command_id,
                entry.name,
                entry.source.value,
                None if entry.success is None else int(entry.success),
                entry.message,
                entry.recorded_at.isoformat(),
                json.dumps(payload, sort_keys=True),
            ),
        )

    def list_recent(self, limit: int = 20) -> list[dict[str, object]]:
        rows = self._store.fetchall(
            """
            SELECT payload_json
            FROM command_history
            ORDER BY recorded_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [_load_json(row["payload_json"]) for row in rows]


class AuditLogRepository:
    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def record(self, entry: CommandAuditEntry) -> None:
        payload = entry.to_dict()
        self._store.execute(
            """
            INSERT INTO audit_log (
                command_id,
                action,
                workspace_id,
                session_id,
                recorded_at,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                entry.command_id,
                entry.action,
                entry.workspace_id,
                entry.session_id,
                entry.recorded_at.isoformat(),
                json.dumps(payload, sort_keys=True),
            ),
        )

    def list_recent(self, limit: int = 20) -> list[dict[str, object]]:
        rows = self._store.fetchall(
            """
            SELECT payload_json
            FROM audit_log
            ORDER BY recorded_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [_load_json(row["payload_json"]) for row in rows]


class DataSourceProfileRepository:
    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, profile: DataSourceProfile) -> None:
        payload = profile.to_dict()
        self._store.execute(
            """
            INSERT INTO datasource_profiles (
                id,
                name,
                backend,
                driver,
                connection_url,
                target_kind,
                target_ref,
                database_name,
                risk_level,
                enabled,
                capabilities_json,
                options_json,
                secret_refs_json,
                payload_json,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                backend = excluded.backend,
                driver = excluded.driver,
                connection_url = excluded.connection_url,
                target_kind = excluded.target_kind,
                target_ref = excluded.target_ref,
                database_name = excluded.database_name,
                risk_level = excluded.risk_level,
                enabled = excluded.enabled,
                capabilities_json = excluded.capabilities_json,
                options_json = excluded.options_json,
                secret_refs_json = excluded.secret_refs_json,
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            (
                profile.id,
                profile.name,
                profile.backend,
                profile.driver,
                profile.connection_url,
                profile.target_kind.value,
                profile.target_ref,
                profile.database_name,
                profile.risk_level,
                int(profile.enabled),
                json.dumps(profile.capabilities, sort_keys=True),
                json.dumps(profile.options, sort_keys=True),
                json.dumps(profile.secret_refs, sort_keys=True),
                json.dumps(payload, sort_keys=True),
                utc_now().isoformat(),
            ),
        )

    def get(self, profile_id: str) -> DataSourceProfile | None:
        row = self._store.fetchone(
            "SELECT payload_json FROM datasource_profiles WHERE id = ?",
            (profile_id,),
        )
        if row is None:
            return None
        return _datasource_from_payload(_load_json(row["payload_json"]))

    def list_all(self) -> list[DataSourceProfile]:
        rows = self._store.fetchall(
            "SELECT payload_json FROM datasource_profiles ORDER BY name"
        )
        return [
            _datasource_from_payload(_load_json(row["payload_json"])) for row in rows
        ]

    def delete(self, profile_id: str) -> None:
        self._store.execute(
            "DELETE FROM datasource_profiles WHERE id = ?", (profile_id,)
        )


class InstalledPluginRepository:
    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, plugin: InstalledPlugin) -> None:
        payload = plugin.to_dict()
        self._store.execute(
            """
            INSERT INTO installed_plugins (
                id,
                name,
                module,
                requirement,
                version_pin,
                install_path,
                enabled,
                source,
                status,
                manifest_json,
                payload_json,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                module = excluded.module,
                requirement = excluded.requirement,
                version_pin = excluded.version_pin,
                install_path = excluded.install_path,
                enabled = excluded.enabled,
                source = excluded.source,
                status = excluded.status,
                manifest_json = excluded.manifest_json,
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            (
                plugin.id,
                plugin.name,
                plugin.module,
                plugin.requirement,
                plugin.version_pin,
                plugin.install_path,
                int(plugin.enabled),
                plugin.source,
                plugin.status,
                json.dumps(plugin.manifest, sort_keys=True),
                json.dumps(payload, sort_keys=True),
                utc_now().isoformat(),
            ),
        )

    def get(self, plugin_id: str) -> InstalledPlugin | None:
        row = self._store.fetchone(
            "SELECT payload_json FROM installed_plugins WHERE id = ?",
            (plugin_id,),
        )
        if row is None:
            return None
        return _installed_plugin_from_payload(_load_json(row["payload_json"]))

    def list_all(self) -> list[InstalledPlugin]:
        rows = self._store.fetchall(
            "SELECT payload_json FROM installed_plugins ORDER BY name"
        )
        return [
            _installed_plugin_from_payload(_load_json(row["payload_json"]))
            for row in rows
        ]

    def delete(self, plugin_id: str) -> None:
        self._store.execute("DELETE FROM installed_plugins WHERE id = ?", (plugin_id,))


class WebAdminStateRepository:
    def __init__(self, store: SQLiteStore) -> None:
        self._store = store

    def save(self, key: str, value: dict[str, object]) -> None:
        self._store.execute(
            """
            INSERT INTO web_admin_state (key, value_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value_json = excluded.value_json,
                updated_at = excluded.updated_at
            """,
            (
                key,
                json.dumps(value, sort_keys=True),
                utc_now().isoformat(),
            ),
        )

    def get(self, key: str) -> dict[str, object] | None:
        row = self._store.fetchone(
            "SELECT value_json FROM web_admin_state WHERE key = ?",
            (key,),
        )
        if row is None:
            return None
        return _load_json(row["value_json"])

    def delete(self, key: str) -> None:
        self._store.execute(
            "DELETE FROM web_admin_state WHERE key = ?",
            (key,),
        )

    def list_prefix(self, prefix: str) -> list[tuple[str, dict[str, object]]]:
        rows = self._store.fetchall(
            """
            SELECT key, value_json
            FROM web_admin_state
            WHERE key LIKE ?
            ORDER BY key ASC
            """,
            (f"{prefix}%",),
        )
        return [(str(row["key"]), _load_json(row["value_json"])) for row in rows]


def _workspace_from_payload(payload: dict[str, object]) -> Workspace:
    target_payload = payload.get("target", {})
    if not isinstance(target_payload, dict):
        target_payload = {}
    return Workspace(
        id=str(payload["id"]),
        name=str(payload["name"]),
        root_path=str(payload["root_path"]),
        target=SessionTarget(
            kind=SessionTargetKind(str(target_payload.get("kind", "local"))),
            ref=(
                str(target_payload["ref"])
                if target_payload.get("ref") is not None
                else None
            ),
        ),
        default_layout_id=(
            str(payload["default_layout_id"])
            if payload.get("default_layout_id") is not None
            else None
        ),
        tags=[str(item) for item in payload.get("tags", [])],
        metadata=(
            payload.get("metadata", {})
            if isinstance(payload.get("metadata", {}), dict)
            else {}
        ),
    )


def _layout_from_payload(payload: dict[str, object]) -> Layout:
    raw_tabs = payload.get("tabs", [])
    tabs: list[TabLayout] = []
    for raw_tab in raw_tabs if isinstance(raw_tabs, list) else []:
        if not isinstance(raw_tab, dict):
            continue
        tabs.append(
            TabLayout(
                id=str(raw_tab["id"]),
                name=str(raw_tab["name"]),
                root_split=_decode_split_node(raw_tab["root_split"]),
            )
        )
    return Layout(
        id=str(payload["id"]),
        name=str(payload["name"]),
        tabs=tabs,
        focus_path=[str(item) for item in payload.get("focus_path", [])],
    )


def _decode_split_node(raw_node: object) -> SplitNode:
    if not isinstance(raw_node, dict):
        msg = "Split node payload must be a mapping."
        raise TypeError(msg)
    raw_children = raw_node.get("children", [])
    children: list[SplitNode | PanelRef] = []
    for child in raw_children if isinstance(raw_children, list) else []:
        if isinstance(child, dict) and {"panel_id", "panel_type"} <= set(child.keys()):
            children.append(
                PanelRef(
                    panel_id=str(child["panel_id"]),
                    panel_type=str(child["panel_type"]),
                )
            )
        else:
            children.append(_decode_split_node(child))
    return SplitNode(
        orientation=(
            str(raw_node["orientation"])
            if raw_node.get("orientation") is not None
            else None
        ),
        ratio=float(raw_node["ratio"]) if raw_node.get("ratio") is not None else None,
        children=children,
    )


def _session_from_payload(payload: dict[str, object]) -> Session:
    created_at = _decode_datetime(payload.get("created_at"))  # type: ignore[arg-type]
    updated_at = _decode_datetime(payload.get("updated_at"))  # type: ignore[arg-type]
    if created_at is None or updated_at is None:
        msg = "Session payload is missing required timestamps."
        raise ValueError(msg)
    return Session(
        id=str(payload["id"]),
        workspace_id=str(payload["workspace_id"]),
        name=str(payload["name"]),
        status=SessionStatus(str(payload["status"])),
        active_tab_id=(
            str(payload["active_tab_id"])
            if payload.get("active_tab_id") is not None
            else None
        ),
        focused_panel_id=(
            str(payload["focused_panel_id"])
            if payload.get("focused_panel_id") is not None
            else None
        ),
        snapshot_ref=(
            str(payload["snapshot_ref"])
            if payload.get("snapshot_ref") is not None
            else None
        ),
        created_at=created_at,
        updated_at=updated_at,
        last_opened_at=_decode_datetime(payload.get("last_opened_at")),  # type: ignore[arg-type]
    )


def _datasource_from_payload(payload: dict[str, object]) -> DataSourceProfile:
    return DataSourceProfile(
        id=str(payload["id"]),
        name=str(payload["name"]),
        backend=str(payload["backend"]),
        driver=str(payload["driver"]) if payload.get("driver") is not None else None,
        connection_url=(
            str(payload["connection_url"])
            if payload.get("connection_url") is not None
            else None
        ),
        target_kind=SessionTargetKind(str(payload.get("target_kind", "local"))),
        target_ref=(
            str(payload["target_ref"])
            if payload.get("target_ref") is not None
            else None
        ),
        database_name=(
            str(payload["database_name"])
            if payload.get("database_name") is not None
            else None
        ),
        risk_level=str(payload.get("risk_level", "dev")),
        capabilities=[str(item) for item in payload.get("capabilities", [])],
        options=payload.get("options", {})
        if isinstance(payload.get("options"), dict)
        else {},
        secret_refs=(
            payload.get("secret_refs", {})
            if isinstance(payload.get("secret_refs"), dict)
            else {}
        ),
        tags=[str(item) for item in payload.get("tags", [])],
        managed_by_plugin=(
            str(payload["managed_by_plugin"])
            if payload.get("managed_by_plugin") is not None
            else None
        ),
        enabled=bool(payload.get("enabled", True)),
    )


def _installed_plugin_from_payload(payload: dict[str, object]) -> InstalledPlugin:
    return InstalledPlugin(
        id=str(payload["id"]),
        name=str(payload["name"]),
        module=str(payload["module"]),
        requirement=str(payload["requirement"]),
        version_pin=(
            str(payload["version_pin"])
            if payload.get("version_pin") is not None
            else None
        ),
        install_path=(
            str(payload["install_path"])
            if payload.get("install_path") is not None
            else None
        ),
        enabled=bool(payload.get("enabled", True)),
        source=str(payload["source"]) if payload.get("source") is not None else None,
        manifest=payload.get("manifest", {})
        if isinstance(payload.get("manifest"), dict)
        else {},
        status=str(payload.get("status", "installed")),
    )
