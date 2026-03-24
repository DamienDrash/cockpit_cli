"""SQLite schema definitions."""

from __future__ import annotations

DATABASE_VERSION = 4

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

V2_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS datasource_profiles (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        backend TEXT NOT NULL,
        driver TEXT,
        connection_url TEXT,
        target_kind TEXT NOT NULL,
        target_ref TEXT,
        database_name TEXT,
        risk_level TEXT NOT NULL,
        enabled INTEGER NOT NULL,
        capabilities_json TEXT NOT NULL,
        options_json TEXT NOT NULL,
        secret_refs_json TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS installed_plugins (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        module TEXT NOT NULL,
        requirement TEXT NOT NULL,
        version_pin TEXT,
        install_path TEXT,
        enabled INTEGER NOT NULL,
        source TEXT,
        status TEXT NOT NULL,
        manifest_json TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS web_admin_state (
        key TEXT PRIMARY KEY,
        value_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_datasource_profiles_backend
    ON datasource_profiles(backend);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_installed_plugins_module
    ON installed_plugins(module);
    """,
)

V3_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS component_health_state (
        component_id TEXT PRIMARY KEY,
        component_kind TEXT NOT NULL,
        display_name TEXT NOT NULL,
        status TEXT NOT NULL,
        workspace_id TEXT,
        session_id TEXT,
        target_kind TEXT NOT NULL,
        target_ref TEXT,
        last_heartbeat_at TEXT,
        last_failure_at TEXT,
        last_recovery_at TEXT,
        next_recovery_at TEXT,
        cooldown_until TEXT,
        consecutive_failures INTEGER NOT NULL,
        exhaustion_count INTEGER NOT NULL,
        quarantined INTEGER NOT NULL,
        quarantine_reason TEXT,
        last_incident_id TEXT,
        payload_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS component_health_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        component_id TEXT NOT NULL,
        component_kind TEXT NOT NULL,
        previous_status TEXT,
        new_status TEXT NOT NULL,
        reason TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        payload_json TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS incidents (
        id TEXT PRIMARY KEY,
        component_id TEXT NOT NULL,
        component_kind TEXT NOT NULL,
        severity TEXT NOT NULL,
        status TEXT NOT NULL,
        title TEXT NOT NULL,
        summary TEXT NOT NULL,
        workspace_id TEXT,
        session_id TEXT,
        opened_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        acknowledged_at TEXT,
        resolved_at TEXT,
        closed_at TEXT,
        payload_json TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS incident_timeline (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        incident_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        message TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        FOREIGN KEY(incident_id) REFERENCES incidents(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS recovery_attempts (
        id TEXT PRIMARY KEY,
        incident_id TEXT NOT NULL,
        component_id TEXT NOT NULL,
        attempt_number INTEGER NOT NULL,
        status TEXT NOT NULL,
        trigger TEXT NOT NULL,
        action TEXT NOT NULL,
        backoff_ms INTEGER NOT NULL,
        scheduled_for TEXT,
        started_at TEXT,
        finished_at TEXT,
        error_message TEXT,
        payload_json TEXT NOT NULL,
        FOREIGN KEY(incident_id) REFERENCES incidents(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS guard_decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        command_id TEXT NOT NULL,
        action_kind TEXT NOT NULL,
        component_kind TEXT NOT NULL,
        target_risk TEXT NOT NULL,
        outcome TEXT NOT NULL,
        requires_confirmation INTEGER NOT NULL,
        requires_elevated_mode INTEGER NOT NULL,
        requires_dry_run INTEGER NOT NULL,
        audit_required INTEGER NOT NULL,
        explanation TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        payload_json TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS operation_diagnostics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        operation_family TEXT NOT NULL,
        component_id TEXT NOT NULL,
        subject_ref TEXT NOT NULL,
        success INTEGER NOT NULL,
        severity TEXT NOT NULL,
        summary TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        payload_json TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS component_diagnostics_cache (
        component_id TEXT PRIMARY KEY,
        component_kind TEXT NOT NULL,
        snapshot_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_component_health_state_status
    ON component_health_state(status);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_component_health_state_kind
    ON component_health_state(component_kind);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_component_health_history_component
    ON component_health_history(component_id, recorded_at DESC);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_incidents_component_status
    ON incidents(component_id, status, updated_at DESC);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_incident_timeline_incident_id
    ON incident_timeline(incident_id, recorded_at DESC);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_recovery_attempts_component_id
    ON recovery_attempts(component_id, scheduled_for DESC);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_guard_decisions_command_id
    ON guard_decisions(command_id, recorded_at DESC);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_operation_diagnostics_family
    ON operation_diagnostics(operation_family, recorded_at DESC);
    """,
)

V4_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS notification_channels (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        kind TEXT NOT NULL,
        enabled INTEGER NOT NULL,
        target_json TEXT NOT NULL,
        secret_refs_json TEXT NOT NULL,
        timeout_seconds INTEGER NOT NULL,
        max_attempts INTEGER NOT NULL,
        base_backoff_seconds INTEGER NOT NULL,
        max_backoff_seconds INTEGER NOT NULL,
        risk_level TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS notification_rules (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        enabled INTEGER NOT NULL,
        event_classes_json TEXT NOT NULL,
        component_kinds_json TEXT NOT NULL,
        severities_json TEXT NOT NULL,
        risk_levels_json TEXT NOT NULL,
        incident_statuses_json TEXT NOT NULL,
        channel_ids_json TEXT NOT NULL,
        delivery_priority INTEGER NOT NULL,
        dedupe_window_seconds INTEGER NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS notification_suppressions (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        enabled INTEGER NOT NULL,
        reason TEXT NOT NULL,
        starts_at TEXT,
        ends_at TEXT,
        event_classes_json TEXT NOT NULL,
        component_kinds_json TEXT NOT NULL,
        severities_json TEXT NOT NULL,
        risk_levels_json TEXT NOT NULL,
        actor TEXT,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS notifications (
        id TEXT PRIMARY KEY,
        event_class TEXT NOT NULL,
        severity TEXT NOT NULL,
        risk_level TEXT NOT NULL,
        title TEXT NOT NULL,
        summary TEXT NOT NULL,
        status TEXT NOT NULL,
        dedupe_key TEXT NOT NULL,
        incident_id TEXT,
        component_id TEXT,
        component_kind TEXT,
        incident_status TEXT,
        source_event_id TEXT,
        suppression_reason TEXT,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS notification_deliveries (
        id TEXT PRIMARY KEY,
        notification_id TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        attempt_number INTEGER NOT NULL,
        status TEXT NOT NULL,
        scheduled_for TEXT,
        started_at TEXT,
        finished_at TEXT,
        error_class TEXT,
        error_message TEXT,
        response_payload_json TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        FOREIGN KEY(notification_id) REFERENCES notifications(id),
        FOREIGN KEY(channel_id) REFERENCES notification_channels(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS component_watch_config (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        component_id TEXT NOT NULL,
        component_kind TEXT NOT NULL,
        subject_kind TEXT NOT NULL,
        subject_ref TEXT NOT NULL,
        enabled INTEGER NOT NULL,
        probe_interval_seconds INTEGER NOT NULL,
        stale_timeout_seconds INTEGER NOT NULL,
        target_kind TEXT NOT NULL,
        target_ref TEXT,
        recovery_policy_override_json TEXT NOT NULL,
        monitor_config_json TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS component_watch_state (
        component_id TEXT PRIMARY KEY,
        watch_id TEXT NOT NULL,
        component_kind TEXT NOT NULL,
        subject_kind TEXT NOT NULL,
        subject_ref TEXT NOT NULL,
        last_probe_at TEXT,
        last_success_at TEXT,
        last_failure_at TEXT,
        last_outcome TEXT NOT NULL,
        last_status TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_notification_channels_kind
    ON notification_channels(kind);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_notification_rules_enabled
    ON notification_rules(enabled);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_notification_suppressions_window
    ON notification_suppressions(enabled, starts_at, ends_at);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_notifications_created_at
    ON notifications(created_at DESC);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_notifications_incident_component
    ON notifications(incident_id, component_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_notification_deliveries_status
    ON notification_deliveries(status, scheduled_for);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_component_watch_config_enabled
    ON component_watch_config(enabled, component_kind);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_component_watch_state_subject
    ON component_watch_state(subject_kind, subject_ref);
    """,
)
