from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from threading import Thread
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import time
import unittest

from cockpit.core.enums import (
    ActionItemStatus,
    ApprovalRequestStatus,
    ClosureQuality,
    EngagementStatus,
    EscalationTargetKind,
    NotificationChannelKind,
    NotificationEventClass,
    PostIncidentReviewStatus,
    ResponseRunStatus,
    ResponseStepStatus,
    RotationIntervalKind,
    ScheduleCoverageKind,
    SessionTargetKind,
    TargetRiskLevel,
    TeamMembershipRole,
    WatchSubjectKind,
)
from cockpit.admin.http_server import LocalWebAdminServer


@dataclass
class _NamedObject:
    name: str
    id: str = "obj-1"
    backend: str = "sqlite"
    connection_url: str | None = None
    target_ref: str | None = None
    capabilities: list[str] = None  # type: ignore[assignment]
    manifest: dict[str, object] = None  # type: ignore[assignment]
    requirement: str = "sample"
    version_pin: str | None = None
    enabled: bool = True
    status: str = "installed"

    def __post_init__(self) -> None:
        if self.capabilities is None:
            self.capabilities = ["can_query"]
        if self.manifest is None:
            self.manifest = {"summary": "sample"}


class FakeWebAdminService:
    def __init__(self) -> None:
        self.saved_pages: list[str] = []
        self.created_datasources: list[dict[str, object]] = []
        self.created_secrets: list[dict[str, object]] = []
        self.closed_tunnels: list[str] = []
        self.rotated_secrets: list[str] = []
        self.reconnected_tunnels: list[str] = []
        self.acknowledged_incidents: list[str] = []
        self.closed_incidents: list[str] = []
        self.retried_components: list[str] = []
        self.reset_components: list[str] = []
        self.saved_channels: list[dict[str, object]] = []
        self.saved_rules: list[dict[str, object]] = []
        self.saved_suppressions: list[dict[str, object]] = []
        self.saved_datasource_watches: list[dict[str, object]] = []
        self.saved_docker_watches: list[dict[str, object]] = []
        self.deleted_watches: list[str] = []
        self.probed_watches: list[str] = []
        self.saved_people: list[dict[str, object]] = []
        self.deleted_people: list[str] = []
        self.saved_teams: list[dict[str, object]] = []
        self.deleted_teams: list[str] = []
        self.saved_memberships: list[dict[str, object]] = []
        self.deleted_memberships: list[str] = []
        self.saved_bindings: list[dict[str, object]] = []
        self.deleted_bindings: list[str] = []
        self.saved_schedules: list[dict[str, object]] = []
        self.deleted_schedules: list[str] = []
        self.saved_rotations: list[dict[str, object]] = []
        self.deleted_rotations: list[str] = []
        self.saved_overrides: list[dict[str, object]] = []
        self.deleted_overrides: list[str] = []
        self.saved_policies: list[dict[str, object]] = []
        self.deleted_policies: list[str] = []
        self.acknowledged_engagements: list[str] = []
        self.repaged_engagements: list[str] = []
        self.handed_off_engagements: list[dict[str, str]] = []
        self.started_responses: list[dict[str, str | None]] = []
        self.executed_responses: list[dict[str, object]] = []
        self.retried_responses: list[dict[str, object]] = []
        self.aborted_responses: list[dict[str, object]] = []
        self.compensated_responses: list[dict[str, object]] = []
        self.approval_decisions: list[dict[str, str | None]] = []
        self.ensured_reviews: list[dict[str, str | None]] = []
        self.added_findings: list[dict[str, str]] = []
        self.added_action_items: list[dict[str, str | None]] = []
        self.updated_action_items: list[dict[str, str]] = []
        self.completed_reviews: list[dict[str, str]] = []

    def diagnostics(self) -> dict[str, object]:
        return {
            "project_root": "/tmp/cockpit",
            "python": "3.11",
            "platform": "Linux",
            "command_count": 4,
            "panel_types": ["work", "db", "response"],
            "datasources": {"total_profiles": 0, "enabled_profiles": 0, "backends": []},
            "secrets": {
                "total_entries": 1,
                "providers": ["env", "vault"],
                "keyring_available": True,
                "rotated_entries": 0,
                "vault_profiles": 1,
                "active_vault_sessions": 1,
                "cached_vault_sessions": 0,
                "renewable_leases": 1,
                "local_cache_available": True,
                "primary_provider": "vault",
            },
            "plugins": {
                "count": 0,
                "enabled": 0,
                "modules": [],
                "trusted_sources": ["git+https://github.com/"],
                "allowed_permissions": ["ui.read", "commands.execute"],
                "app_version": "0.1.0",
            },
            "plugin_hosts": [
                {
                    "component_id": "plugin-host:notes",
                    "plugin_id": "plg-notes",
                    "display_name": "Plugin host Notes",
                    "alive": True,
                    "status": "host_running",
                }
            ],
            "tunnels": [
                {
                    "profile_id": "pg-main",
                    "target_ref": "deploy@example.com",
                    "remote_host": "db.internal",
                    "remote_port": 5432,
                    "local_port": 15432,
                    "alive": True,
                }
            ],
            "health": {
                "healthy": 3,
                "degraded": 0,
                "recovering": 1,
                "failed": 0,
                "quarantined": 1,
            },
            "quarantined_components": [
                {
                    "component_id": "ssh-tunnel:pg-main",
                    "component_kind": "ssh_tunnel",
                    "status": "quarantined",
                }
            ],
            "active_incidents": [
                {
                    "id": "inc-1",
                    "component_id": "ssh-tunnel:pg-main",
                    "component_kind": "ssh_tunnel",
                    "severity": "high",
                    "status": "open",
                    "summary": "tunnel exited",
                    "updated_at": "2026-03-23T00:00:00+00:00",
                }
            ],
            "recent_recovery_attempts": [
                {"id": "rcv-1", "status": "failed"},
            ],
            "notifications": {
                "counts": {
                    "queued": 1,
                    "suppressed": 1,
                    "delivered": 2,
                    "delivering": 0,
                    "failed": 1,
                },
                "recent": [
                    {
                        "id": "ntf-1",
                        "title": "Tunnel unhealthy",
                        "summary": "ssh tunnel is reconnecting",
                        "status": "queued",
                    }
                ],
                "recent_failures": [
                    {
                        "id": "ndl-1",
                        "channel_id": "slack-ops",
                        "attempt_number": 2,
                        "error_message": "timeout",
                    }
                ],
            },
            "notification_channels": [
                {
                    "id": "internal-default",
                    "name": "Internal",
                }
            ],
            "notification_rules": [
                {
                    "id": "rule-1",
                    "name": "Default",
                }
            ],
            "suppression_rules": [
                {
                    "id": "sup-1",
                    "name": "Maintenance mute",
                }
            ],
            "watches": {
                "configs": [
                    {
                        "id": "wch-1",
                        "component_id": "watch:datasource:pg-main",
                    }
                ],
                "states": [
                    {
                        "component_id": "watch:datasource:pg-main",
                        "last_status": "unreachable",
                    }
                ],
                "unhealthy": [
                    {
                        "component_id": "watch:datasource:pg-main",
                        "last_status": "unreachable",
                    }
                ],
            },
            "oncall": {
                "people": [_OperatorPersonObject().to_dict()],
                "teams": [_OperatorTeamObject().to_dict()],
                "bindings": [_OwnershipBindingObject().to_dict()],
                "schedules": [_ScheduleObject().to_dict()],
                "engagements": {
                    "counts": {"active": 1, "blocked": 0},
                    "active": [_EngagementObject().to_dict()],
                    "blocked": [],
                    "recent_exhausted": [],
                },
                "policies": [_EscalationPolicyObject().to_dict()],
            },
            "response": {
                "active_runs": [_ResponseRunObject().to_dict()],
                "pending_approvals": [
                    {
                        "request": _ApprovalRequestObject().to_dict(),
                        "decisions": [_ApprovalDecisionObject().to_dict()],
                    }
                ],
                "open_reviews": [_ReviewObject().to_dict()],
            },
            "runbooks": [_RunbookObject().to_dict()],
            "reviews": [_ReviewObject().to_dict()],
            "tasks": [
                {
                    "name": "web-admin-server",
                    "component_kind": "web_admin",
                    "alive": True,
                }
            ],
            "web_admin_tasks": [
                {
                    "name": "web-admin-server",
                    "component_kind": "web_admin",
                    "alive": True,
                }
            ],
            "operations": {
                "docker": [{"name": "web"}],
                "db": [{"profile_id": "pg-main"}],
                "curl": [{"url": "https://example.com"}],
                "notification": [{"summary": "internal notification stored"}],
                "recent_guard_decisions": [{"outcome": "allow"}],
                "recent_operations": [{"summary": "ok"}],
            },
            "tools": {"git": True, "docker": True, "ssh": True},
        }

    def save_last_page(self, page: str) -> None:
        self.saved_pages.append(page)

    def list_datasources(self):
        return []

    def create_datasource(self, payload: dict[str, object]):
        self.created_datasources.append(dict(payload))
        return _NamedObject(name=payload.get("name", "New datasource"))

    def delete_datasource(self, profile_id: str) -> None:
        del profile_id

    def inspect_datasource(self, profile_id: str):
        del profile_id
        return _NamedObject(name="Inspection")

    def execute_datasource(
        self,
        profile_id: str,
        statement: str,
        *,
        operation: str,
        confirmed: bool = False,
        elevated_mode: bool = False,
    ):
        del profile_id, statement, operation, confirmed, elevated_mode
        return SimpleResult("Datasource command executed.")

    def last_datasource_result(self):
        return {"profile_id": "pg-main", "result": {"message": "ok"}}

    def list_secrets(self):
        return [_SecretObject()]

    def create_secret(self, payload: dict[str, object]):
        self.created_secrets.append(dict(payload))
        return _SecretObject(name=str(payload.get("name", "analytics-pass")))

    def delete_secret(self, name: str, *, purge_value: bool = False) -> None:
        del name, purge_value

    def rotate_secret(self, name: str, *, secret_value: str):
        del secret_value
        self.rotated_secrets.append(name)
        return _SecretObject(
            name=name,
            provider="keyring",
            reference={"provider": "keyring", "service": "cockpit", "username": name},
        )

    def list_vault_profiles(self):
        return [
            _VaultProfileObject(),
        ]

    def save_vault_profile(self, payload: dict[str, object]):
        del payload
        return _VaultProfileObject()

    def delete_vault_profile(self, profile_id: str, *, revoke: bool = False) -> None:
        del profile_id, revoke

    def login_vault_profile(self, profile_id: str, payload: dict[str, object]):
        del payload
        return _VaultSessionObject(profile_id=profile_id or "ops-vault")

    def logout_vault_profile(self, profile_id: str, *, revoke: bool = False) -> None:
        del profile_id, revoke

    def vault_profile_health(self, profile_id: str) -> dict[str, object]:
        return {
            "profile_id": profile_id,
            "health": {"initialized": True, "sealed": False},
        }

    def list_vault_sessions(self):
        return [_VaultSessionObject()]

    def list_vault_leases(self):
        return [_VaultLeaseObject()]

    def renew_vault_lease(self, lease_id: str, *, increment_seconds: int | None = None):
        del increment_seconds
        return _VaultLeaseObject(lease_id=lease_id)

    def revoke_vault_lease(self, lease_id: str) -> None:
        del lease_id

    def transit_operation(self, payload: dict[str, object]) -> dict[str, object]:
        del payload
        return {"operation": "encrypt", "ciphertext": "vault:v1:deadbeef"}

    def list_plugins(self):
        return []

    def install_plugin(self, payload: dict[str, str]):
        del payload
        return _NamedObject(name="Plugin")

    def update_plugin(self, plugin_id: str):
        del plugin_id
        return _NamedObject(name="Plugin")

    def toggle_plugin(self, plugin_id: str, enabled: bool):
        del plugin_id, enabled
        return _NamedObject(name="Plugin")

    def pin_plugin(self, plugin_id: str, version_pin: str | None):
        del plugin_id, version_pin
        return _NamedObject(name="Plugin")

    def remove_plugin(self, plugin_id: str) -> None:
        del plugin_id

    def list_notification_channels(self):
        return [_NotificationChannelObject()]

    def save_notification_channel(self, payload: dict[str, object]):
        self.saved_channels.append(dict(payload))
        return _NotificationChannelObject(
            id=str(payload.get("channel_id", "nch-1") or "nch-1"),
            name=str(payload.get("name", "Ops Channel")),
            kind=NotificationChannelKind(str(payload.get("kind", "internal"))),
        )

    def delete_notification_channel(self, channel_id: str) -> None:
        del channel_id

    def list_notification_rules(self):
        return [_NotificationRuleObject()]

    def save_notification_rule(self, payload: dict[str, object]):
        self.saved_rules.append(dict(payload))
        return _NotificationRuleObject(
            id=str(payload.get("rule_id", "nrl-1") or "nrl-1"),
            name=str(payload.get("name", "Ops Rule")),
        )

    def delete_notification_rule(self, rule_id: str) -> None:
        del rule_id

    def list_suppression_rules(self):
        return [_SuppressionRuleObject()]

    def save_suppression_rule(self, payload: dict[str, object]):
        self.saved_suppressions.append(dict(payload))
        return _SuppressionRuleObject(
            id=str(payload.get("suppression_id", "sup-1") or "sup-1"),
            name=str(payload.get("name", "Maintenance mute")),
            reason=str(payload.get("reason", "Maintenance")),
        )

    def delete_suppression_rule(self, suppression_id: str) -> None:
        del suppression_id

    def list_notifications(self, *, status=None):
        del status
        return [
            {
                "id": "ntf-1",
                "title": "Tunnel unhealthy",
                "event_class": "incident_opened",
                "severity": "high",
                "status": "queued",
                "summary": "ssh tunnel is reconnecting",
            }
        ]

    def notification_detail(self, notification_id: str):
        del notification_id
        return {
            "notification": {"id": "ntf-1", "title": "Tunnel unhealthy"},
            "deliveries": [{"id": "ndl-1", "status": "failed"}],
        }

    def notification_summary(self):
        return self.diagnostics()["notifications"]

    def list_watch_configs(self):
        return [_WatchConfigObject()]

    def list_watch_states(self):
        return [
            {
                "component_id": "watch:datasource:pg-main",
                "watch_id": "wch-1",
                "last_status": "unreachable",
                "last_probe_at": "2026-03-23T00:00:00+00:00",
            }
        ]

    def save_datasource_watch(self, payload: dict[str, object]):
        self.saved_datasource_watches.append(dict(payload))
        return _WatchConfigObject(
            id=str(payload.get("watch_id", "wch-1") or "wch-1"),
            name=str(payload.get("name", "Datasource Watch")),
            subject_ref=str(payload.get("profile_id", "pg-main")),
        )

    def save_docker_watch(self, payload: dict[str, object]):
        self.saved_docker_watches.append(dict(payload))
        return _WatchConfigObject(
            id=str(payload.get("watch_id", "wch-2") or "wch-2"),
            name=str(payload.get("name", "Docker Watch")),
            subject_kind=WatchSubjectKind.DOCKER_CONTAINER,
            subject_ref=str(payload.get("container_ref", "web")),
            component_id=f"watch:docker:{payload.get('container_ref', 'web')}",
            target_kind=SessionTargetKind(str(payload.get("target_kind", "local"))),
            target_ref=payload.get("target_ref"),
        )

    def delete_watch(self, watch_id: str) -> None:
        self.deleted_watches.append(watch_id)

    def probe_watch(self, watch_id: str):
        self.probed_watches.append(watch_id)
        return {"watch_id": watch_id, "last_status": "reachable"}

    def list_layouts(self):
        return [
            _LayoutObject(
                id="default",
                name="Default",
                tabs=[
                    {
                        "id": "work",
                        "name": "Work",
                    }
                ],
            )
        ]

    def layout_summaries(self):
        return [
            {
                "id": "default",
                "name": "Default",
                "tab_count": 1,
                "tabs": [{"id": "work", "name": "Work"}],
            }
        ]

    def load_layout_document(self, layout_id: str):
        del layout_id
        return {
            "id": "default",
            "name": "Default",
            "focus_path": [],
            "tabs": [
                {
                    "id": "work",
                    "name": "Work",
                    "root_split": {
                        "orientation": "vertical",
                        "ratio": 1.0,
                        "children": [{"panel_id": "work-panel", "panel_type": "work"}],
                    },
                }
            ],
        }

    def validate_layout_document(self, payload: dict[str, object]):
        return {
            "ok": True,
            "errors": [],
            "layout": payload,
        }

    def save_layout_document(self, payload: dict[str, object]):
        return _LayoutObject(
            id=str(payload.get("id", "default")),
            name=str(payload.get("name", "Default")),
            tabs=[
                {
                    "id": "work",
                    "name": "Work",
                }
            ],
        )

    def clone_layout(
        self, source_layout_id: str, target_layout_id: str, name: str | None = None
    ):
        del source_layout_id, target_layout_id, name
        return _NamedObject(name="Layout")

    def toggle_layout_tab(self, layout_id: str, tab_id: str):
        del layout_id, tab_id
        return _NamedObject(name="Layout")

    def set_layout_ratio(self, layout_id: str, tab_id: str, ratio: float):
        del layout_id, tab_id, ratio
        return _NamedObject(name="Layout")

    def add_panel_to_layout(
        self, layout_id: str, tab_id: str, panel_id: str, panel_type: str
    ):
        del layout_id, tab_id, panel_id, panel_type
        return _NamedObject(name="Layout")

    def remove_panel_from_layout(self, layout_id: str, tab_id: str, panel_id: str):
        del layout_id, tab_id, panel_id
        return _NamedObject(name="Layout")

    def replace_panel_in_layout(
        self,
        layout_id: str,
        tab_id: str,
        existing_panel_id: str,
        replacement_panel_id: str,
        replacement_panel_type: str,
    ):
        del (
            layout_id,
            tab_id,
            existing_panel_id,
            replacement_panel_id,
            replacement_panel_type,
        )
        return _NamedObject(name="Layout")

    def move_panel_in_layout(
        self,
        layout_id: str,
        tab_id: str,
        panel_id: str,
        direction: str,
    ):
        del layout_id, tab_id, panel_id, direction
        return _NamedObject(name="Layout")

    def available_panels(self):
        return [
            ("work", "work-panel", "Work"),
            ("logs", "logs-panel", "Logs"),
            ("ops", "ops-panel", "Ops"),
            ("response", "response-panel", "Response"),
        ]

    def close_tunnel(self, profile_id: str) -> None:
        self.closed_tunnels.append(profile_id)

    def reconnect_tunnel(self, profile_id: str) -> None:
        self.reconnected_tunnels.append(profile_id)

    def list_incidents(
        self, *, status=None, severity=None, component_kind=None, search=None
    ):
        del status, severity, component_kind, search
        return [
            _IncidentObject(),
        ]

    def incident_detail(self, incident_id: str):
        del incident_id
        return _IncidentDetailObject()

    def acknowledge_incident(self, incident_id: str):
        self.acknowledged_incidents.append(incident_id)
        return _IncidentObject(id=incident_id, status="acknowledged")

    def close_incident(self, incident_id: str):
        self.closed_incidents.append(incident_id)
        return _IncidentObject(id=incident_id, status="closed")

    def reset_component_quarantine(self, component_id: str) -> None:
        self.reset_components.append(component_id)

    def retry_component_recovery(self, component_id: str) -> bool:
        self.retried_components.append(component_id)
        return True

    def list_operator_people(self):
        return [_OperatorPersonObject()]

    def save_operator_person(self, payload: dict[str, object]):
        self.saved_people.append(dict(payload))
        return _OperatorPersonObject(
            id=str(payload.get("person_id", "opr-1") or "opr-1"),
            display_name=str(payload.get("display_name", "Alice Example")),
            handle=str(payload.get("handle", "alice")),
        )

    def delete_operator_person(self, person_id: str) -> None:
        self.deleted_people.append(person_id)

    def list_operator_teams(self):
        return [_OperatorTeamObject()]

    def save_operator_team(self, payload: dict[str, object]):
        self.saved_teams.append(dict(payload))
        return _OperatorTeamObject(
            id=str(payload.get("team_id", "team-1") or "team-1"),
            name=str(payload.get("name", "Platform Ops")),
            default_escalation_policy_id=payload.get("default_escalation_policy_id")
            or None,
        )

    def delete_operator_team(self, team_id: str) -> None:
        self.deleted_teams.append(team_id)

    def list_team_memberships(self):
        return [_MembershipObject()]

    def save_team_membership(self, payload: dict[str, object]):
        self.saved_memberships.append(dict(payload))
        return _MembershipObject(
            id=str(payload.get("membership_id", "mem-1") or "mem-1"),
            team_id=str(payload.get("team_id", "team-1")),
            person_id=str(payload.get("person_id", "opr-1")),
            role=TeamMembershipRole(
                str(payload.get("role", TeamMembershipRole.MEMBER.value))
            ),
        )

    def delete_team_membership(self, membership_id: str) -> None:
        self.deleted_memberships.append(membership_id)

    def list_ownership_bindings(self):
        return [_OwnershipBindingObject()]

    def save_ownership_binding(self, payload: dict[str, object]):
        self.saved_bindings.append(dict(payload))
        return _OwnershipBindingObject(
            id=str(payload.get("binding_id", "own-1") or "own-1"),
            name=str(payload.get("name", "Prod docker ownership")),
            team_id=str(payload.get("team_id", "team-1")),
        )

    def delete_ownership_binding(self, binding_id: str) -> None:
        self.deleted_bindings.append(binding_id)

    def list_oncall_schedules(self):
        return [_ScheduleObject()]

    def save_oncall_schedule(self, payload: dict[str, object]):
        self.saved_schedules.append(dict(payload))
        return _ScheduleObject(
            id=str(payload.get("schedule_id", "sch-1") or "sch-1"),
            team_id=str(payload.get("team_id", "team-1")),
            name=str(payload.get("name", "Primary Hours")),
            coverage_kind=ScheduleCoverageKind(
                str(payload.get("coverage_kind", ScheduleCoverageKind.ALWAYS.value))
            ),
        )

    def delete_oncall_schedule(self, schedule_id: str) -> None:
        self.deleted_schedules.append(schedule_id)

    def list_rotations(self, schedule_id: str):
        del schedule_id
        return [_RotationObject()]

    def save_rotation(self, payload: dict[str, object]):
        self.saved_rotations.append(dict(payload))
        return _RotationObject(
            id=str(payload.get("rotation_id", "rot-1") or "rot-1"),
            schedule_id=str(payload.get("schedule_id", "sch-1")),
            name=str(payload.get("name", "Primary Rotation")),
        )

    def delete_rotation(self, rotation_id: str) -> None:
        self.deleted_rotations.append(rotation_id)

    def list_overrides(self, schedule_id: str):
        del schedule_id
        return [_OverrideObject()]

    def save_override(self, payload: dict[str, object]):
        self.saved_overrides.append(dict(payload))
        return _OverrideObject(
            id=str(payload.get("override_id", "ovr-1") or "ovr-1"),
            schedule_id=str(payload.get("schedule_id", "sch-1")),
            replacement_person_id=str(payload.get("replacement_person_id", "opr-1")),
        )

    def delete_override(self, override_id: str) -> None:
        self.deleted_overrides.append(override_id)

    def list_escalation_policies(self):
        return [_EscalationPolicyObject()]

    def escalation_policy_detail(self, policy_id: str):
        del policy_id
        return _EscalationPolicyDetailObject()

    def save_escalation_policy(self, payload: dict[str, object]):
        self.saved_policies.append(dict(payload))
        return _EscalationPolicyDetailObject(
            policy=_EscalationPolicyObject(
                id=str(payload.get("policy_id", "epc-1") or "epc-1"),
                name=str(payload.get("name", "Default escalation")),
            )
        )

    def delete_escalation_policy(self, policy_id: str) -> None:
        self.deleted_policies.append(policy_id)

    def list_engagements(self, *, active_only: bool = False):
        del active_only
        return [_EngagementObject().to_dict()]

    def engagement_detail(self, engagement_id: str):
        del engagement_id
        return _EngagementDetailObject()

    def acknowledge_engagement(self, engagement_id: str, *, actor: str = "web-admin"):
        del actor
        self.acknowledged_engagements.append(engagement_id)
        return _EngagementObject(id=engagement_id, status=EngagementStatus.ACKNOWLEDGED)

    def handoff_engagement(
        self,
        engagement_id: str,
        *,
        actor: str = "web-admin",
        target_kind: str = "person",
        target_ref: str,
    ):
        self.handed_off_engagements.append(
            {
                "engagement_id": engagement_id,
                "actor": actor,
                "target_kind": target_kind,
                "target_ref": target_ref,
            }
        )
        return _EngagementObject(id=engagement_id)

    def repage_engagement(self, engagement_id: str, *, actor: str = "web-admin"):
        del actor
        self.repaged_engagements.append(engagement_id)
        return _EngagementObject(id=engagement_id)

    def list_runbooks(self):
        return [_RunbookObject()]

    def runbook_detail(self, runbook_id: str, *, version: str | None = None):
        del version
        return _RunbookObject(id=runbook_id or "docker-container-unhealthy")

    def list_response_runs(self, *, active_only: bool = False):
        del active_only
        return [_ResponseRunObject().to_dict()]

    def response_run_detail(self, run_id: str):
        return _ResponseDetailObject(
            response_run=_ResponseRunObject(id=run_id or "rrn-1")
        )

    def start_response_run(
        self,
        *,
        incident_id: str,
        runbook_id: str,
        actor: str = "web-admin",
        runbook_version: str | None = None,
        engagement_id: str | None = None,
    ):
        self.started_responses.append(
            {
                "incident_id": incident_id,
                "runbook_id": runbook_id,
                "actor": actor,
                "runbook_version": runbook_version,
                "engagement_id": engagement_id,
            }
        )
        return _ResponseRunObject(
            id="rrn-started",
            incident_id=incident_id,
            runbook_id=runbook_id,
            runbook_version=runbook_version or "1.0.0",
        )

    def execute_response_run(
        self,
        run_id: str,
        *,
        actor: str = "web-admin",
        confirmed: bool = False,
        elevated_mode: bool = False,
        notes: str | None = None,
    ):
        self.executed_responses.append(
            {
                "run_id": run_id,
                "actor": actor,
                "confirmed": confirmed,
                "elevated_mode": elevated_mode,
                "notes": notes,
            }
        )
        return _ResponseRunObject(id=run_id, summary="Executed current response step.")

    def retry_response_run(
        self,
        run_id: str,
        *,
        actor: str = "web-admin",
        confirmed: bool = False,
        elevated_mode: bool = False,
        notes: str | None = None,
    ):
        self.retried_responses.append(
            {
                "run_id": run_id,
                "actor": actor,
                "confirmed": confirmed,
                "elevated_mode": elevated_mode,
                "notes": notes,
            }
        )
        return _ResponseRunObject(id=run_id, summary="Retrying current response step.")

    def abort_response_run(
        self, run_id: str, *, actor: str = "web-admin", reason: str = "web-admin abort"
    ):
        self.aborted_responses.append(
            {"run_id": run_id, "actor": actor, "reason": reason}
        )
        return _ResponseRunObject(
            id=run_id, status=ResponseRunStatus.ABORTED, summary="Response run aborted."
        )

    def compensate_response_run(
        self,
        run_id: str,
        *,
        actor: str = "web-admin",
        confirmed: bool = False,
        elevated_mode: bool = False,
    ):
        self.compensated_responses.append(
            {
                "run_id": run_id,
                "actor": actor,
                "confirmed": confirmed,
                "elevated_mode": elevated_mode,
            }
        )
        return _ResponseRunObject(id=run_id, summary="Compensation completed.")

    def list_pending_approvals(self):
        return [
            {
                "request": _ApprovalRequestObject().to_dict(),
                "decisions": [_ApprovalDecisionObject().to_dict()],
            }
        ]

    def decide_approval(
        self,
        request_id: str,
        *,
        approver_ref: str = "web-admin",
        decision: str = "approve",
        comment: str | None = None,
    ):
        self.approval_decisions.append(
            {
                "request_id": request_id,
                "approver_ref": approver_ref,
                "decision": decision,
                "comment": comment,
            }
        )
        return _ResponseRunObject(
            id="rrn-1",
            status=ResponseRunStatus.READY,
            summary=f"Approval request {request_id} handled.",
        )

    def list_reviews(self):
        return [_ReviewObject()]

    def review_detail(self, review_id: str):
        return _ReviewDetailObject(review=_ReviewObject(id=review_id or "rvw-1"))

    def ensure_review(
        self,
        *,
        incident_id: str,
        response_run_id: str | None = None,
        owner_ref: str | None = None,
    ):
        self.ensured_reviews.append(
            {
                "incident_id": incident_id,
                "response_run_id": response_run_id,
                "owner_ref": owner_ref,
            }
        )
        return _ReviewObject(
            id="rvw-opened",
            incident_id=incident_id,
            response_run_id=response_run_id,
            owner_ref=owner_ref,
        )

    def add_review_finding(
        self,
        review_id: str,
        *,
        category: str,
        severity: str,
        title: str,
        detail: str,
    ):
        self.added_findings.append(
            {
                "review_id": review_id,
                "category": category,
                "severity": severity,
                "title": title,
                "detail": detail,
            }
        )
        return _ReviewFindingObject(
            id="rfn-added", review_id=review_id, title=title, detail=detail
        )

    def add_review_action_item(
        self,
        review_id: str,
        *,
        owner_ref: str | None,
        title: str,
        detail: str,
        due_at: datetime | None = None,
    ):
        self.added_action_items.append(
            {
                "review_id": review_id,
                "owner_ref": owner_ref,
                "title": title,
                "detail": detail,
                "due_at": due_at.isoformat() if due_at is not None else None,
            }
        )
        return _ActionItemObject(
            id="act-added",
            review_id=review_id,
            owner_ref=owner_ref,
            title=title,
            detail=detail,
        )

    def set_review_action_item_status(self, action_item_id: str, *, status: str):
        self.updated_action_items.append(
            {"action_item_id": action_item_id, "status": status}
        )
        return _ActionItemObject(id=action_item_id, status=ActionItemStatus(status))

    def complete_review(
        self,
        review_id: str,
        *,
        summary: str,
        root_cause: str,
        closure_quality: str,
    ):
        self.completed_reviews.append(
            {
                "review_id": review_id,
                "summary": summary,
                "root_cause": root_cause,
                "closure_quality": closure_quality,
            }
        )
        return _ReviewObject(
            id=review_id,
            status=PostIncidentReviewStatus.COMPLETED,
            summary=summary,
            root_cause=root_cause,
            closure_quality=ClosureQuality(closure_quality),
        )


@dataclass
class _SecretObject:
    name: str = "analytics-pass"
    provider: str = "env"
    reference: dict[str, object] = None  # type: ignore[assignment]
    description: str | None = "DB password"
    updated_at: datetime | None = datetime(2026, 3, 23, tzinfo=UTC)
    revision: int = 1

    def __post_init__(self) -> None:
        if self.reference is None:
            self.reference = {"provider": "env", "name": "ANALYTICS_DB_PASS"}


@dataclass
class _VaultProfileObject:
    id: str = "ops-vault"
    name: str = "Ops Vault"
    address: str = "https://vault.internal:8200"
    auth_type: str = "token"
    auth_mount: str | None = None
    role_name: str | None = None
    allow_local_cache: bool = True
    verify_tls: bool = True


@dataclass
class _VaultSessionObject:
    profile_id: str = "ops-vault"
    auth_type: str = "token"
    cached: bool = False
    renewable: bool = True
    expires_at: datetime | None = datetime(2026, 3, 23, tzinfo=UTC)


@dataclass
class _VaultLeaseObject:
    lease_id: str = "lease-1"
    profile_id: str = "ops-vault"
    source_kind: str = "dynamic"
    mount: str = "database"
    path: str = "creds/app"
    renewable: bool = True
    expires_at: datetime | None = datetime(2026, 3, 23, tzinfo=UTC)


@dataclass
class SimpleResult:
    message: str


@dataclass
class _NotificationChannelObject:
    id: str = "internal-default"
    name: str = "Internal"
    kind: NotificationChannelKind = NotificationChannelKind.INTERNAL
    enabled: bool = True
    risk_level: TargetRiskLevel = TargetRiskLevel.DEV
    target: dict[str, object] = field(default_factory=dict)
    max_attempts: int = 3


@dataclass
class _NotificationRuleObject:
    id: str = "rule-1"
    name: str = "Default"
    event_classes: tuple[NotificationEventClass, ...] = (
        NotificationEventClass.INCIDENT_OPENED,
    )
    channel_ids: tuple[str, ...] = ("internal-default",)
    delivery_priority: int = 100
    dedupe_window_seconds: int = 300
    enabled: bool = True


@dataclass
class _SuppressionRuleObject:
    id: str = "sup-1"
    name: str = "Maintenance mute"
    reason: str = "Maintenance"
    starts_at: str | None = "2026-03-23T00:00:00+00:00"
    ends_at: str | None = "2026-03-23T02:00:00+00:00"
    event_classes: tuple[NotificationEventClass, ...] = (
        NotificationEventClass.COMPONENT_DEGRADED,
    )


@dataclass
class _WatchConfigObject:
    id: str = "wch-1"
    name: str = "Datasource Watch"
    subject_kind: WatchSubjectKind = WatchSubjectKind.DATASOURCE
    subject_ref: str = "pg-main"
    enabled: bool = True
    probe_interval_seconds: int = 30
    stale_timeout_seconds: int = 90
    component_id: str = "watch:datasource:pg-main"
    target_kind: SessionTargetKind = SessionTargetKind.LOCAL
    target_ref: str | None = None


@dataclass
class _OperatorContactTargetObject:
    channel_id: str = "slack-alice"
    label: str = "Slack"
    enabled: bool = True
    priority: int = 100

    def to_dict(self) -> dict[str, object]:
        return {
            "channel_id": self.channel_id,
            "label": self.label,
            "enabled": self.enabled,
            "priority": self.priority,
        }


@dataclass
class _OperatorPersonObject:
    id: str = "opr-1"
    display_name: str = "Alice Example"
    handle: str = "alice"
    enabled: bool = True
    timezone: str = "Europe/Berlin"
    contact_targets: list[_OperatorContactTargetObject] = field(
        default_factory=lambda: [_OperatorContactTargetObject()]
    )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "handle": self.handle,
            "enabled": self.enabled,
            "timezone": self.timezone,
            "contact_targets": [item.to_dict() for item in self.contact_targets],
        }


@dataclass
class _OperatorTeamObject:
    id: str = "team-1"
    name: str = "Platform Ops"
    enabled: bool = True
    description: str | None = "Primary operators"
    default_escalation_policy_id: str | None = "epc-1"

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
            "description": self.description,
            "default_escalation_policy_id": self.default_escalation_policy_id,
        }


@dataclass
class _MembershipObject:
    id: str = "mem-1"
    team_id: str = "team-1"
    person_id: str = "opr-1"
    role: TeamMembershipRole = TeamMembershipRole.MEMBER
    enabled: bool = True


@dataclass
class _OwnershipBindingObject:
    id: str = "own-1"
    name: str = "Docker Web"
    team_id: str = "team-1"
    enabled: bool = True
    component_kind: str = "docker_runtime"
    component_id: str = "docker:web"
    subject_kind: str | None = None
    subject_ref: str | None = None
    risk_level: str | None = "prod"
    escalation_policy_id: str | None = "epc-1"

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "team_id": self.team_id,
            "enabled": self.enabled,
            "component_kind": self.component_kind,
            "component_id": self.component_id,
            "subject_kind": self.subject_kind,
            "subject_ref": self.subject_ref,
            "risk_level": self.risk_level,
            "escalation_policy_id": self.escalation_policy_id,
        }


@dataclass
class _ScheduleObject:
    id: str = "sch-1"
    team_id: str = "team-1"
    name: str = "Primary Hours"
    timezone: str = "Europe/Berlin"
    enabled: bool = True
    coverage_kind: ScheduleCoverageKind = ScheduleCoverageKind.ALWAYS
    schedule_config: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "team_id": self.team_id,
            "name": self.name,
            "timezone": self.timezone,
            "enabled": self.enabled,
            "coverage_kind": self.coverage_kind.value,
            "schedule_config": self.schedule_config,
        }


@dataclass
class _RotationObject:
    id: str = "rot-1"
    schedule_id: str = "sch-1"
    name: str = "Primary Rotation"
    participant_ids: tuple[str, ...] = ("opr-1",)
    enabled: bool = True
    anchor_at: str = "2026-03-24T09:00:00+01:00"
    interval_kind: RotationIntervalKind = RotationIntervalKind.DAYS
    interval_count: int = 7
    handoff_time: str | None = "09:00"


@dataclass
class _OverrideObject:
    id: str = "ovr-1"
    schedule_id: str = "sch-1"
    replacement_person_id: str = "opr-1"
    replaced_person_id: str | None = None
    starts_at: str = "2026-03-24T18:00:00+01:00"
    ends_at: str = "2026-03-25T08:00:00+01:00"
    reason: str = "Vacation cover"
    priority: int = 100
    actor: str | None = "operator"


@dataclass
class _EscalationPolicyObject:
    id: str = "epc-1"
    name: str = "Default escalation"
    enabled: bool = True
    default_ack_timeout_seconds: int = 900
    default_repeat_page_seconds: int = 300
    max_repeat_pages: int = 2

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
            "default_ack_timeout_seconds": self.default_ack_timeout_seconds,
            "default_repeat_page_seconds": self.default_repeat_page_seconds,
            "max_repeat_pages": self.max_repeat_pages,
        }


@dataclass
class _EscalationStepObject:
    id: str = "est-1"
    step_index: int = 0
    target_kind: EscalationTargetKind = EscalationTargetKind.TEAM
    target_ref: str = "team-1"

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "step_index": self.step_index,
            "target_kind": self.target_kind.value,
            "target_ref": self.target_ref,
        }


@dataclass
class _EscalationPolicyDetailObject:
    policy: _EscalationPolicyObject = field(default_factory=_EscalationPolicyObject)
    steps: list[_EscalationStepObject] = field(
        default_factory=lambda: [_EscalationStepObject()]
    )


@dataclass
class _EngagementObject:
    id: str = "eng-1"
    incident_id: str = "inc-1"
    incident_component_id: str = "ssh-tunnel:pg-main"
    team_id: str | None = "team-1"
    policy_id: str | None = "epc-1"
    status: EngagementStatus = EngagementStatus.ACTIVE
    current_step_index: int = 0
    current_target_kind: EscalationTargetKind = EscalationTargetKind.TEAM
    current_target_ref: str = "team-1"
    ack_deadline_at: str = "2026-03-24T10:15:00+00:00"
    next_action_at: str = "2026-03-24T10:05:00+00:00"
    updated_at: str = "2026-03-24T10:00:00+00:00"

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "incident_id": self.incident_id,
            "incident_component_id": self.incident_component_id,
            "team_id": self.team_id,
            "policy_id": self.policy_id,
            "status": self.status.value,
            "current_step_index": self.current_step_index,
            "current_target_kind": self.current_target_kind.value,
            "current_target_ref": self.current_target_ref,
            "ack_deadline_at": self.ack_deadline_at,
            "next_action_at": self.next_action_at,
            "updated_at": self.updated_at,
        }


@dataclass
class _EngagementTimelineObject:
    event_type: str = "paged"

    def to_dict(self) -> dict[str, object]:
        return {"event_type": self.event_type}


@dataclass
class _EngagementDeliveryLinkObject:
    notification_id: str = "ntf-1"

    def to_dict(self) -> dict[str, object]:
        return {"notification_id": self.notification_id}


@dataclass
class _IncidentObject:
    id: str = "inc-1"
    component_id: str = "ssh-tunnel:pg-main"
    component_kind: str = "ssh_tunnel"
    severity: str = "high"
    status: str = "open"
    title: str = "Tunnel unhealthy"
    summary: str = "tunnel exited"
    updated_at: str = "2026-03-23T00:00:00+00:00"

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "component_id": self.component_id,
            "component_kind": self.component_kind,
            "severity": self.severity,
            "status": self.status,
            "title": self.title,
            "summary": self.summary,
            "updated_at": self.updated_at,
        }


@dataclass
class _IncidentStatusValue:
    value: str


@dataclass
class _IncidentDetailIncident:
    id: str = "inc-1"
    component_id: str = "ssh-tunnel:pg-main"
    title: str = "Tunnel unhealthy"
    summary: str = "tunnel exited"
    status: _IncidentStatusValue = field(
        default_factory=lambda: _IncidentStatusValue("open")
    )
    severity: _IncidentStatusValue = field(
        default_factory=lambda: _IncidentStatusValue("high")
    )


@dataclass
class _IncidentTimelineItem:
    event_type: str = "opened"

    def to_dict(self) -> dict[str, object]:
        return {"event_type": self.event_type}


@dataclass
class _RecoveryAttemptItem:
    attempt_number: int = 1

    def to_dict(self) -> dict[str, object]:
        return {"attempt_number": self.attempt_number}


@dataclass
class _IncidentDetailObject:
    incident: _IncidentDetailIncident = field(default_factory=_IncidentDetailIncident)
    timeline: list[_IncidentTimelineItem] = None  # type: ignore[assignment]
    recovery_attempts: list[_RecoveryAttemptItem] = None  # type: ignore[assignment]
    current_health: dict[str, object] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.timeline is None:
            self.timeline = [_IncidentTimelineItem()]
        if self.recovery_attempts is None:
            self.recovery_attempts = [_RecoveryAttemptItem()]
        if self.current_health is None:
            self.current_health = {"status": "recovering"}


@dataclass
class _EngagementDetailObject:
    engagement: _EngagementObject = field(default_factory=_EngagementObject)
    incident: _IncidentDetailIncident = field(default_factory=_IncidentDetailIncident)
    timeline: list[_EngagementTimelineObject] = field(
        default_factory=lambda: [_EngagementTimelineObject()]
    )
    delivery_links: list[_EngagementDeliveryLinkObject] = field(
        default_factory=lambda: [_EngagementDeliveryLinkObject()]
    )


@dataclass
class _LayoutObject:
    id: str
    name: str
    tabs: list[dict[str, str]]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "focus_path": [],
            "tabs": [
                {
                    "id": "work",
                    "name": "Work",
                    "root_split": {
                        "orientation": "vertical",
                        "ratio": 1.0,
                        "children": [{"panel_id": "work-panel", "panel_type": "work"}],
                    },
                }
            ],
        }


@dataclass
class _RunbookObject:
    id: str = "docker-container-unhealthy"
    version: str = "1.0.0"
    title: str = "Recover unhealthy Docker container"
    description: str | None = "Restart, validate, and compensate if needed."

    @property
    def risk_class(self):
        class _RiskClass:
            value = "guarded"

        return _RiskClass()

    @property
    def tags(self) -> tuple[str, ...]:
        return ("docker", "recovery")

    @property
    def scope(self) -> dict[str, object]:
        return {"component_kinds": ["docker_runtime"], "risk_levels": ["stage", "prod"]}

    @property
    def steps(self) -> tuple[object, ...]:
        return (
            _ResponseStepRunObject(step_key="restart"),
            _ResponseStepRunObject(step_key="verify"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "version": self.version,
            "title": self.title,
            "description": self.description,
            "risk_class": self.risk_class.value,
            "scope": self.scope,
            "tags": list(self.tags),
            "steps": [
                {"key": "restart", "title": "Restart container"},
                {"key": "verify", "title": "Verify health"},
            ],
        }


@dataclass
class _ResponseRunObject:
    id: str = "rrn-1"
    incident_id: str = "inc-1"
    runbook_id: str = "docker-container-unhealthy"
    runbook_version: str = "1.0.0"
    status: ResponseRunStatus = ResponseRunStatus.READY
    current_step_index: int = 0
    risk_level: TargetRiskLevel = TargetRiskLevel.PROD
    summary: str | None = "Ready to execute."

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "incident_id": self.incident_id,
            "runbook_id": self.runbook_id,
            "runbook_version": self.runbook_version,
            "status": self.status.value,
            "current_step_index": self.current_step_index,
            "risk_level": self.risk_level.value,
            "summary": self.summary,
        }


@dataclass
class _ResponseStepRunObject:
    id: str = "rsp-1"
    step_key: str = "restart"
    status: ResponseStepStatus = ResponseStepStatus.READY
    attempt_count: int = 0
    output_summary: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "step_key": self.step_key,
            "status": self.status.value,
            "attempt_count": self.attempt_count,
            "output_summary": self.output_summary,
        }


@dataclass
class _ApprovalRequestObject:
    id: str = "apr-1"
    response_run_id: str = "rrn-1"
    step_run_id: str = "rsp-1"
    status: ApprovalRequestStatus = ApprovalRequestStatus.PENDING
    required_approver_count: int = 2
    required_roles: tuple[str, ...] = ("lead",)
    reason: str = "Production restart requires approval."

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "response_run_id": self.response_run_id,
            "step_run_id": self.step_run_id,
            "status": self.status.value,
            "required_approver_count": self.required_approver_count,
            "required_roles": list(self.required_roles),
            "reason": self.reason,
        }


@dataclass
class _ApprovalDecisionObject:
    id: str = "apd-1"
    approval_request_id: str = "apr-1"
    approver_ref: str = "opr-1"
    decision: str = "approve"

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "approval_request_id": self.approval_request_id,
            "approver_ref": self.approver_ref,
            "decision": self.decision,
        }


@dataclass
class _ResponseArtifactObject:
    id: str = "art-1"
    response_run_id: str = "rrn-1"
    label: str = "docker-inspect"

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "response_run_id": self.response_run_id,
            "label": self.label,
        }


@dataclass
class _CompensationRunObject:
    id: str = "cmp-1"
    response_run_id: str = "rrn-1"
    status: str = "completed"

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "response_run_id": self.response_run_id,
            "status": self.status,
        }


@dataclass
class _ReviewObject:
    id: str = "rvw-1"
    incident_id: str = "inc-1"
    response_run_id: str | None = "rrn-1"
    owner_ref: str | None = "opr-1"
    status: PostIncidentReviewStatus = PostIncidentReviewStatus.OPEN
    summary: str | None = None
    root_cause: str | None = None
    closure_quality: ClosureQuality = ClosureQuality.COMPLETE

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "incident_id": self.incident_id,
            "response_run_id": self.response_run_id,
            "owner_ref": self.owner_ref,
            "status": self.status.value,
            "summary": self.summary,
            "root_cause": self.root_cause,
            "closure_quality": self.closure_quality.value,
        }


@dataclass
class _ReviewFindingObject:
    id: str = "rfn-1"
    review_id: str = "rvw-1"
    title: str = "Improve response automation"
    detail: str = "Manual restart could be automated."

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "review_id": self.review_id,
            "title": self.title,
            "detail": self.detail,
        }


@dataclass
class _ActionItemObject:
    id: str = "act-1"
    review_id: str = "rvw-1"
    owner_ref: str | None = "opr-2"
    status: ActionItemStatus = ActionItemStatus.OPEN
    title: str = "Add health probes"
    detail: str = "Implement container health probe automation."

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "review_id": self.review_id,
            "owner_ref": self.owner_ref,
            "status": self.status.value,
            "title": self.title,
            "detail": self.detail,
        }


@dataclass
class _ResponseDetailObject:
    response_run: _ResponseRunObject = field(default_factory=_ResponseRunObject)
    incident: _IncidentDetailIncident = field(default_factory=_IncidentDetailIncident)
    runbook: _RunbookObject = field(default_factory=_RunbookObject)
    step_runs: tuple[_ResponseStepRunObject, ...] = field(
        default_factory=lambda: (
            _ResponseStepRunObject(
                id="rsp-1",
                step_key="restart",
                status=ResponseStepStatus.SUCCEEDED,
                attempt_count=1,
                output_summary="Container restarted.",
            ),
            _ResponseStepRunObject(
                id="rsp-2",
                step_key="verify",
                status=ResponseStepStatus.READY,
                attempt_count=0,
            ),
        )
    )
    approvals: tuple[dict[str, object], ...] = field(
        default_factory=lambda: (
            {
                "request": _ApprovalRequestObject().to_dict(),
                "decisions": [_ApprovalDecisionObject().to_dict()],
            },
        )
    )
    artifacts: tuple[_ResponseArtifactObject, ...] = field(
        default_factory=lambda: (_ResponseArtifactObject(),)
    )
    compensations: tuple[_CompensationRunObject, ...] = field(
        default_factory=lambda: (_CompensationRunObject(),)
    )
    timeline: tuple[dict[str, object], ...] = field(
        default_factory=lambda: (
            {"event_type": "run_started", "message": "Response run started."},
            {"event_type": "step_succeeded", "message": "Restart completed."},
        )
    )
    review: _ReviewObject | None = field(default_factory=_ReviewObject)


@dataclass
class _ReviewDetailObject:
    review: _ReviewObject = field(default_factory=_ReviewObject)
    findings: tuple[_ReviewFindingObject, ...] = field(
        default_factory=lambda: (_ReviewFindingObject(),)
    )
    action_items: tuple[_ActionItemObject, ...] = field(
        default_factory=lambda: (_ActionItemObject(),)
    )


class LocalWebAdminServerTests(unittest.TestCase):
    def test_serves_pages_and_handles_post_actions(self) -> None:
        service = FakeWebAdminService()
        server = LocalWebAdminServer(service, host="127.0.0.1", port=0)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base_url = None
            for _ in range(50):
                base_url = server.listen_url()
                if base_url:
                    break
                time.sleep(0.05)
            self.assertIsNotNone(base_url)
            assert base_url is not None

            with urlopen(f"{base_url}/diagnostics") as response:
                body = response.read().decode("utf-8")
            self.assertIn("Diagnostics", body)
            self.assertIn("trusted_sources", body)
            self.assertIn("Health Summary", body)

            with urlopen(f"{base_url}/incidents") as response:
                incidents_body = response.read().decode("utf-8")
            self.assertIn("Incident Center", incidents_body)
            self.assertIn("inc-1", incidents_body)

            with urlopen(f"{base_url}/api/layouts") as response:
                layout_catalog = response.read().decode("utf-8")
            self.assertIn('"layouts"', layout_catalog)
            self.assertIn('"panel_id": "work-panel"', layout_catalog)

            with urlopen(f"{base_url}/api/layouts/default") as response:
                layout_document = response.read().decode("utf-8")
            self.assertIn('"root_split"', layout_document)

            with urlopen(f"{base_url}/layouts/editor") as response:
                editor_html = response.read().decode("utf-8")
            self.assertIn("Cockpit Layout Editor", editor_html)

            with urlopen(f"{base_url}/plugins") as response:
                plugin_body = response.read().decode("utf-8")
            self.assertIn("git+https://github.com/", plugin_body)

            with urlopen(f"{base_url}/notifications") as response:
                notifications_body = response.read().decode("utf-8")
            self.assertIn("Recent notifications", notifications_body)
            self.assertIn("Tunnel unhealthy", notifications_body)

            with urlopen(f"{base_url}/watches") as response:
                watches_body = response.read().decode("utf-8")
            self.assertIn("Configured watches", watches_body)
            self.assertIn("Datasource Watch", watches_body)

            with urlopen(f"{base_url}/oncall") as response:
                oncall_body = response.read().decode("utf-8")
            self.assertIn("Create operator", oncall_body)
            self.assertIn("Platform Ops", oncall_body)

            with urlopen(f"{base_url}/engagements") as response:
                engagements_body = response.read().decode("utf-8")
            self.assertIn("Engagement Center", engagements_body)
            self.assertIn("eng-1", engagements_body)

            with urlopen(f"{base_url}/runbooks") as response:
                runbooks_body = response.read().decode("utf-8")
            self.assertIn("Runbook catalog", runbooks_body)
            self.assertIn("docker-container-unhealthy", runbooks_body)

            with urlopen(f"{base_url}/responses") as response:
                responses_body = response.read().decode("utf-8")
            self.assertIn("Response Center", responses_body)
            self.assertIn("rrn-1", responses_body)

            with urlopen(f"{base_url}/reviews") as response:
                reviews_body = response.read().decode("utf-8")
            self.assertIn("Review Center", reviews_body)
            self.assertIn("rvw-1", reviews_body)

            with urlopen(f"{base_url}/secrets") as response:
                secrets_body = response.read().decode("utf-8")
            self.assertIn("analytics-pass", secrets_body)

            request = Request(
                f"{base_url}/datasources/create",
                data=urlencode(
                    {
                        "name": "PG",
                        "backend": "postgres",
                        "connection_url": "postgresql://localhost/app",
                        "secret_refs_json": '{"DB_PASS":"env:APP_DB_PASS"}',
                        "options_json": '{"connect_args":{"sslmode":"require"}}',
                        "tags": "analytics, stage",
                    }
                ).encode("utf-8"),
                method="POST",
            )
            with urlopen(request) as response:
                redirected_body = response.read().decode("utf-8")

            self.assertIn("Created datasource PG.", redirected_body)
            self.assertEqual(service.created_datasources[0]["backend"], "postgres")
            self.assertEqual(
                service.created_datasources[0]["secret_refs_json"],
                '{"DB_PASS":"env:APP_DB_PASS"}',
            )

            validate_request = Request(
                f"{base_url}/api/layouts/validate",
                data=json.dumps(
                    {
                        "layout": {
                            "id": "default",
                            "name": "Default",
                            "focus_path": [],
                            "tabs": [
                                {
                                    "id": "work",
                                    "name": "Work",
                                    "root_split": {
                                        "orientation": "vertical",
                                        "ratio": 1.0,
                                        "children": [
                                            {
                                                "panel_id": "work-panel",
                                                "panel_type": "work",
                                            }
                                        ],
                                    },
                                }
                            ],
                        }
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(validate_request) as response:
                validate_body = response.read().decode("utf-8")
            self.assertIn('"ok": true', validate_body)

            execute_request = Request(
                f"{base_url}/datasources/execute",
                data=urlencode(
                    {
                        "profile_id": "pg-main",
                        "statement": "SELECT 1",
                        "operation": "query",
                        "confirmed": "1",
                    }
                ).encode("utf-8"),
                method="POST",
            )
            with urlopen(execute_request) as response:
                execute_body = response.read().decode("utf-8")
            self.assertIn("Datasource command executed.", execute_body)

            secret_request = Request(
                f"{base_url}/secrets/create",
                data=urlencode(
                    {
                        "name": "redis-pass",
                        "provider": "env",
                        "env_name": "REDIS_PASSWORD",
                    }
                ).encode("utf-8"),
                method="POST",
            )
            with urlopen(secret_request) as response:
                secret_body = response.read().decode("utf-8")
            self.assertIn("Saved secret reference redis-pass.", secret_body)
            self.assertEqual(service.created_secrets[0]["env_name"], "REDIS_PASSWORD")

            channel_request = Request(
                f"{base_url}/notifications/channel/save",
                data=urlencode(
                    {
                        "name": "Slack Ops",
                        "kind": "slack",
                        "target_json": '{"url":"https://hooks.slack.test"}',
                    }
                ).encode("utf-8"),
                method="POST",
            )
            with urlopen(channel_request) as response:
                channel_body = response.read().decode("utf-8")
            self.assertIn("Saved notification channel Slack Ops.", channel_body)
            self.assertEqual(service.saved_channels[0]["kind"], "slack")

            watch_request = Request(
                f"{base_url}/watches/datasource/save",
                data=urlencode(
                    {
                        "name": "Primary DB Reachability",
                        "profile_id": "pg-main",
                    }
                ).encode("utf-8"),
                method="POST",
            )
            with urlopen(watch_request) as response:
                watch_body = response.read().decode("utf-8")
            self.assertIn("Saved datasource watch Primary DB Reachability.", watch_body)
            self.assertEqual(
                service.saved_datasource_watches[0]["profile_id"], "pg-main"
            )

            rotate_request = Request(
                f"{base_url}/secrets/rotate",
                data=urlencode(
                    {
                        "name": "analytics-pass",
                        "secret_value": "rotated",
                    }
                ).encode("utf-8"),
                method="POST",
            )
            with urlopen(rotate_request) as response:
                rotate_body = response.read().decode("utf-8")
            self.assertIn("Rotated secret reference analytics-pass.", rotate_body)
            self.assertEqual(service.rotated_secrets, ["analytics-pass"])

            close_tunnel_request = Request(
                f"{base_url}/diagnostics/close-tunnel",
                data=urlencode({"profile_id": "pg-main"}).encode("utf-8"),
                method="POST",
            )
            with urlopen(close_tunnel_request) as response:
                diagnostics_body = response.read().decode("utf-8")
            self.assertIn("Closed tunnel for pg-main.", diagnostics_body)
            self.assertEqual(service.closed_tunnels, ["pg-main"])

            reconnect_tunnel_request = Request(
                f"{base_url}/diagnostics/reconnect-tunnel",
                data=urlencode({"profile_id": "pg-main"}).encode("utf-8"),
                method="POST",
            )
            with urlopen(reconnect_tunnel_request) as response:
                reconnect_body = response.read().decode("utf-8")
            self.assertIn("Reconnected tunnel for pg-main.", reconnect_body)
            self.assertEqual(service.reconnected_tunnels, ["pg-main"])

            acknowledge_request = Request(
                f"{base_url}/incidents/acknowledge",
                data=urlencode({"incident_id": "inc-1"}).encode("utf-8"),
                method="POST",
            )
            with urlopen(acknowledge_request) as response:
                acknowledge_body = response.read().decode("utf-8")
            self.assertIn("Acknowledged incident inc-1.", acknowledge_body)
            self.assertEqual(service.acknowledged_incidents, ["inc-1"])

            person_request = Request(
                f"{base_url}/oncall/people/save",
                data=urlencode(
                    {
                        "display_name": "Alice Example",
                        "handle": "alice",
                        "timezone": "Europe/Berlin",
                        "contact_targets_json": '[{"channel_id":"slack-alice","label":"Slack","enabled":true,"priority":100}]',
                    }
                ).encode("utf-8"),
                method="POST",
            )
            with urlopen(person_request) as response:
                person_body = response.read().decode("utf-8")
            self.assertIn("Saved operator Alice Example.", person_body)
            self.assertEqual(service.saved_people[0]["handle"], "alice")

            policy_request = Request(
                f"{base_url}/oncall/policies/save",
                data=urlencode(
                    {
                        "name": "Primary Escalation",
                        "default_ack_timeout_seconds": "900",
                        "default_repeat_page_seconds": "300",
                        "max_repeat_pages": "2",
                        "steps_json": '[{"step_index":0,"target_kind":"team","target_ref":"team-1"}]',
                    }
                ).encode("utf-8"),
                method="POST",
            )
            with urlopen(policy_request) as response:
                policy_body = response.read().decode("utf-8")
            self.assertIn("Saved escalation policy Primary Escalation.", policy_body)
            self.assertEqual(service.saved_policies[0]["name"], "Primary Escalation")

            engagement_ack_request = Request(
                f"{base_url}/engagements/ack",
                data=urlencode({"engagement_id": "eng-1"}).encode("utf-8"),
                method="POST",
            )
            with urlopen(engagement_ack_request) as response:
                engagement_ack_body = response.read().decode("utf-8")
            self.assertIn("Acknowledged engagement eng-1.", engagement_ack_body)
            self.assertEqual(service.acknowledged_engagements, ["eng-1"])

            handoff_request = Request(
                f"{base_url}/engagements/handoff",
                data=urlencode(
                    {
                        "engagement_id": "eng-1",
                        "target_kind": "person",
                        "target_ref": "opr-2",
                    }
                ).encode("utf-8"),
                method="POST",
            )
            with urlopen(handoff_request) as response:
                handoff_body = response.read().decode("utf-8")
            self.assertIn("Handed off engagement eng-1.", handoff_body)
            self.assertEqual(service.handed_off_engagements[0]["target_ref"], "opr-2")

            response_start_request = Request(
                f"{base_url}/responses/start",
                data=urlencode(
                    {
                        "incident_id": "inc-1",
                        "runbook_id": "docker-container-unhealthy",
                        "runbook_version": "1.0.0",
                        "engagement_id": "eng-1",
                    }
                ).encode("utf-8"),
                method="POST",
            )
            with urlopen(response_start_request) as response:
                response_start_body = response.read().decode("utf-8")
            self.assertIn("Started response run rrn-started.", response_start_body)
            self.assertEqual(
                service.started_responses[0]["runbook_id"], "docker-container-unhealthy"
            )

            response_execute_request = Request(
                f"{base_url}/responses/execute",
                data=urlencode(
                    {
                        "response_run_id": "rrn-1",
                        "confirmed": "1",
                        "elevated_mode": "1",
                        "notes": "operator confirmed",
                    }
                ).encode("utf-8"),
                method="POST",
            )
            with urlopen(response_execute_request) as response:
                response_execute_body = response.read().decode("utf-8")
            self.assertIn("Executed current response step.", response_execute_body)
            self.assertTrue(bool(service.executed_responses[0]["confirmed"]))

            approval_request = Request(
                f"{base_url}/approvals/decide",
                data=urlencode(
                    {
                        "approval_request_id": "apr-1",
                        "decision": "approve",
                        "comment": "looks good",
                    }
                ).encode("utf-8"),
                method="POST",
            )
            with urlopen(approval_request) as response:
                approval_body = response.read().decode("utf-8")
            self.assertIn("Approved approval request apr-1.", approval_body)
            self.assertEqual(service.approval_decisions[0]["decision"], "approve")

            ensure_review_request = Request(
                f"{base_url}/reviews/ensure",
                data=urlencode(
                    {
                        "incident_id": "inc-1",
                        "response_run_id": "rrn-1",
                        "owner_ref": "opr-1",
                    }
                ).encode("utf-8"),
                method="POST",
            )
            with urlopen(ensure_review_request) as response:
                ensure_review_body = response.read().decode("utf-8")
            self.assertIn("Opened review rvw-opened.", ensure_review_body)
            self.assertEqual(service.ensured_reviews[0]["owner_ref"], "opr-1")

            add_finding_request = Request(
                f"{base_url}/reviews/finding/add",
                data=urlencode(
                    {
                        "review_id": "rvw-1",
                        "category": "automation",
                        "severity": "high",
                        "title": "Automate restart verification",
                        "detail": "Verification remained manual.",
                    }
                ).encode("utf-8"),
                method="POST",
            )
            with urlopen(add_finding_request) as response:
                finding_body = response.read().decode("utf-8")
            self.assertIn("Added finding rfn-added.", finding_body)
            self.assertEqual(service.added_findings[0]["category"], "automation")

            add_action_item_request = Request(
                f"{base_url}/reviews/action-item/add",
                data=urlencode(
                    {
                        "review_id": "rvw-1",
                        "owner_ref": "opr-2",
                        "title": "Ship probe fix",
                        "detail": "Add restart probe automation.",
                        "due_at": "2026-03-25T12:00:00+00:00",
                    }
                ).encode("utf-8"),
                method="POST",
            )
            with urlopen(add_action_item_request) as response:
                action_item_body = response.read().decode("utf-8")
            self.assertIn("Added action item act-added.", action_item_body)
            self.assertEqual(service.added_action_items[0]["owner_ref"], "opr-2")

            update_action_item_request = Request(
                f"{base_url}/reviews/action-item/status",
                data=urlencode(
                    {
                        "action_item_id": "act-1",
                        "status": "closed",
                    }
                ).encode("utf-8"),
                method="POST",
            )
            with urlopen(update_action_item_request) as response:
                update_action_body = response.read().decode("utf-8")
            self.assertIn("Updated action item act-1.", update_action_body)
            self.assertEqual(service.updated_action_items[0]["status"], "closed")

            complete_review_request = Request(
                f"{base_url}/reviews/complete",
                data=urlencode(
                    {
                        "review_id": "rvw-1",
                        "summary": "Restored service and validated health.",
                        "root_cause": "Missing restart automation.",
                        "closure_quality": "complete",
                    }
                ).encode("utf-8"),
                method="POST",
            )
            with urlopen(complete_review_request) as response:
                complete_review_body = response.read().decode("utf-8")
            self.assertIn("Completed review rvw-1.", complete_review_body)
            self.assertEqual(
                service.completed_reviews[0]["closure_quality"], "complete"
            )

            self.assertIn("/diagnostics", service.saved_pages)
            self.assertIn("/plugins", service.saved_pages)
            self.assertIn("/notifications", service.saved_pages)
            self.assertIn("/watches", service.saved_pages)
            self.assertIn("/oncall", service.saved_pages)
            self.assertIn("/engagements", service.saved_pages)
            self.assertIn("/runbooks", service.saved_pages)
            self.assertIn("/responses", service.saved_pages)
            self.assertIn("/reviews", service.saved_pages)
            self.assertIn("/secrets", service.saved_pages)
            self.assertIn("/datasources", service.saved_pages)
            self.assertIn("/incidents", service.saved_pages)
        finally:
            server.shutdown()
            thread.join(timeout=2)
