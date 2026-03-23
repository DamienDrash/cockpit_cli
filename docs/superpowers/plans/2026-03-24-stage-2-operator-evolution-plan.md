# Stage 2 Operator Evolution Implementation Plan

Date: 2026-03-24
Status: Ready for implementation
Input spec: [2026-03-24-stage-2-operator-evolution-design.md](../specs/2026-03-24-stage-2-operator-evolution-design.md)
Project: `cockpit_cli`

## Objective

Implement Stage 2 as the next operator-grade layer on top of the Stage 1
incident and self-healing spine.

The result must add:

- a persisted notification plane
- suppression and routing policy
- expanded health coverage for plugin hosts, the web admin server, datasource
  reachability monitors, and Docker container health
- stronger operator-native web admin and TUI surfaces

## Delivery Definition

Stage 2 is complete when an operator can:

1. configure notification channels and routing rules
2. define time-bounded suppression rules
3. see notifications, suppressed notifications, and delivery failures in the
   web admin
4. monitor plugin hosts, the web admin, explicit datasource reachability
   watches, and explicit Docker health watches through the same health spine
5. receive deterministic internal and outbound notifications for Stage 2 health
   events
6. inspect a compact operator summary in the TUI without leaving the keyboard

## Implementation Strategy

Build in the following order:

1. domain contracts and enums
2. persistence schema and repositories
3. notification, suppression, and watch services
4. delivery adapters
5. runtime integration
6. web admin views and actions
7. TUI operator summary surface
8. deterministic tests and critical review

This order is strict enough to keep UI and delivery logic from outrunning the
domain and persistence model.

## Phase 1: Domain Contracts

### Goal

Define explicit Stage 2 models and events before any persistence or UI work.

### Deliverables

- notification models
- watch configuration models
- notification delivery result contracts
- Stage 2 domain events
- enum extensions for channels, notification status, suppression, and watch
  outcomes

### Target files

```text
src/cockpit/shared/enums.py
src/cockpit/domain/models/notifications.py
src/cockpit/domain/models/watch.py
src/cockpit/domain/events/notification_events.py
src/cockpit/domain/events/health_events.py
```

### Exit criteria

- all Stage 2 persisted records are representable as typed dataclasses
- events distinguish notification lifecycle from health lifecycle

## Phase 2: Persistence

### Goal

Extend SQLite for notifications, suppressions, channels, delivery attempts, and
watch state.

### Deliverables

- schema migration
- repositories for Stage 2 entities
- efficient query helpers for recent notifications, failed deliveries, active
  suppressions, and enabled watch configs

### Target files

```text
src/cockpit/infrastructure/persistence/schema.py
src/cockpit/infrastructure/persistence/migrations.py
src/cockpit/infrastructure/persistence/ops_repositories.py
tests/integration/test_ops_repositories.py
```

### Exit criteria

- Stage 2 records round-trip through SQLite
- repository APIs support admin and runtime read paths without ad hoc SQL in
  services

## Phase 3: Notification And Suppression Services

### Goal

Create the central notification plane and suppression/routing policy layer.

### Deliverables

- `NotificationPolicyService`
- `SuppressionService`
- `NotificationService`
- sink adapter interface and delivery retry logic

### Target files

```text
src/cockpit/application/services/notification_policy_service.py
src/cockpit/application/services/suppression_service.py
src/cockpit/application/services/notification_service.py
src/cockpit/infrastructure/notifications/base.py
src/cockpit/infrastructure/notifications/webhook_adapter.py
src/cockpit/infrastructure/notifications/slack_adapter.py
src/cockpit/infrastructure/notifications/ntfy_adapter.py
```

### Exit criteria

- health/incident events can become persisted notifications
- suppression decisions are explicit and persisted
- delivery attempts are bounded and observable

## Phase 4: Expanded Health Coverage

### Goal

Integrate Stage 2 watched components into the existing health spine.

### Deliverables

- component watch service
- plugin host health observation
- web admin server heartbeat/liveness observation
- datasource reachability watches
- Docker health watches
- integration with `RuntimeHealthMonitor` and `SelfHealingService`

### Target files

```text
src/cockpit/application/services/component_watch_service.py
src/cockpit/application/services/self_healing_service.py
src/cockpit/runtime/health_monitor.py
src/cockpit/application/services/plugin_service.py
src/cockpit/infrastructure/web/admin_server.py
src/cockpit/infrastructure/docker/docker_adapter.py
src/cockpit/application/services/operations_diagnostics_service.py
```

### Exit criteria

- watched Stage 2 components use the same incident/recovery/quarantine model
- no duplicate health-tracking subsystem is introduced

## Phase 5: Web Admin

### Goal

Expose Stage 2 configuration and operator visibility through the existing local
web admin.

### Deliverables

- notification pages
- suppression rule management
- channel management
- watch configuration pages
- diagnostics expansion for Stage 2 health and delivery state

### Target files

```text
src/cockpit/application/services/web_admin_service.py
src/cockpit/infrastructure/web/admin_server.py
tests/integration/test_web_admin_server.py
```

### Exit criteria

- operators can inspect and change Stage 2 state without editing raw SQLite
- stage 2 web actions are deterministic and test-covered

## Phase 6: TUI Operator Surface

### Goal

Add a concise operator-native summary panel inside the TUI.

### Deliverables

- new `OpsPanel` or equivalent operator summary surface
- panel registration and layout integration
- command context and refresh behavior consistent with the existing panel model

### Target files

```text
src/cockpit/ui/panels/ops_panel.py
src/cockpit/bootstrap.py
src/cockpit/ui/screens/app_shell.py
tests/e2e/...
tests/unit/...
```

### Exit criteria

- TUI shows active incidents, quarantines, failed deliveries, and unhealthy
  watched components without becoming a second admin plane

## Phase 7: Verification

### Goal

Prove Stage 2 behavior through deterministic automated tests and a principal
engineer style review.

### Test additions

- notification policy decisions
- suppression windows and expiry
- delivery attempt backoff and exhaustion
- datasource watch classification
- Docker health watch classification
- plugin host and web admin health transitions
- Stage 2 repository round-trips
- Stage 2 web admin list/detail/action flows
- compact TUI operator summary rendering

### Final review checklist

- no infinite retry loops in notifications or component recovery
- suppression behavior is visible and reversible
- delivery failures do not mutate incidents incorrectly
- watch config is explicit and opt-in
- no Stage 2 logic is hidden in UI code
- persistence is complete enough for diagnostics and operator action history
