# Stage 2 Operator Evolution Design

Date: 2026-03-24
Status: Draft approved in interactive design review

## Scope

This spec defines Stage 2 of the next major operator-focused evolution of
`cockpit_cli`.

Stage 1 established:

- a persistent health model
- structured incidents
- bounded recovery with cooldown and quarantine
- centralized guard policy
- deeper diagnostics for Docker, DB, and Curl

Stage 2 extends that spine into a more complete operator control plane with
four tightly related goals:

- introduce a real notification plane
- add suppression and routing policy
- expand health coverage to more platform components
- add stronger operator-native views in the TUI and web admin

This is not a detached feature bundle. The result must remain one coherent
operational architecture with one health model, one incident model, one
notification model, and one persistent history.

## Product Decision

Stage 2 must be operator-grade without turning Cockpit into a full external
incident-management platform.

The approved decisions are:

- notifications must work both internally and externally
- the internal surfaces remain first-class
- outbound delivery is plugin-friendly but Stage 2 includes first-class support
  for:
  - webhook
  - Slack
  - ntfy
- suppression rules are time-bound and policy-driven
- suppression keys may match by:
  - component kind
  - severity
  - risk level
  - event class
- health coverage expands in Stage 2 to:
  - plugin hosts
  - the web admin server
  - datasource reachability monitors
  - Docker container health
- Stage 2 does not attempt on-call scheduling, roster management, or full
  escalation trees

## Goals

- Make notifications a first-class persisted operator concern
- Separate notification/suppression policy from guard policy
- Expand health/recovery coverage without creating a second supervision system
- Surface active health, notifications, suppression, and delivery failures in a
  way operators can act on quickly
- Keep the architecture deterministic, inspectable, and testable

## Non-Goals

- Pager or on-call rotation management
- Schedule-aware escalation rules
- Full alert-rule authoring for arbitrary metric expressions
- Probing every datasource or HTTP target by default
- A second admin system outside the existing web admin and TUI
- A SaaS-dependent notification architecture

## Target Outcome

After Stage 2:

- incidents can produce structured notifications
- notifications can be routed internally and externally
- suppression rules can intentionally reduce noise while remaining visible in
  persistence and diagnostics
- plugin hosts, the web admin, monitored datasources, and Docker health appear
  in the same health/recovery/incident model as Stage 1 components
- operators can inspect current health, delivery state, suppression state, and
  recent failures in both the web admin and the TUI

## Architectural Principles

### One Incident Model

Incidents remain the canonical record of operator-visible component failure and
degradation. Notifications are derived from incident and health events, not the
other way around.

### One Health Spine

Stage 2 extends the Stage 1 health spine. It must not introduce parallel status
tracking for plugin hosts, datasource probes, or Docker health.

### One Policy Layer Per Concern

Two policy families remain distinct:

- guard policy decides whether an operator action may execute
- notification policy decides whether an event should be emitted, suppressed,
  and delivered

Mixing these concerns would make audit and behavior hard to reason about.

### Internal First, External Capable

Notifications must always exist in Cockpit's own persistence and views before
they are delivered to external sinks. External delivery is an extension of the
internal notification model, not a substitute for it.

## Stage 2 Architecture

The implementation is split into six layers.

### 1. Notification Plane

This layer turns structured events into persisted notifications and delivery
attempts.

Responsibilities:

- normalize health and incident events into notification records
- assign severity, event class, dedupe keys, and routing context
- persist notifications before delivery
- call suppression policy
- route to configured sinks
- record per-channel delivery attempts and outcomes

Primary service:

- `NotificationService`

### 2. Suppression And Routing Policy

This layer evaluates whether a notification should be routed, delayed, or
suppressed.

Responsibilities:

- evaluate active notification rules
- evaluate active suppression windows
- provide explicit decision reasons
- support time-bounded mute behavior
- separate operator intent from sink delivery mechanics

Primary services:

- `NotificationPolicyService`
- `SuppressionService`

### 3. Expanded Health Coverage

This layer integrates new monitored component kinds into the existing
supervision model.

New Stage 2 monitored components:

- plugin host runtime
- web admin server runtime
- datasource reachability monitor
- Docker container health snapshot

These components use the existing incident, recovery, quarantine, and history
contracts from Stage 1.

Primary services:

- `ComponentWatchService`
- extensions to `SelfHealingService`
- extensions to `RuntimeHealthMonitor`

### 4. Delivery Adapters

Outbound sinks must be explicit adapters behind one contract.

Stage 2 built-ins:

- `WebhookNotificationAdapter`
- `SlackNotificationAdapter`
- `NtfyNotificationAdapter`

Each adapter must:

- accept a normalized delivery payload
- return structured success or failure metadata
- avoid hidden retries inside the adapter
- surface deterministic error information

### 5. Operator Views

The web admin remains the primary control plane for notification and suppression
configuration. The TUI gains concise operator-native views.

Web admin additions:

- Notifications
- Delivery attempts
- Notification channels
- Notification rules
- Suppression rules
- Expanded health overview

TUI additions:

- compact operator summary view for active incidents, unhealthy components,
  delivery failures, and suppressed notifications

### 6. Persistence Layer

SQLite remains the system of record for notification and suppression state.

No JSON side files may be used for Stage 2 operational data.

## Core Models

### NotificationChannel

Represents a configured outbound or internal destination.

Fields:

- id
- display name
- channel kind
- enabled
- target payload
- auth/secret reference metadata
- delivery timeout config
- retry policy fields
- risk classification
- created at
- updated at

### NotificationRule

Defines routing intent.

Fields:

- id
- enabled
- event classes
- component kinds
- severities
- risk levels
- incident statuses
- channel targets
- delivery priority
- dedupe window
- created at
- updated at

### NotificationSuppressionRule

Defines time-bounded muting behavior.

Fields:

- id
- enabled
- reason
- starts at
- ends at
- event classes
- component kinds
- severities
- risk levels
- actor metadata
- created at
- updated at

### NotificationRecord

Represents a persisted operator notification.

Fields:

- id
- source event id
- incident id optional
- component id optional
- event class
- severity
- risk level
- title
- summary
- detail payload
- dedupe key
- status
- suppression decision
- created at

### NotificationDeliveryAttempt

Represents one concrete delivery attempt for one notification and one channel.

Fields:

- id
- notification id
- channel id
- attempt number
- status
- started at
- finished at
- error class
- error message
- provider response metadata

### ComponentWatchConfig

Defines active monitoring intent for Stage 2 components.

Fields:

- id
- component kind
- component ref
- enabled
- probe interval seconds
- stale timeout seconds
- recovery policy override optional
- monitor config payload
- created at
- updated at

### ComponentWatchState

Stores the latest probe or watch outcome.

Fields:

- component id
- last probe at
- last success at
- last failure at
- last outcome
- last status
- probe payload

## Notification Events

Stage 2 introduces notification-focused domain events but does not replace the
existing health events.

Examples:

- `NotificationQueued`
- `NotificationSuppressed`
- `NotificationDeliveryStarted`
- `NotificationDelivered`
- `NotificationDeliveryFailed`
- `SuppressionRuleChanged`

These events are for observability and UI updates. The persisted notification
tables remain the source of truth.

## Routing And Suppression Flow

### Notification Creation

1. A health or incident event is published
2. `NotificationService` maps it to a notification candidate
3. The candidate receives:
   - event class
   - severity
   - risk level
   - dedupe key
   - structured payload
4. The notification is persisted
5. `NotificationPolicyService` resolves matching channels
6. `SuppressionService` evaluates suppression rules
7. If suppressed:
   - notification status is set accordingly
   - suppression reason is persisted
   - no outbound delivery occurs
8. If not suppressed:
   - delivery attempts are created and executed

### Delivery Behavior

Delivery must be deterministic:

- no infinite retry loops
- bounded retry count
- explicit retry backoff per channel
- final failure state persisted and visible

Delivery retry is independent from component recovery retry. A failing Slack
channel must not reopen or mutate the originating incident.

## Expanded Health Coverage Design

### Plugin Host Health

Plugin hosts already have runtime isolation from the core process. Stage 2
promotes their runtime state into the health spine.

Failure classes:

- host process crash
- startup failure
- repeated permission denial
- repeated integrity failure

Expected behavior:

- classify recoverable vs non-recoverable failures
- recover through bounded host restart where allowed
- quarantine after repeated exhaustion

### Web Admin Health

The local web admin server becomes a supervised component.

Signals:

- startup success/failure
- request-serving heartbeat
- shutdown unexpectedly

Recovery:

- bounded restart attempt where safe
- quarantine after exhaustion

### Datasource Reachability Monitoring

Stage 2 does not probe every datasource indiscriminately.

Instead, operators may enable reachability monitoring per datasource profile or
per watch config.

Signals:

- successful lightweight connect or ping
- tunnel unavailable
- auth resolution failure
- timeout

Reachability failures feed the same incident and notification pipeline but do
not by themselves mutate datasource configuration.

### Docker Container Health

Docker diagnostics already exist. Stage 2 elevates relevant container health
signals into the health spine.

Signals:

- unhealthy container state
- repeated restarts if visible
- last exit code drift
- missing expected container

Not every Docker container becomes monitored by default. Monitoring must be
explicit by watch config or selected panel context.

## Operator Surfaces

### Web Admin

The web admin gains dedicated sections for:

- notification overview
- notification detail
- delivery failures
- channel configuration
- routing rules
- suppression rules
- expanded health watch configuration

The diagnostics overview should summarize:

- active incidents
- quarantined components
- queued or failed notifications
- suppressed notification counts
- recent delivery failures
- monitored datasource state
- monitored Docker health state

### TUI

The TUI gains a concise operator-oriented view. It is intentionally not a full
configuration surface.

The TUI should show:

- active incidents
- quarantined components
- newest delivery failures
- suppressed notification count
- unhealthy monitored components

The TUI must remain keyboard-first and low-noise.

## Persistence Design

SQLite schema additions should include:

- `notification_channels`
- `notification_rules`
- `notification_suppressions`
- `notifications`
- `notification_deliveries`
- `component_watch_config`
- `component_watch_state`

These integrate with the existing Stage 1 incident and recovery tables.

Indexes should exist for:

- active suppression lookup by time window and event dimensions
- recent notification lookup by created time
- notification detail by incident id and component id
- delivery retry lookup by status and next-attempt time
- watch-state lookup by component id

## File-Level Impact

Expected additions include:

- new domain models for notifications and watch configs
- new notification events
- new application services for notification routing and suppression
- new persistence repositories and schema migration
- new delivery adapters for webhook, Slack, and ntfy
- extensions to runtime health monitoring
- web admin endpoints and views
- compact TUI operator view extensions

The implementation must extend the existing architecture rather than creating a
parallel operator subsystem.

## Error Handling

Stage 2 must keep error classes explicit.

Examples:

- notification suppressed by rule
- delivery failed due to transport error
- delivery failed due to auth or secret resolution error
- datasource probe failed due to timeout
- datasource probe failed due to tunnel outage
- Docker health fetch failed because daemon is unavailable

These outcomes should be visible in persistence and diagnostics, not hidden
inside logs alone.

## Testing Strategy

### Unit Tests

- notification candidate generation from incident and health events
- routing-rule evaluation
- suppression-rule evaluation
- bounded delivery retry and backoff
- Slack/webhook/ntfy adapter result handling
- datasource reachability classification
- Docker health classification
- plugin-host and web-admin health state transitions

### Integration Tests

- SQLite repository round-trips for channels, rules, suppressions,
  notifications, deliveries, and watch state
- web admin list/detail/action flows
- runtime monitor integration with fake watch components
- self-healing plus notification interaction

### TUI Tests

- operator summary rendering
- navigation to incident and delivery summary surfaces where applicable

### Web Admin E2E Tests

- create and edit channel config
- create and expire suppression rule
- inspect failed deliveries
- inspect monitored component health

No test should depend on a real Slack workspace, real ntfy service, or real
production infrastructure. Use fakes and deterministic transport stubs.

## Rollout Strategy

Stage 2 should ship incrementally behind the existing architecture:

1. schema and repositories
2. notification and suppression services
3. delivery adapters
4. expanded health monitors
5. web admin views
6. TUI operator summary enhancements

At each step, behavior must remain deterministic and backward-compatible with
Stage 1 operational flows.

## Open Boundaries For Later Stages

Stage 2 intentionally leaves room for later growth:

- escalation chains
- on-call schedules
- more outbound integrations
- richer probe types
- metric-driven alerting
- plugin-defined notification sinks

Those belong to later stages and should build on the Stage 2 notification and
watching foundations rather than replacing them.
