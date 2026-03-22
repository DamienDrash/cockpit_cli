"""SQLite schema definitions."""

from __future__ import annotations

DATABASE_VERSION = 1

CREATE_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
"""

V1_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS workspaces (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        root_path TEXT NOT NULL,
        target_kind TEXT NOT NULL,
        target_ref TEXT,
        default_layout_id TEXT,
        tags_json TEXT NOT NULL,
        metadata_json TEXT NOT NULL,
        payload_json TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS layouts (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        focus_path_json TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        name TEXT NOT NULL,
        status TEXT NOT NULL,
        active_tab_id TEXT,
        focused_panel_id TEXT,
        snapshot_ref TEXT,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        last_opened_at TEXT,
        FOREIGN KEY(workspace_id) REFERENCES workspaces(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS snapshots (
        ref TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        snapshot_kind TEXT NOT NULL,
        schema_version INTEGER NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(session_id) REFERENCES sessions(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS command_history (
        command_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        source TEXT NOT NULL,
        success INTEGER,
        message TEXT,
        recorded_at TEXT NOT NULL,
        payload_json TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        command_id TEXT NOT NULL,
        action TEXT NOT NULL,
        workspace_id TEXT,
        session_id TEXT,
        recorded_at TEXT NOT NULL,
        payload_json TEXT NOT NULL
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_sessions_workspace_id
    ON sessions(workspace_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_snapshots_session_id
    ON snapshots(session_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_audit_log_command_id
    ON audit_log(command_id);
    """,
)
