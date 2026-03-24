# Stage 5 Automation Control Plane Design

Date: 2026-03-24
Status: Draft approved in interactive design review

## Scope

This spec defines Stage 5 of the operator evolution for `cockpit_cli`.

Stage 1 established:

- structured health, incidents, recovery, quarantine, and guard policy
- persistent operational diagnostics and Incident Center workflows

Stage 2 extended that spine with:

- notification delivery, routing, and suppression
- broader watch coverage and operator-facing health surfaces

Stage 3 added:

- ownership, on-call schedules, escalation policy, and engagement runtime

Stage 4 added:

- structured incident response execution
- guarded runbooks, approvals, compensation, and structured post-incident review

Stage 5 builds the next operator-grade layer on top of that foundation:

- deterministic remediation orchestration beyond a single linear response path
- reusable remediation templates and target-aware execution policies
- structured case files and evidence packaging as first-class runtime outputs
- exportable, reviewable, and policy-governed operator records for the full
  response lifecycle

Stage 5 must remain one coherent operator architecture:

- incidents remain canonical
- engagements remain the ownership and paging plane
- response runs remain the incident-centric linear execution model
- Stage 5 adds a bounded remediation layer and evidence plane on top of those
  existing contracts

Stage 5 is not a generic workflow engine, not a background scheduler platform,
and not an ad hoc evidence export script.

## Product Decision

The approved product decision is:

- Stage 5 is an automation control plane with two equal halves:
  - deterministic remediation orchestration
  - operator-grade evidence packaging / case files
- response runs from Stage 4 remain linear and incident-centric
- remediation runs are a separate runtime with bounded fan-out and explicit
  policies
- evidence is assembled as structured runtime state, not reconstructed from
  logs after the fact
- the web admin is the deep authoring, inspection, and export plane
- the TUI is the live operate plane for active remediation status and control

## Goals

- Introduce reusable remediation plans and units without turning the product
  into a generic DAG engine
- Support deterministic multi-target execution with bounded parallelism
- Enforce execution windows, lock scopes, concurrency classes, and partial
  failure policy
- Persist per-target execution state, not only aggregate run state
- Make case files first-class records with manifests, evidence completeness,
  and export history
- Provide reliable exportable operator packages with redaction and inclusion
  policy
- Keep guard, approval, audit, diagnostics, and review history connected to
  remediation and case files
- Preserve inspectability, determinism, and restart safety

## Non-Goals

- arbitrary branching workflow graphs
- user-authored Python automation as the primary Stage 5 format
- a cron-like automation scheduler unrelated to incidents and operations
- replacing Stage 4 response runs or approvals
- replacing Stage 3 engagement semantics
- free-form forensic note taking as the primary evidence model
- external collaboration suites or ticketing integrations as the core of
  Stage 5

## Target Outcome

After Stage 5:

- an incident response run may launch a linked remediation run from a reusable
  remediation plan
- remediation runs may target multiple explicit resources with bounded
  parallelism and lock-aware safety
- blocked windows, lock conflicts, approvals, and partial failures become
  explicit runtime states
- each remediation target has independent persisted state, guard history,
  evidence completeness, and compensation status
- a case file is created and maintained as a first-class record for the
  incident lifecycle
- operators can inspect evidence completeness, included artifacts, guard
  decisions, review linkage, and export history from product surfaces
- structured case-file exports are reproducible and policy-governed

## Architectural Principles

### One Incident Spine

Incidents remain the canonical anchor object. Stage 5 must attach to existing
incident, engagement, response, and review records instead of inventing a
parallel alert or case object hierarchy.

### Separate Linear Response From Controlled Parallel Remediation

Stage 4 response runs stay linear and deterministic. Stage 5 remediation runs
form a separate runtime with explicit target-level state and bounded
parallelism. This avoids corrupting the simpler Stage 4 state machine.

### Explicit Runtime Policies

Stage 5 must make execution decisions inspectable:

- whether a target may execute now
- whether it is blocked by lock or execution window
- whether it exceeded concurrency or failure limits
- whether evidence is complete enough to export

No hidden retry, hidden fan-out, or hidden case-file assembly is allowed.

### Evidence Is Produced During Runtime

Case files are assembled from structured runtime events, diagnostics snapshots,
artifact references, guard decisions, approvals, and review state while the
system runs. They are not reconstructed from free-form logs later.

### Policy Before Execution

Every remediation target execution flows through:

- remediation policy
- guard policy
- approval policy where required
- lock and execution-window evaluation

This must happen centrally, not inside UI code or ad hoc executor branches.

### Restart Safety

On restart, the system reconstructs remediation runs, target runs, lock state,
and case files from SQLite. No target execution resumes unless persisted state
still permits that exact transition.

## Stage 5 Architecture

The implementation is split into six layers.

### 1. Remediation Catalog Layer

This layer defines reusable remediation templates stored in the repository.

Responsibilities:

- discover and validate remediation plan files
- expose stable ids, versions, checksums, and source paths
- model targets, fan-out rules, lock scopes, and evidence contracts
- support reuse from response runs and operator-triggered actions

Primary models and services:

- `RemediationPlanDefinition`
- `RemediationUnitDefinition`
- `RemediationTargetSelector`
- `EvidenceContractDefinition`
- `RemediationCatalogService`
- `RemediationLoader`

### 2. Remediation Runtime Layer

This layer manages active remediation execution.

Responsibilities:

- start remediation runs from incidents and optionally response runs
- materialize target runs from selectors and explicit targets
- evaluate execution windows and lock scopes
- schedule target executions under concurrency limits
- persist aggregate and per-target runtime state
- handle partial failure, compensation, suspend, abort, and completion

Primary models and services:

- `RemediationRun`
- `RemediationTargetRun`
- `RemediationExecutionLease`
- `RemediationRuntimePolicy`
- `RemediationRunService`
- `RemediationSchedulerService`

### 3. Policy And Lease Layer

This layer governs whether remediation may proceed.

Responsibilities:

- evaluate remediation policy against target, environment, plan, and runtime
- enforce lock scope and lease acquisition
- enforce execution windows and maintenance constraints
- define partial-failure and auto-compensation handling
- expose structured decision payloads for diagnostics and operators

Primary models and services:

- `RemediationPolicyDecision`
- `LeaseDecision`
- `ExecutionWindowDecision`
- `RemediationPolicyService`
- `ExecutionLeaseService`

### 4. Evidence And Case-File Layer

This layer manages structured evidence packaging.

Responsibilities:

- create and maintain case files linked to incident lifecycle objects
- collect guard decisions, approvals, diagnostics snapshots, artifacts, and
  review linkage
- track completeness and redaction state
- build deterministic export manifests
- record export jobs and outputs

Primary models and services:

- `CaseFile`
- `CaseFileEvidenceItem`
- `CaseFileExport`
- `EvidenceBundle`
- `CaseFileService`
- `EvidencePackagingService`

### 5. Monitoring Layer

This layer supervises due actions and runtime progression.

Responsibilities:

- sweep remediation runs for due target dispatch
- detect expired execution windows or stale waits
- expire leases safely
- update case-file completeness and export readiness
- publish runtime events for UI/admin refresh

Primary runtime pieces:

- `RemediationMonitor`
- `CaseFileMonitor`

### 6. Operator Surfaces

The web admin remains the deep control plane. The TUI remains the live operate
plane.

Web admin additions:

- remediation plan catalog
- remediation run list and detail
- target-run detail with lock/window/policy state
- case-file detail and evidence completeness
- export history and redaction status

TUI additions:

- compact remediation summary inside ops context
- selected remediation run / selected target view
- blocked lock and execution-window visibility
- current evidence completeness and export readiness
- explicit actions for start, resume, abort, compensate, and export

## Core Domain Model

### RemediationPlanDefinition

Represents one versioned remediation plan loaded from the repository.

Fields:

- `id`
- `version`
- `title`
- `description`
- `scope`
- `risk_class`
- `source_path`
- `checksum`
- `tags`
- `units`
- `default_concurrency_limit`
- `default_window_policy`

### RemediationUnitDefinition

Represents one reusable unit of remediation work.

Fields:

- `key`
- `title`
- `executor_kind`
- `operation_kind`
- `target_selector`
- `lock_scope`
- `concurrency_class`
- `requires_confirmation`
- `requires_elevated_mode`
- `approval_policy`
- `failure_policy`
- `evidence_contract`
- `compensation`
- `unit_config`

### RemediationRun

Represents one remediation execution attached to an incident and optional
response run.

Fields:

- `id`
- `incident_id`
- `response_run_id`
- `engagement_id`
- `plan_id`
- `plan_version`
- `status`
- `risk_level`
- `started_by`
- `started_at`
- `updated_at`
- `completed_at`
- `summary`
- `last_error`
- `policy_payload`

### RemediationTargetRun

Represents execution state for one target inside a remediation run.

Fields:

- `id`
- `remediation_run_id`
- `unit_key`
- `target_ref`
- `target_kind`
- `status`
- `attempt_count`
- `guard_decision_id`
- `approval_request_id`
- `lease_id`
- `started_at`
- `finished_at`
- `output_summary`
- `output_payload`
- `last_error`
- `evidence_complete`

### RemediationExecutionLease

Represents the active lease protecting a lock scope.

Fields:

- `id`
- `scope_ref`
- `scope_kind`
- `holder_run_id`
- `holder_target_run_id`
- `status`
- `acquired_at`
- `expires_at`
- `released_at`
- `release_reason`

### CaseFile

Represents the structured evidence package for an incident lifecycle.

Fields:

- `id`
- `incident_id`
- `engagement_id`
- `response_run_id`
- `remediation_run_id`
- `review_id`
- `status`
- `completeness_status`
- `manifest_version`
- `summary`
- `opened_at`
- `updated_at`
- `sealed_at`

### CaseFileEvidenceItem

Represents one included evidence item in a case file.

Fields:

- `id`
- `case_file_id`
- `category`
- `source_kind`
- `source_ref`
- `label`
- `payload`
- `redaction_state`
- `required`
- `included_at`

### CaseFileExport

Represents one export attempt for a case file.

Fields:

- `id`
- `case_file_id`
- `status`
- `requested_by`
- `requested_at`
- `completed_at`
- `format`
- `storage_ref`
- `manifest_payload`
- `error_message`

## Data Flow

### Remediation Start

1. Operator starts remediation from incident or response context
2. `RemediationRunService` loads plan definition and computes runtime policy
3. target selectors materialize target runs
4. case file is created or linked
5. run and target runs are persisted in `READY` / `PENDING`
6. runtime event announces remediation creation

### Target Dispatch

1. `RemediationMonitor` sweeps due runs
2. `RemediationSchedulerService` checks concurrency limit and target status
3. `ExecutionLeaseService` evaluates lock acquisition
4. `RemediationPolicyService` evaluates execution window and runtime policy
5. if allowed, execution flows through Stage 4 executor and guard spine
6. results, diagnostics snapshots, and evidence items are persisted

### Blocked Execution

If a target cannot execute:

- lock conflict -> target becomes `WAITING_LOCK`
- closed execution window -> target becomes `WAITING_WINDOW`
- approval required -> target becomes `WAITING_APPROVAL`
- unsafe policy outcome -> target becomes `BLOCKED`

These are explicit persisted states. No polling loop may silently bypass them.

### Case-File Assembly

1. remediation events and outputs generate structured evidence items
2. guard decisions, approvals, diagnostics snapshots, and review linkage are
   attached to the case file
3. completeness evaluation runs after each relevant change
4. export becomes available only when policy permits and required evidence is
   present

## Event Model

New Stage 5 domain/runtime events should include:

- `RemediationRunCreated`
- `RemediationRunStatusChanged`
- `RemediationTargetStatusChanged`
- `RemediationLeaseAcquired`
- `RemediationLeaseReleased`
- `CaseFileCreated`
- `CaseFileStatusChanged`
- `CaseFileCompletenessChanged`
- `CaseFileExportRequested`
- `CaseFileExportCompleted`
- `CaseFileExportFailed`

These events refresh admin/TUI surfaces and keep diagnostics aligned with
runtime state.

## Persistence Design

Stage 5 extends SQLite with these primary tables:

- `remediation_plans`
- `remediation_runs`
- `remediation_target_runs`
- `remediation_execution_leases`
- `remediation_timeline`
- `case_files`
- `case_file_evidence_items`
- `case_file_exports`

Important query patterns:

- list active remediation runs ordered by update time
- list target runs for one remediation run ordered by unit and target
- list active leases by scope or holder
- fetch case file detail with evidence items and latest export records
- list exportable but incomplete case files
- list blocked or waiting remediation targets for operator attention

Repositories must stay explicit and typed, following the existing
`ops_repositories.py` style.

## Policy Design

### Remediation Policy

Recovery policy from Stage 1 remains separate. Stage 5 introduces remediation
policy with at least:

- `max_concurrency`
- `lock_scope`
- `window_policy`
- `max_attempts_per_target`
- `partial_failure_mode`
- `auto_compensation_mode`
- `required_evidence_categories`
- `export_requires_review`

### Lease Policy

Lease semantics must support:

- deterministic acquisition and release
- safe expiry and reacquisition
- one active holder per lock scope
- explicit release reason

### Evidence Policy

Evidence policy must support:

- required vs optional evidence items
- redaction state
- export eligibility
- sealing behavior

## Error Handling And Recovery

### Plan Load Failures

- invalid remediation plans are rejected from the catalog
- validation errors remain visible in admin diagnostics
- invalid definitions never become runnable

### Lease Conflicts

- lock conflict does not fail the whole run immediately
- target stays in an explicit wait state
- operator can see the current lease holder

### Partial Failure

- per-target failures remain localized
- aggregate run status reflects policy outcome
- compensation is explicit and bounded

### Restart Behavior

- on restart, remediation runs, target runs, leases, and case files are
  reconstructed from SQLite
- blocked waits remain blocked
- running targets are never re-executed blindly
- export jobs are resumed only when persisted state marks them resumable

## Web Admin Design

Additions:

- `Remediation Plans` page
- `Remediation Runs` page with run and target detail
- `Case Files` page with evidence completeness and export history
- export action endpoints and detail view

Each page must show structured state rather than dumping JSON blobs.

## TUI Design

Recommended Stage 5 additions:

- extend `OpsPanel` with remediation summary
- add a dedicated `RemediationPanel`
- surface selected remediation run, blocked targets, waiting windows, and
  evidence completeness
- add explicit actions for:
  - start remediation
  - retry blocked target
  - abort remediation run
  - trigger compensation
  - request case-file export

The TUI should remain the live operate plane, not the primary authoring plane
for remediation plans or redaction policy.

## Testing Strategy

Stage 5 requires deterministic tests across four levels.

### Unit

- remediation plan schema validation
- policy evaluation for windows, locks, fan-out, and partial-failure modes
- lease acquisition and release semantics
- case-file completeness evaluation
- export eligibility and redaction decisions

### Integration

- SQLite round-trip for remediation runs, target runs, leases, case files,
  evidence items, and exports
- remediation start from incident/response context
- lease conflict and release lifecycle
- case-file creation and export lifecycle

### Surface Tests

- web admin payloads and routes for remediation and case-file sections
- TUI remediation context and command behavior
- diagnostics payloads for remediation and evidence status

### End-To-End Light

- incident -> response -> remediation -> case file -> export
- target lock conflict -> wait -> release -> resumed execution
- partial failure -> compensation -> sealed case file outcome

All tests must remain deterministic and must not depend on real production
systems.

## Risks

### Scope Creep Into Generic Workflow Engine

Risk:

- remediation runtime grows into a general orchestration platform

Mitigation:

- keep the model incident-centric and bounded
- avoid arbitrary branching and unbounded scheduling

### Unsafe Parallel Mutation

Risk:

- fan-out remediation mutates too many targets unsafely

Mitigation:

- explicit concurrency limits, execution windows, and lease policy
- all target execution remains guard-policy mediated

### Evidence Incompleteness

Risk:

- case files become unreliable because runtime fails to attach critical
  evidence

Mitigation:

- evidence contract on plans
- required evidence completeness checks
- export gating on completeness state

### State Explosion

Risk:

- response, remediation, lease, approval, and case-file state become tangled

Mitigation:

- separate state machines per model
- centralize transitions in dedicated services

## Delivery Definition

Stage 5 is complete when an operator can:

1. store and validate reusable remediation plans from the repository
2. start a remediation run linked to an incident and optional response run
3. execute bounded multi-target remediation under lock, window, and guard
   policies
4. inspect per-target execution state and partial-failure behavior
5. see case-file completeness, included evidence, and export readiness
6. export a deterministic case file with manifest and structured evidence
7. inspect the full path from incident to response, remediation, review, and
   evidence package in the product
