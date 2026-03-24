# Stage 4 Incident Response Lifecycle Implementation Plan

Date: 2026-03-24
Status: Ready for implementation
Input spec: [2026-03-24-stage-4-incident-response-lifecycle-design.md](../specs/2026-03-24-stage-4-incident-response-lifecycle-design.md)
Project: `cockpit_cli`

## Objective

Implement Stage 4 as the next operator-grade layer on top of the Stage 1, 2,
and 3 operator spine.

The result must add:

- repository-backed declarative runbook catalog and validation
- deterministic response runtime for incidents
- guarded executable step orchestration
- explicit approval and two-person approval support
- compensation and rollback tracking
- structured post-incident review and action items
- web-admin and TUI operator surfaces for active response

## Delivery Definition

Stage 4 is complete when an operator can:

1. store and validate versioned runbooks from the repository
2. start a response run for an incident
3. see the current step, waiting state, approvals, artifacts, and outputs
4. execute or advance manual and guarded automated steps
5. approve, reject, retry, abort, and compensate with explicit audit state
6. finish or abort a response deterministically
7. create and manage a structured post-incident review with findings and
   action items
8. inspect the full response lifecycle through the product surfaces

## Implementation Strategy

Build in the following order:

1. domain contracts and enums
2. SQLite schema and repositories
3. runbook catalog and loader
4. response runtime and approval services
5. executor registry and bounded executors
6. incident / engagement integration
7. web-admin and TUI surfaces
8. deterministic tests and critical review

This order keeps execution, approval, and persistence rooted in explicit
contracts instead of UI-first shortcuts.

## Phase 1: Domain Contracts

### Goal

Define explicit Stage 4 contracts for runbooks, response runtime, approvals,
artifacts, compensation, review findings, and action items before persistence
and UI work.

### Deliverables

- response and review enums
- runbook definition models
- response run, step run, approval, artifact, and compensation models
- post-incident review models
- Stage 4 response events

### Target files

```text
src/cockpit/shared/enums.py
src/cockpit/domain/models/response.py
src/cockpit/domain/models/review.py
src/cockpit/domain/events/response_events.py
```

### Exit criteria

- every persisted Stage 4 record is representable as typed dataclasses
- response, approval, and compensation semantics are explicit

## Phase 2: Persistence

### Goal

Extend SQLite with runbook catalog, response runtime, approval, artifact, and
review state.

### Deliverables

- schema migration for Stage 4 tables
- focused repositories for response runs, steps, approvals, artifacts,
  compensation, reviews, findings, and action items
- query helpers for active runs, waiting approvals, and recent reviews

### Target files

```text
src/cockpit/infrastructure/persistence/schema.py
src/cockpit/infrastructure/persistence/migrations.py
src/cockpit/infrastructure/persistence/ops_repositories.py
tests/integration/test_stage4_ops_repositories.py
```

### Exit criteria

- Stage 4 records round-trip through SQLite
- repository APIs cover runtime, admin, and TUI read paths without ad hoc SQL

## Phase 3: Runbook Catalog

### Goal

Create the repository-backed runbook source-of-truth and strict schema
validation.

### Deliverables

- runbook file loader
- strict validation and checksum generation
- catalog indexing into SQLite
- runbook list and detail queries

### Target files

```text
src/cockpit/infrastructure/runbooks/loader.py
src/cockpit/infrastructure/runbooks/schema.py
src/cockpit/application/services/runbook_catalog_service.py
config/runbooks/
tests/unit/test_runbook_catalog_service.py
tests/unit/test_runbook_loader.py
```

### Exit criteria

- invalid runbooks are rejected deterministically
- valid runbooks can be listed and versioned through the application

## Phase 4: Response Runtime And Approval

### Goal

Implement the primary response runtime, approval gates, and compensation flows.

### Deliverables

- `ResponseRunService`
- `ApprovalService`
- response state transitions
- waiting approval, operator wait, retry, abort, and compensation behavior
- incident linkage and response timeline emission

### Target files

```text
src/cockpit/application/services/response_run_service.py
src/cockpit/application/services/approval_service.py
src/cockpit/application/services/postincident_service.py
src/cockpit/domain/events/response_events.py
tests/unit/test_response_run_service.py
tests/unit/test_approval_service.py
tests/unit/test_postincident_service.py
```

### Exit criteria

- one incident can own a deterministic primary response run
- approval and compensation are explicit persisted flows
- no hidden auto-resume or silent re-execution exists

## Phase 5: Executor Registry And Step Execution

### Goal

Implement bounded runbook execution through centralized step executors.

### Deliverables

- `ResponseExecutorService`
- manual, shell, HTTP, Docker, and DB step executors
- operation-intent to guard-policy evaluation
- structured artifacts and output summaries

### Target files

```text
src/cockpit/application/services/response_executor_service.py
src/cockpit/infrastructure/runbooks/executors/manual.py
src/cockpit/infrastructure/runbooks/executors/shell.py
src/cockpit/infrastructure/runbooks/executors/http.py
src/cockpit/infrastructure/runbooks/executors/docker.py
src/cockpit/infrastructure/runbooks/executors/db.py
tests/unit/test_response_executor_service.py
```

### Exit criteria

- every executable step flows through one central execution contract
- risky operations are still governed by the existing guard spine

## Phase 6: Incident And Engagement Integration

### Goal

Link response runtime to the existing incident and Stage 3 engagement plane.

### Deliverables

- response run creation from incident scope
- optional engagement linkage
- response status influence on diagnostics and summaries
- response-related command handlers

### Target files

```text
src/cockpit/application/services/incident_service.py
src/cockpit/application/services/escalation_service.py
src/cockpit/application/handlers/response_handlers.py
src/cockpit/bootstrap.py
config/commands.yaml
tests/unit/test_response_handlers.py
```

### Exit criteria

- incidents can start response runs without creating a second incident model
- active response state is visible in the operator spine

## Phase 7: Web Admin And TUI Surfaces

### Goal

Expose Stage 4 through the existing web-admin control plane and a dedicated
response-centric TUI surface.

### Deliverables

- web-admin sections for runbooks, responses, approvals, and post-incident
- dedicated `ResponsePanel` for live response operation
- operator actions for start, execute, approve, retry, abort, and compensate

### Target files

```text
src/cockpit/application/services/web_admin_service.py
src/cockpit/infrastructure/web/admin_server.py
src/cockpit/ui/panels/response_panel.py
src/cockpit/ui/screens/app_shell.py
src/cockpit/bootstrap.py
tests/integration/test_web_admin_server.py
tests/unit/test_response_panel.py
```

### Exit criteria

- operators can inspect and operate Stage 4 without editing SQLite directly
- the TUI remains focused on live execution, not runbook authoring

## Phase 8: Testing And Review

### Goal

Provide deterministic test coverage for state machines, persistence, runbook
loading, approval logic, executor behavior, and surface integration.

### Deliverables

- unit tests for runbook validation, state transitions, approvals, and
  compensation
- integration tests for SQLite persistence and web-admin flows
- TUI surface tests for active response context
- compile and full unittest verification

### Exit criteria

- Stage 4 behavior is deterministic and regression-resistant
- architecture remains cohesive and maintainable under strict review

## Critical Integration Rules

- do not duplicate incident state inside response runtime
- do not bypass `GuardPolicyService`
- do not execute prod-mutating steps without explicit approval
- do not let response restart semantics silently re-run steps after process
  restart
- do not implement approval as a boolean flag; decisions must be persisted
- do not allow compensation to mutate state without the same policy spine

## Testing Focus Areas

### Unit

- runbook schema validation
- response run state transitions
- approval threshold logic including two-person approval
- compensation transition rules
- executor normalization and guard integration

### Integration

- SQLite round-trip for response runs, steps, approvals, artifacts, reviews,
  and action items
- response-start flow attached to an incident
- web-admin actions for approval and review

### TUI

- response panel rendering and selection
- command context for selected response run and approval

### End-to-End Light

- incident -> response run -> approval -> execution -> completion -> review
- failure -> compensation -> blocked/completed outcome

## Risks

### Scope Creep

- risk: Stage 4 becomes a generic workflow system
- mitigation: keep the runtime linear and incident-centric

### Unsafe Execution

- risk: executors introduce an unguarded path
- mitigation: all executable steps use the centralized executor service and
  guard evaluation

### Approval Drift

- risk: approval semantics diverge across UI and runtime
- mitigation: `ApprovalService` remains canonical and surfaces only call it

### Review Sprawl

- risk: post-incident review degrades into unstructured notes
- mitigation: findings, action items, and closure quality remain first-class
  models
