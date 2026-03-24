# Stage 5 Automation Control Plane Implementation Plan

Date: 2026-03-24
Status: Ready for implementation
Input spec: [2026-03-24-stage-5-automation-control-plane-design.md](../specs/2026-03-24-stage-5-automation-control-plane-design.md)
Project: `cockpit_cli`

## Objective

Implement Stage 5 as the next operator-grade layer on top of the Stage 1, 2,
3, and 4 operator spine.

The result must add:

- repository-backed remediation plan catalog and validation
- deterministic remediation runtime with per-target state
- centralized remediation policy and execution lease handling
- structured case files and evidence completeness tracking
- exportable evidence bundles and deterministic export history
- web-admin and TUI surfaces for remediation and case-file workflows

## Delivery Definition

Stage 5 is complete when an operator can:

1. store and validate reusable remediation plans from the repository
2. start a remediation run linked to an incident and optional response run
3. see active target runs, blocked lock/window states, and aggregate runtime
   status
4. execute bounded multi-target remediation under centralized policy
5. inspect structured case-file completeness and included evidence
6. request a deterministic case-file export and inspect export history
7. follow the full path from incident to response, remediation, review, and
   evidence package through the product

## Implementation Strategy

Build in the following order:

1. domain contracts and enums
2. SQLite schema and repositories
3. remediation catalog and validation
4. policy, lease, and case-file services
5. remediation runtime and monitor
6. response/runtime integration and evidence capture
7. web-admin and TUI surfaces
8. deterministic tests and critical review

This order keeps state contracts and persistence ahead of runtime behavior and
prevents UI-first shortcuts.

## Phase 1: Domain Contracts

### Goal

Define explicit Stage 5 contracts for remediation plans, remediation runtime,
leases, case files, evidence items, and export records.

### Deliverables

- remediation enums
- remediation plan and unit models
- remediation run, target run, and lease models
- case-file, evidence item, and export models
- Stage 5 remediation and case-file events

### Target files

```text
src/cockpit/shared/enums.py
src/cockpit/domain/models/remediation.py
src/cockpit/domain/models/casefile.py
src/cockpit/domain/events/remediation_events.py
```

### Exit criteria

- every persisted Stage 5 record is representable as typed dataclasses
- remediation and case-file state machines are explicit

## Phase 2: Persistence

### Goal

Extend SQLite with remediation, lease, and case-file records plus required
indexes and repository APIs.

### Deliverables

- schema migration for Stage 5 tables
- focused repositories for remediation plans, runs, target runs, leases,
  timelines, case files, evidence items, and exports
- query helpers for active runs, blocked targets, active leases, and exportable
  case files

### Target files

```text
src/cockpit/infrastructure/persistence/schema.py
src/cockpit/infrastructure/persistence/migrations.py
src/cockpit/infrastructure/persistence/ops_repositories.py
tests/integration/test_stage5_ops_repositories.py
```

### Exit criteria

- Stage 5 records round-trip through SQLite
- repository APIs cover runtime, admin, and TUI read paths without ad hoc SQL

## Phase 3: Remediation Catalog

### Goal

Create the repository-backed source-of-truth for remediation plans and strict
schema validation.

### Deliverables

- remediation file loader
- strict validation and checksum generation
- catalog indexing into SQLite
- plan list and detail queries

### Target files

```text
src/cockpit/infrastructure/remediation/schema.py
src/cockpit/infrastructure/remediation/loader.py
src/cockpit/application/services/remediation_catalog_service.py
config/remediations/
tests/unit/test_remediation_catalog_service.py
tests/unit/test_remediation_loader.py
```

### Exit criteria

- invalid remediation plans are rejected deterministically
- valid plans can be listed and versioned through the application

## Phase 4: Policy, Lease, And Case-File Services

### Goal

Implement centralized remediation policy, lease handling, and case-file
assembly before runtime dispatch.

### Deliverables

- `RemediationPolicyService`
- `ExecutionLeaseService`
- `CaseFileService`
- `EvidencePackagingService`
- completeness evaluation and export gating

### Target files

```text
src/cockpit/application/services/remediation_policy_service.py
src/cockpit/application/services/execution_lease_service.py
src/cockpit/application/services/case_file_service.py
src/cockpit/application/services/evidence_packaging_service.py
tests/unit/test_remediation_policy_service.py
tests/unit/test_execution_lease_service.py
tests/unit/test_case_file_service.py
tests/unit/test_evidence_packaging_service.py
```

### Exit criteria

- remediation policy decisions are explicit and persisted where appropriate
- lease handling is deterministic and restart-safe
- case-file completeness is computed from structured state

## Phase 5: Remediation Runtime And Monitor

### Goal

Implement the active remediation runtime, per-target execution state, and due
dispatch monitoring.

### Deliverables

- `RemediationRunService`
- `RemediationSchedulerService`
- `RemediationMonitor`
- target materialization, bounded dispatch, wait states, compensation,
  aggregate status updates

### Target files

```text
src/cockpit/application/services/remediation_run_service.py
src/cockpit/application/services/remediation_scheduler_service.py
src/cockpit/runtime/remediation_monitor.py
tests/unit/test_remediation_run_service.py
tests/unit/test_remediation_scheduler_service.py
```

### Exit criteria

- one incident/response context can own explicit remediation runs
- multi-target execution remains bounded and deterministic
- waits and partial failures are persisted as explicit runtime states

## Phase 6: Response Integration And Evidence Capture

### Goal

Connect remediation to existing response execution, diagnostics, review, and
guard infrastructure.

### Deliverables

- remediation start from incident/response scope
- evidence capture from guard decisions, approvals, artifacts, diagnostics, and
  review linkage
- remediation-related command handlers

### Target files

```text
src/cockpit/application/services/response_run_service.py
src/cockpit/application/services/operations_diagnostics_service.py
src/cockpit/application/services/postincident_service.py
src/cockpit/application/handlers/remediation_handlers.py
src/cockpit/bootstrap.py
config/commands.yaml
tests/unit/test_remediation_handlers.py
```

### Exit criteria

- remediation does not invent a second incident or review model
- evidence assembly stays connected to the existing operator spine

## Phase 7: Web Admin And TUI Surfaces

### Goal

Expose Stage 5 through the existing web-admin control plane and a dedicated
remediation-centric TUI surface.

### Deliverables

- web-admin sections for remediation plans, runs, case files, and exports
- dedicated `RemediationPanel` for live remediation operation
- ops summary integration for blocked targets and export readiness

### Target files

```text
src/cockpit/application/services/web_admin_service.py
src/cockpit/infrastructure/web/admin_server.py
src/cockpit/ui/panels/remediation_panel.py
src/cockpit/ui/panels/ops_panel.py
src/cockpit/ui/screens/app_shell.py
src/cockpit/bootstrap.py
tests/integration/test_web_admin_server.py
tests/unit/test_remediation_panel.py
tests/unit/test_ops_panel.py
```

### Exit criteria

- operators can inspect and operate Stage 5 without editing SQLite directly
- the TUI remains the live operate plane, not the primary authoring plane

## Phase 8: Final Review And Hardening

### Goal

Critically review the result for determinism, lock safety, evidence
completeness, and maintainability.

### Deliverables

- regression tests for restart safety, lock conflict, case-file completeness,
  and export lifecycle
- architecture review against the approved spec
- docs/config updates where needed

### Target files

```text
tests/
config/remediations/
docs/
```

### Exit criteria

- Stage 5 behavior is deterministic and regression-resistant
- no hidden retry, hidden fan-out, or hidden export behavior remains

## Risks And Controls

### Risk: Stage 5 grows into a generic workflow engine

Control:

- keep remediation incident-centric and bounded
- avoid arbitrary branching and unrelated scheduling concerns

### Risk: unsafe fan-out mutation

Control:

- centralize concurrency, window, and lease evaluation
- keep all executions inside existing guard policy

### Risk: incomplete or misleading case files

Control:

- model evidence contracts explicitly
- gate export on completeness and policy

### Risk: state explosion across response, remediation, and case files

Control:

- keep separate state machines and focused services
- use typed repositories and explicit transitions only
