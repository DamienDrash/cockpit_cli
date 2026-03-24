"""SQLite schema definitions."""

from __future__ import annotations

DATABASE_VERSION = 6

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

V5_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS operator_people (
        id TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        handle TEXT NOT NULL,
        enabled INTEGER NOT NULL,
        timezone TEXT NOT NULL,
        contact_targets_json TEXT NOT NULL,
        metadata_json TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS operator_teams (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        enabled INTEGER NOT NULL,
        description TEXT,
        default_escalation_policy_id TEXT,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS team_memberships (
        id TEXT PRIMARY KEY,
        team_id TEXT NOT NULL,
        person_id TEXT NOT NULL,
        role TEXT NOT NULL,
        enabled INTEGER NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(team_id) REFERENCES operator_teams(id),
        FOREIGN KEY(person_id) REFERENCES operator_people(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS ownership_bindings (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        team_id TEXT NOT NULL,
        enabled INTEGER NOT NULL,
        component_kind TEXT,
        component_id TEXT,
        subject_kind TEXT,
        subject_ref TEXT,
        risk_level TEXT,
        escalation_policy_id TEXT,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(team_id) REFERENCES operator_teams(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS oncall_schedules (
        id TEXT PRIMARY KEY,
        team_id TEXT NOT NULL,
        name TEXT NOT NULL,
        timezone TEXT NOT NULL,
        enabled INTEGER NOT NULL,
        coverage_kind TEXT NOT NULL,
        schedule_config_json TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(team_id) REFERENCES operator_teams(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS schedule_rotations (
        id TEXT PRIMARY KEY,
        schedule_id TEXT NOT NULL,
        name TEXT NOT NULL,
        participant_ids_json TEXT NOT NULL,
        enabled INTEGER NOT NULL,
        anchor_at TEXT,
        interval_kind TEXT NOT NULL,
        interval_count INTEGER NOT NULL,
        handoff_time TEXT,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(schedule_id) REFERENCES oncall_schedules(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS schedule_overrides (
        id TEXT PRIMARY KEY,
        schedule_id TEXT NOT NULL,
        replacement_person_id TEXT NOT NULL,
        replaced_person_id TEXT,
        starts_at TEXT NOT NULL,
        ends_at TEXT NOT NULL,
        reason TEXT NOT NULL,
        priority INTEGER NOT NULL,
        enabled INTEGER NOT NULL,
        actor TEXT,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(schedule_id) REFERENCES oncall_schedules(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS escalation_policies (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        enabled INTEGER NOT NULL,
        default_ack_timeout_seconds INTEGER NOT NULL,
        default_repeat_page_seconds INTEGER NOT NULL,
        max_repeat_pages INTEGER NOT NULL,
        terminal_behavior TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS escalation_steps (
        id TEXT PRIMARY KEY,
        policy_id TEXT NOT NULL,
        step_index INTEGER NOT NULL,
        target_kind TEXT NOT NULL,
        target_ref TEXT NOT NULL,
        ack_timeout_seconds INTEGER,
        repeat_page_seconds INTEGER,
        max_repeat_pages INTEGER,
        reminder_enabled INTEGER NOT NULL,
        stop_on_ack INTEGER NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(policy_id) REFERENCES escalation_policies(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS incident_engagements (
        id TEXT PRIMARY KEY,
        incident_id TEXT NOT NULL,
        incident_component_id TEXT NOT NULL,
        team_id TEXT,
        policy_id TEXT,
        status TEXT NOT NULL,
        current_step_index INTEGER NOT NULL,
        current_target_kind TEXT,
        current_target_ref TEXT,
        resolved_person_id TEXT,
        acknowledged_by TEXT,
        acknowledged_at TEXT,
        handoff_count INTEGER NOT NULL,
        repeat_page_count INTEGER NOT NULL,
        next_action_at TEXT,
        ack_deadline_at TEXT,
        last_page_at TEXT,
        exhausted INTEGER NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        closed_at TEXT,
        FOREIGN KEY(incident_id) REFERENCES incidents(id),
        FOREIGN KEY(team_id) REFERENCES operator_teams(id),
        FOREIGN KEY(policy_id) REFERENCES escalation_policies(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS engagement_timeline (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        engagement_id TEXT NOT NULL,
        incident_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        message TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        FOREIGN KEY(engagement_id) REFERENCES incident_engagements(id),
        FOREIGN KEY(incident_id) REFERENCES incidents(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS engagement_delivery_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        engagement_id TEXT NOT NULL,
        notification_id TEXT NOT NULL,
        delivery_id TEXT,
        purpose TEXT NOT NULL,
        step_index INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        FOREIGN KEY(engagement_id) REFERENCES incident_engagements(id),
        FOREIGN KEY(notification_id) REFERENCES notifications(id)
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_operator_people_handle
    ON operator_people(handle);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_team_memberships_team
    ON team_memberships(team_id, enabled);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ownership_bindings_team
    ON ownership_bindings(team_id, enabled);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ownership_bindings_match
    ON ownership_bindings(component_id, subject_ref, component_kind, risk_level);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_oncall_schedules_team
    ON oncall_schedules(team_id, enabled);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_schedule_rotations_schedule
    ON schedule_rotations(schedule_id, enabled);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_schedule_overrides_schedule_window
    ON schedule_overrides(schedule_id, enabled, starts_at, ends_at);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_escalation_steps_policy
    ON escalation_steps(policy_id, step_index);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_incident_engagements_incident
    ON incident_engagements(incident_id, status, updated_at DESC);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_incident_engagements_due
    ON incident_engagements(status, next_action_at);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_engagement_timeline_engagement
    ON engagement_timeline(engagement_id, recorded_at ASC);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_engagement_delivery_links_engagement
    ON engagement_delivery_links(engagement_id, created_at DESC);
    """,
)

V6_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS runbook_catalog (
        catalog_key TEXT PRIMARY KEY,
        runbook_id TEXT NOT NULL,
        runbook_version TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        risk_class TEXT NOT NULL,
        source_path TEXT NOT NULL,
        checksum TEXT NOT NULL,
        tags_json TEXT NOT NULL,
        scope_json TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        loaded_at TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS response_runs (
        id TEXT PRIMARY KEY,
        incident_id TEXT NOT NULL,
        engagement_id TEXT,
        runbook_id TEXT NOT NULL,
        runbook_version TEXT NOT NULL,
        status TEXT NOT NULL,
        current_step_index INTEGER NOT NULL,
        risk_level TEXT NOT NULL,
        elevated_mode INTEGER NOT NULL,
        started_by TEXT,
        started_at TEXT,
        updated_at TEXT NOT NULL,
        completed_at TEXT,
        summary TEXT,
        last_error TEXT,
        payload_json TEXT NOT NULL,
        FOREIGN KEY(incident_id) REFERENCES incidents(id),
        FOREIGN KEY(engagement_id) REFERENCES incident_engagements(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS response_step_runs (
        id TEXT PRIMARY KEY,
        response_run_id TEXT NOT NULL,
        step_key TEXT NOT NULL,
        step_index INTEGER NOT NULL,
        executor_kind TEXT NOT NULL,
        status TEXT NOT NULL,
        attempt_count INTEGER NOT NULL,
        guard_decision_id INTEGER,
        approval_request_id TEXT,
        started_at TEXT,
        finished_at TEXT,
        output_summary TEXT,
        output_payload_json TEXT NOT NULL,
        last_error TEXT,
        FOREIGN KEY(response_run_id) REFERENCES response_runs(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS approval_requests (
        id TEXT PRIMARY KEY,
        response_run_id TEXT NOT NULL,
        step_run_id TEXT NOT NULL,
        status TEXT NOT NULL,
        requested_by TEXT,
        required_approver_count INTEGER NOT NULL,
        required_roles_json TEXT NOT NULL,
        allow_self_approval INTEGER NOT NULL,
        reason TEXT,
        expires_at TEXT,
        created_at TEXT NOT NULL,
        resolved_at TEXT,
        payload_json TEXT NOT NULL,
        FOREIGN KEY(response_run_id) REFERENCES response_runs(id),
        FOREIGN KEY(step_run_id) REFERENCES response_step_runs(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS approval_decisions (
        id TEXT PRIMARY KEY,
        approval_request_id TEXT NOT NULL,
        approver_ref TEXT NOT NULL,
        decision TEXT NOT NULL,
        comment TEXT,
        created_at TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        FOREIGN KEY(approval_request_id) REFERENCES approval_requests(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS response_artifacts (
        id TEXT PRIMARY KEY,
        response_run_id TEXT NOT NULL,
        step_run_id TEXT,
        artifact_kind TEXT NOT NULL,
        label TEXT NOT NULL,
        storage_ref TEXT,
        summary TEXT,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(response_run_id) REFERENCES response_runs(id),
        FOREIGN KEY(step_run_id) REFERENCES response_step_runs(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS compensation_runs (
        id TEXT PRIMARY KEY,
        response_run_id TEXT NOT NULL,
        step_run_id TEXT NOT NULL,
        status TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT,
        summary TEXT,
        last_error TEXT,
        payload_json TEXT NOT NULL,
        FOREIGN KEY(response_run_id) REFERENCES response_runs(id),
        FOREIGN KEY(step_run_id) REFERENCES response_step_runs(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS postincident_reviews (
        id TEXT PRIMARY KEY,
        incident_id TEXT NOT NULL,
        response_run_id TEXT,
        status TEXT NOT NULL,
        owner_ref TEXT,
        opened_at TEXT NOT NULL,
        completed_at TEXT,
        summary TEXT,
        root_cause TEXT,
        closure_quality TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        FOREIGN KEY(incident_id) REFERENCES incidents(id),
        FOREIGN KEY(response_run_id) REFERENCES response_runs(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS review_findings (
        id TEXT PRIMARY KEY,
        review_id TEXT NOT NULL,
        category TEXT NOT NULL,
        severity TEXT NOT NULL,
        title TEXT NOT NULL,
        detail TEXT NOT NULL,
        created_at TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        FOREIGN KEY(review_id) REFERENCES postincident_reviews(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS action_items (
        id TEXT PRIMARY KEY,
        review_id TEXT NOT NULL,
        owner_ref TEXT,
        status TEXT NOT NULL,
        title TEXT NOT NULL,
        detail TEXT NOT NULL,
        due_at TEXT,
        created_at TEXT NOT NULL,
        closed_at TEXT,
        payload_json TEXT NOT NULL,
        FOREIGN KEY(review_id) REFERENCES postincident_reviews(id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS response_timeline (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        response_run_id TEXT NOT NULL,
        incident_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        message TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        FOREIGN KEY(response_run_id) REFERENCES response_runs(id),
        FOREIGN KEY(incident_id) REFERENCES incidents(id)
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_runbook_catalog_lookup
    ON runbook_catalog(runbook_id, runbook_version, loaded_at DESC);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_response_runs_incident
    ON response_runs(incident_id, status, updated_at DESC);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_response_step_runs_run
    ON response_step_runs(response_run_id, step_index);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_approval_requests_status
    ON approval_requests(status, expires_at);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_approval_requests_run
    ON approval_requests(response_run_id, status, created_at DESC);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_approval_decisions_request
    ON approval_decisions(approval_request_id, created_at ASC);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_response_artifacts_run
    ON response_artifacts(response_run_id, created_at DESC);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_compensation_runs_step
    ON compensation_runs(step_run_id, started_at DESC);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_postincident_reviews_incident
    ON postincident_reviews(incident_id, status, opened_at DESC);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_review_findings_review
    ON review_findings(review_id, created_at ASC);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_action_items_review
    ON action_items(review_id, status, due_at);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_response_timeline_run
    ON response_timeline(response_run_id, recorded_at ASC);
    """,
)
