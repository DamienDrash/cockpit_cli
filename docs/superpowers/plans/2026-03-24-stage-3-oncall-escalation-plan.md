# Stage 3 On-Call And Escalation Implementation Plan

Date: 2026-03-24
Status: Ready for implementation
Input spec: [2026-03-24-stage-3-oncall-escalation-design.md](../specs/2026-03-24-stage-3-oncall-escalation-design.md)
Project: `cockpit_cli`

## Objective

Implement Stage 3 as the next operator-grade layer on top of the Stage 1 and
Stage 2 operator spine.

The result must add:

- first-class people and teams
- deterministic on-call resolution from schedules, rotations, and overrides
- explicit escalation policies and active incident engagements
- reminder, acknowledgement, handoff, and bounded repeat paging behavior
- web-admin configuration surfaces
- TUI live engagement surfaces

## Delivery Definition

Stage 3 is complete when an operator can:

1. define people, teams, memberships, schedules, rotations, and overrides
2. bind owned runtime scopes to teams and escalation policies
3. configure escalation policies and ordered escalation steps
4. open an incident that deterministically creates an active engagement
5. see current owner, next deadline, and current step for an active engagement
6. acknowledge, hand off, or force re-page an engagement
7. inspect full engagement timeline and linked delivery attempts
8. trust that paging is bounded, auditable, and never silently dropped

## Implementation Strategy

Build in the following order:

1. domain contracts and enums
2. SQLite schema and repositories
3. on-call resolution and escalation policy services
4. engagement runtime and monitor integration
5. notification linkage and incident integration
6. web-admin configuration and active-engagement views
7. TUI active-engagement surface
8. deterministic tests and critical review

This order keeps runtime logic dependent on explicit persisted models rather
than UI-first shortcuts.

## Phase 1: Domain Contracts

### Goal

Define explicit Stage 3 operator, ownership, schedule, escalation, and
engagement contracts before persistence and UI work.

### Deliverables

- new enums for engagement and target kinds
- people, teams, memberships, ownership bindings
- schedules, rotations, overrides
- escalation policies and steps
- active engagement models and timeline entries
- Stage 3 domain events

### Target files

```text
src/cockpit/shared/enums.py
src/cockpit/domain/models/oncall.py
src/cockpit/domain/models/escalation.py
src/cockpit/domain/events/escalation_events.py
```

### Exit criteria

- all Stage 3 persisted records are representable as typed dataclasses
- engagement lifecycle and target semantics are explicit

## Phase 2: Persistence

### Goal

Extend SQLite with configuration and runtime state for Stage 3.

### Deliverables

- schema migration for operator, schedule, policy, and engagement tables
- focused repositories for Stage 3 entities
- active and due-engagement query helpers

### Target files

```text
src/cockpit/infrastructure/persistence/schema.py
src/cockpit/infrastructure/persistence/migrations.py
src/cockpit/infrastructure/persistence/ops_repositories.py
tests/integration/test_ops_repositories.py
```

### Exit criteria

- Stage 3 records round-trip through SQLite
- repository APIs cover admin, runtime, and TUI read paths without ad hoc SQL

## Phase 3: Resolution And Policy Services

### Goal

Create the deterministic ownership, schedule, and escalation policy services.

### Deliverables

- `OnCallResolutionService`
- `EscalationPolicyService`
- validation logic for schedules, overrides, and escalation steps

### Target files

```text
src/cockpit/application/services/oncall_resolution_service.py
src/cockpit/application/services/escalation_policy_service.py
tests/unit/test_oncall_resolution_service.py
tests/unit/test_escalation_policy_service.py
```

### Exit criteria

- schedule resolution is deterministic and explainable
- override conflicts fail explicitly
- escalation deadlines and repeat-page behavior are computed centrally

## Phase 4: Engagement Runtime

### Goal

Implement the active incident engagement runtime and due-action monitor.

### Deliverables

- `EscalationService`
- `EscalationMonitor`
- incident-to-engagement creation
- ack, handoff, re-page, and close flows
- due reminder, re-page, and step progression sweeps

### Target files

```text
src/cockpit/application/services/escalation_service.py
src/cockpit/runtime/escalation_monitor.py
src/cockpit/application/services/incident_service.py
src/cockpit/application/services/notification_service.py
src/cockpit/bootstrap.py
```

### Exit criteria

- incidents create at most one active primary engagement
- acknowledgement stops progression without closing incidents
- repeat paging and escalation are bounded and persisted

## Phase 5: Notification And Diagnostics Integration

### Goal

Link engagement actions to the existing Stage 2 notification plane and extend
operator diagnostics.

### Deliverables

- notification payload enrichment with engagement context
- correlation between engagements and delivery attempts
- diagnostics expansion for ownership and escalation state

### Target files

```text
src/cockpit/application/services/notification_service.py
src/cockpit/application/services/operations_diagnostics_service.py
src/cockpit/application/services/web_admin_service.py
```

### Exit criteria

- a page is visible both as an engagement action and as a notification/delivery
- delivery failure does not silently kill engagement runtime

## Phase 6: Web Admin

### Goal

Expose full Stage 3 configuration and active-engagement operations through the
existing local web admin.

### Deliverables

- sections for people, teams, memberships, schedules, rotations, overrides,
  ownership bindings, and escalation policies
- active engagement list and detail pages
- ack, handoff, and re-page actions

### Target files

```text
src/cockpit/application/services/web_admin_service.py
src/cockpit/infrastructure/web/admin_server.py
tests/integration/test_web_admin_server.py
```

### Exit criteria

- operators can configure and inspect Stage 3 state without editing SQLite
- validation errors are deterministic and readable

## Phase 7: TUI Active Engagement Surface

### Goal

Extend the operator TUI with live engagement visibility and actions.

### Deliverables

- ops panel enhancements for active engagements
- keyboard-first ack / handoff / re-page flows
- summary of current owner, deadline, and blocked/exhausted state

### Target files

```text
src/cockpit/ui/panels/ops_panel.py
src/cockpit/bootstrap.py
src/cockpit/ui/screens/app_shell.py
tests/unit/test_ops_panel.py
```

### Exit criteria

- the TUI remains an operate plane rather than a config plane
- active engagement actions work without leaving the keyboard

## Phase 8: Verification

### Goal

Prove Stage 3 behavior with deterministic tests and a principal-engineer style
review.

### Test additions

- ownership binding precedence
- schedule resolution across rotations and overrides
- escalation-step deadlines and repeat-page caps
- engagement creation from incidents
- ack, resolve, handoff, and exhaustion flows
- repository round-trips for all new entities
- admin create/edit/list/detail/action flows
- TUI active engagement summary and action flows

### Final review checklist

- no second incident model exists
- ownership and delivery stay separated
- no implicit schedule guessing occurs
- no infinite repeat-page loops exist
- blocked/unassigned states are explicit and visible
- all operator actions are persisted and auditable
