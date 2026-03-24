# Stage 4 Incident Response Lifecycle Design

Date: 2026-03-24
Status: Draft approved in interactive design review

## Scope

This spec defines Stage 4 of the operator evolution for `cockpit_cli`.

Stage 1 established:

- structured health, incidents, recovery, and quarantine
- centralized guard policy and operator-grade diagnostics

Stage 2 extended that spine with:

- persisted notifications, routing, and suppression
- broader component watches and operator notification handling

Stage 3 added:

- first-class on-call ownership
- escalation policy
- active engagement runtime for incidents

Stage 4 builds the next operator-grade layer on top of that foundation:

- structured incident response execution
- guarded runbook automation
- approval and compensation flows
- post-incident review and action tracking

This stage must remain one coherent operator architecture:

- incidents remain canonical
- engagements remain the ownership and paging plane
- Stage 4 adds response execution and structured review on top of those
  existing contracts

Stage 4 is not a generic workflow engine and not an ad hoc scripting feature.

## Product Decision

The approved product decision is:

- Stage 4 is a purpose-built incident response lifecycle system
- it includes both:
  - active response during an incident
  - structured post-incident review after or alongside response
- runbooks are declarative, versioned, and stored in the repository
- runbooks may contain executable steps, not only manual checklists
- mutating production-like steps never execute silently
- high-risk classes may require two-person approval
- compensation and rollback are first-class response concepts
- the runtime stays deterministic and linear, not a generic DAG engine
- the local web admin is the deep control plane
- the TUI is the live operate plane for active response

## Goals

- Provide a deterministic response runtime attached to incidents
- Execute structured runbook steps through guarded executors
- Introduce explicit approval flows for risky operations
- Capture response artifacts, outputs, and status as persisted runtime state
- Support compensation and bounded retry without hidden behavior
- Add structured post-incident review records and action items
- Preserve one canonical operator history across incident, engagement,
  response, approval, and review
- Keep behavior inspectable, auditable, and testable

## Non-Goals

- a generic visual workflow builder
- arbitrary branching DAG execution
- unbounded auto-remediation loops
- user-authored Python code as the primary runbook format
- replacing existing incident, notification, or engagement models
- external SaaS-style incident collaboration features
- chat-ops command parsing as the primary execution interface

## Target Outcome

After Stage 4:

- an incident can start a response run from a versioned runbook
- a response run can execute manual or bounded automated steps
- every step persists guard decisions, approvals, artifacts, and outputs
- risky steps can block on one- or two-person approvals
- compensation steps can run explicitly and be tracked independently
- operators can inspect active response state in the TUI
- operators can manage runbooks, approvals, reviews, and action items in the
  web admin
- post-incident review becomes a structured artifact rather than a free-form
  note

## Architectural Principles

### One Incident Model

Response runtime attaches to the existing incident model. It does not create a
parallel incident object or a separate alert object.

### One Ownership Plane

Stage 3 engagement remains the ownership and paging layer. Stage 4 may link a
response run to an engagement, but it does not replace engagement semantics.

### Declarative Runbooks

Runbooks must be versioned files in the repository with a strict schema. This
makes them reviewable, diffable, auditable, and suitable for operator
workflows.

### Deterministic Runtime

Stage 4 must be explicit about:

- current step
- wait states
- approval states
- retries
- compensation
- abort and completion

No step may execute implicitly after restart without persisted state allowing
that exact transition.

### Guarded Automation

Runbook automation must reuse the existing policy and guard spine rather than
inventing a second unsafe execution path.

### Structured Review

Post-incident review must be modeled as persisted structured records with
status and action items, not left as free text inside timeline notes.

## Stage 4 Architecture

The implementation is split into six layers.

### 1. Runbook Catalog Layer

This layer defines the source-of-truth runbooks and loads them into the
application.

Responsibilities:

- discover runbook files from the repository
- validate them against a strict schema
- expose stable runbook ids and versions
- compute checksums and track source paths
- surface declared risk and approval metadata

Primary models and services:

- `RunbookDefinition`
- `RunbookStepDefinition`
- `RunbookCompensationDefinition`
- `RunbookArtifactDefinition`
- `RunbookCatalogService`
- `RunbookLoader`

### 2. Response Runtime Layer

This layer manages the active response lifecycle for incidents.

Responsibilities:

- start a response run for an incident
- persist current runtime state
- create and advance step runs
- transition through waiting, blocked, failed, compensating, and completed
  states
- allow operator actions such as execute, retry, abort, compensate, and skip
  where policy permits

Primary models and services:

- `ResponseRun`
- `ResponseStepRun`
- `CompensationRun`
- `ResponseRunService`

### 3. Approval Layer

This layer governs explicit operator approval for risky steps.

Responsibilities:

- create approval requests for steps that require approval
- enforce one- or two-person thresholds
- enforce approver role constraints
- persist decisions and comments
- expire or block stale requests

Primary models and services:

- `ApprovalRequest`
- `ApprovalDecision`
- `ApprovalPolicyDecision`
- `ApprovalService`

### 4. Execution Layer

This layer runs the concrete step executors.

Responsibilities:

- select the correct executor for each step kind
- translate a runbook step into a structured operation intent
- evaluate the step against runbook and guard policy
- execute manual, shell, HTTP, Docker, and DB steps through bounded contracts
- capture artifacts and structured summaries

Primary services and executors:

- `ResponseExecutorService`
- `ManualStepExecutor`
- `ShellStepExecutor`
- `HttpStepExecutor`
- `DockerStepExecutor`
- `DatabaseStepExecutor`

### 5. Post-Incident Review Layer

This layer captures structured review and follow-up work.

Responsibilities:

- create and update review records
- record findings and root-cause notes
- create and track action items
- link artifacts and timeline notes
- expose review completeness and closure quality

Primary models and services:

- `PostIncidentReview`
- `ReviewFinding`
- `ActionItem`
- `LinkedArtifact`
- `PostIncidentService`

### 6. Operator Surfaces

The web admin remains the deep control plane. The TUI remains the live operate
plane.

Web admin additions:

- runbook catalog
- response runs and step details
- approval queue and approval detail
- compensation history
- post-incident reviews and action items

TUI additions:

- active response summary
- selected response run and current step
- waiting approvals
- latest artifacts and step outputs
- explicit actions for execute, retry, abort, approve, and compensate

## Core Domain Model

### RunbookDefinition

Represents one versioned response runbook loaded from the repository.

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
- `steps`

### RunbookStepDefinition

Represents one ordered step in a runbook.

Fields:

- `key`
- `title`
- `executor_kind`
- `description`
- `operation_kind`
- `requires_elevated_mode`
- `requires_confirmation`
- `approval_policy`
- `retry_policy`
- `artifact_contract`
- `compensation`
- `step_config`

### ResponseRun

Represents one primary execution of a runbook for an incident.

Fields:

- `id`
- `incident_id`
- `engagement_id`
- `runbook_id`
- `runbook_version`
- `status`
- `current_step_index`
- `risk_level`
- `elevated_mode`
- `started_by`
- `started_at`
- `updated_at`
- `completed_at`
- `summary`
- `last_error`

### ResponseStepRun

Represents a persisted execution record for one runbook step.

Fields:

- `id`
- `response_run_id`
- `step_key`
- `step_index`
- `executor_kind`
- `status`
- `attempt_count`
- `guard_decision_id`
- `approval_request_id`
- `started_at`
- `finished_at`
- `output_summary`
- `output_payload`
- `last_error`

### ApprovalRequest

Represents one step-level approval gate.

Fields:

- `id`
- `response_run_id`
- `step_run_id`
- `status`
- `required_approver_count`
- `required_roles`
- `reason`
- `expires_at`
- `created_at`
- `resolved_at`

### ApprovalDecision

Represents one operator decision for an approval request.

Fields:

- `id`
- `approval_request_id`
- `approver_ref`
- `decision`
- `comment`
- `created_at`

### CompensationRun

Represents execution of a compensation step related to a forward step.

Fields:

- `id`
- `response_run_id`
- `step_run_id`
- `status`
- `started_at`
- `finished_at`
- `summary`
- `last_error`

### PostIncidentReview

Represents the structured review record for an incident and optional response
run.

Fields:

- `id`
- `incident_id`
- `response_run_id`
- `status`
- `owner_ref`
- `opened_at`
- `completed_at`
- `summary`
- `root_cause`
- `closure_quality`

### ReviewFinding

Represents one structured review finding or contributing factor.

Fields:

- `id`
- `review_id`
- `category`
- `severity`
- `title`
- `detail`
- `created_at`

### ActionItem

Represents a follow-up task created from a review.

Fields:

- `id`
- `review_id`
- `owner_ref`
- `status`
- `title`
- `detail`
- `due_at`
- `created_at`
- `closed_at`

## State Machines

### ResponseRun Status

Primary response statuses:

- `CREATED`
- `READY`
- `RUNNING`
- `WAITING_APPROVAL`
- `WAITING_OPERATOR`
- `BLOCKED`
- `FAILED`
- `COMPENSATING`
- `COMPLETED`
- `ABORTED`

Rules:

- `CREATED -> READY` after runbook validation and step materialization
- `READY -> RUNNING` when the current step begins
- `RUNNING -> WAITING_APPROVAL` when a step requires approval
- `RUNNING -> WAITING_OPERATOR` when a manual action is required
- `RUNNING -> FAILED` on step failure without automatic retry
- `RUNNING -> COMPENSATING` when explicit compensation begins
- `RUNNING -> COMPLETED` after the final successful step
- `WAITING_APPROVAL -> RUNNING` when approval thresholds are met
- `WAITING_OPERATOR -> RUNNING` on explicit operator action
- `BLOCKED -> RUNNING` only by explicit operator reset or valid dependency
  recovery
- no closed state may transition silently back to running

### ResponseStepRun Status

Step statuses:

- `PENDING`
- `READY`
- `RUNNING`
- `WAITING_APPROVAL`
- `WAITING_OPERATOR`
- `SUCCEEDED`
- `FAILED`
- `SKIPPED`
- `ABORTED`
- `COMPENSATED`

### ApprovalRequest Status

Approval request statuses:

- `PENDING`
- `APPROVED`
- `REJECTED`
- `EXPIRED`
- `CANCELLED`

### CompensationRun Status

Compensation statuses:

- `PENDING`
- `RUNNING`
- `COMPLETED`
- `FAILED`
- `SKIPPED`

## Runbook Format

Runbooks must be declarative YAML documents under a versioned repository path,
for example:

```text
config/runbooks/
  incident-response/
    docker-container-unhealthy.yaml
    database-read-latency.yaml
```

Each file must contain:

- metadata
- version
- scope / target hints
- ordered steps
- per-step executor config
- per-step policy metadata
- optional compensation definition
- artifact declarations

The loader must reject:

- unknown executor kinds
- duplicate step keys
- non-contiguous step order
- missing approval policy for steps that demand two-person approval
- invalid compensation references

## Policy Model

Stage 4 reuses the existing guard spine and adds a response-specific policy
layer.

### Response Policy

Response policy determines:

- whether a step is executable or manual-only
- whether approval is required
- whether elevated mode is required
- whether two-person approval is required
- retry and compensation behavior
- whether the step is blocked on production-like targets

### Guard Policy

The existing `GuardPolicyService` remains canonical for concrete risky
operations such as:

- Docker mutations
- DB mutations or destructive queries
- HTTP mutations against risky targets

Each executable step becomes an operation intent and then a `GuardContext`.

### Approval Policy

Approval policy determines:

- number of required approvers
- role or membership requirements
- expiry windows
- whether self-approval is allowed
- whether rejection hard-blocks the run

## Event Flows

### 1. Incident Starts Response

1. Incident enters response scope
2. `ResponseRunService.start_run(...)` resolves runbook
3. `ResponseRun` and initial `ResponseStepRun` are persisted
4. `ResponseRunCreated` event is published
5. TUI and web admin surfaces refresh

### 2. Executable Step Requires Approval

1. Runtime prepares the current step
2. Response policy says approval is required
3. `ApprovalRequest` is persisted
4. `ResponseRun` enters `WAITING_APPROVAL`
5. `ApprovalRequested` event is published
6. Notification plane may fan out approval notifications

### 3. Approval Completes

1. Operators submit one or more `ApprovalDecision` records
2. `ApprovalService` evaluates the threshold
3. Request becomes `APPROVED` or `REJECTED`
4. `ResponseRun` returns to `RUNNING` or becomes `BLOCKED/ABORTED`
5. `ApprovalResolved` event is published

### 4. Step Execution

1. `ResponseExecutorService` selects the executor
2. Guard evaluation is performed
3. Executor runs the step or records a controlled failure
4. `ResponseStepRun` is updated
5. Artifacts and output summaries are persisted
6. Runtime advances to the next step, wait state, or failure state

### 5. Step Failure and Compensation

1. Step fails after bounded retries
2. Runtime checks compensation policy
3. If compensation exists and is permitted, `CompensationRun` starts
4. Compensation artifacts and outcomes are persisted
5. Response remains `COMPENSATING`, `FAILED`, or `BLOCKED` depending on
   outcome

### 6. Response Completion and Review

1. Final step succeeds or run is explicitly closed
2. `ResponseRun` becomes `COMPLETED` or `ABORTED`
3. A `PostIncidentReview` may be created automatically or explicitly
4. Operators add findings and action items
5. Review and action items become part of incident closure quality

## Persistence Design

Stage 4 extends SQLite with the following primary tables.

### `runbook_catalog`

Stores indexed runbook metadata.

Important fields:

- `id`
- `version`
- `title`
- `source_path`
- `checksum`
- `risk_class`
- `metadata_json`
- `loaded_at`

### `response_runs`

Stores the runtime state for a response run.

Important fields:

- `id`
- `incident_id`
- `engagement_id`
- `runbook_id`
- `runbook_version`
- `status`
- `current_step_index`
- `risk_level`
- `elevated_mode`
- `started_by`
- `summary`
- `last_error`
- `started_at`
- `updated_at`
- `completed_at`

### `response_step_runs`

Stores step execution history.

Important fields:

- `id`
- `response_run_id`
- `step_key`
- `step_index`
- `executor_kind`
- `status`
- `attempt_count`
- `guard_decision_id`
- `approval_request_id`
- `output_summary`
- `output_payload_json`
- `last_error`
- `started_at`
- `finished_at`

### `approval_requests`

Stores step approval gates.

Important fields:

- `id`
- `response_run_id`
- `step_run_id`
- `status`
- `required_approver_count`
- `required_roles_json`
- `reason`
- `expires_at`
- `created_at`
- `resolved_at`

### `approval_decisions`

Stores individual approver votes.

Important fields:

- `id`
- `approval_request_id`
- `approver_ref`
- `decision`
- `comment`
- `created_at`

### `response_artifacts`

Stores output references and structured artifacts.

Important fields:

- `id`
- `response_run_id`
- `step_run_id`
- `artifact_kind`
- `label`
- `storage_ref`
- `summary`
- `payload_json`
- `created_at`

### `compensation_runs`

Stores compensation execution state.

Important fields:

- `id`
- `response_run_id`
- `step_run_id`
- `status`
- `summary`
- `last_error`
- `started_at`
- `finished_at`

### `postincident_reviews`

Stores review headers.

Important fields:

- `id`
- `incident_id`
- `response_run_id`
- `status`
- `owner_ref`
- `summary`
- `root_cause`
- `closure_quality`
- `opened_at`
- `completed_at`

### `review_findings`

Stores structured review findings.

Important fields:

- `id`
- `review_id`
- `category`
- `severity`
- `title`
- `detail`
- `created_at`

### `action_items`

Stores review follow-ups.

Important fields:

- `id`
- `review_id`
- `owner_ref`
- `status`
- `title`
- `detail`
- `due_at`
- `created_at`
- `closed_at`

### `response_timeline`

Stores a canonical response timeline.

Important fields:

- `id`
- `response_run_id`
- `incident_id`
- `event_type`
- `message`
- `payload_json`
- `created_at`

## Services And Boundaries

### RunbookCatalogService

Responsibilities:

- load and validate runbooks
- expose list/detail queries
- provide a stable `id + version + checksum` contract

### ResponseRunService

Responsibilities:

- start runs
- materialize steps
- drive state transitions
- coordinate execution, retry, abort, and compensation

### ApprovalService

Responsibilities:

- create approval requests
- record approval decisions
- evaluate thresholds and roles
- expire or cancel requests

### ResponseExecutorService

Responsibilities:

- resolve executor implementations
- build operation intents
- call guard policy
- normalize executor outputs

### PostIncidentService

Responsibilities:

- manage review records
- findings
- action items
- closure quality

## Web Admin Design

The existing local web admin must be extended with new structured surfaces.

### Runbooks Page

Shows:

- runbook catalog
- source path
- version
- risk class
- supported scopes
- validation status

### Responses Page

Shows:

- active and recent response runs
- current step
- status
- waiting approvals
- compensation state
- step artifacts
- explicit response actions

### Approvals Page

Shows:

- pending approvals
- required approvers
- received decisions
- expiry status

### Post-Incident Page

Shows:

- review status
- findings
- action items
- closure quality

## TUI Design

The TUI remains the live operations plane.

Recommended Stage 4 additions:

- a dedicated `ResponsePanel`
- compact response summary inside ops context
- operator actions for:
  - start response
  - approve selected request
  - retry selected step
  - abort selected run
  - trigger compensation where allowed

The TUI should not become the primary authoring surface for reviews or runbook
editing.

## Error Handling And Recovery

### Runbook Load Failures

- invalid runbooks are rejected from the catalog
- validation errors remain visible in admin diagnostics
- invalid definitions never become executable

### Step Execution Failures

- every failure persists to `response_step_runs`
- retries are bounded and explicit
- failures do not silently disappear
- compensation only runs when configured and allowed

### Approval Failures

- approval expiry is explicit
- rejection is explicit
- self-approval policy is explicit
- no implicit fallback approval exists

### Restart Behavior

- on process restart, active runs are reconstructed from SQLite
- waiting approval remains waiting
- manual steps remain waiting
- automated steps are not re-run unless the persisted state marks them
  retryable and pending

## Testing Strategy

Stage 4 requires deterministic tests across four levels.

### Unit

- runbook schema validation
- runbook loading and checksum behavior
- response state transitions
- approval threshold logic
- two-person approval rules
- compensation transitions
- executor normalization and guard integration

### Integration

- SQLite round-trip for response runs, step runs, approvals, artifacts,
  reviews, and action items
- response start from incident and engagement linkage
- approval request lifecycle
- post-incident review lifecycle

### Surface Tests

- web admin service payloads for runbooks, responses, approvals, and reviews
- HTTP server routes for new admin sections
- TUI response panel context and command behavior

### End-to-End Light

- incident -> response run -> approval -> execution -> completion -> review
- step failure -> compensation -> blocked/completed outcome

All tests must remain deterministic and must not depend on real production
systems.

## Risks

### Scope Creep Into Workflow Platform

Risk:

- the runtime grows into a generic orchestration engine

Mitigation:

- keep the model linear and incident-centric
- avoid generic branching and unbounded scheduling

### Unsafe Automation

Risk:

- response automation bypasses guard policy

Mitigation:

- every executable step flows through response policy and guard policy
- production-like mutation requires explicit approval paths

### State Explosion

Risk:

- run state, approval state, compensation state, and review state become
  tangled

Mitigation:

- keep each state machine explicit and separated by model
- centralize transitions in dedicated services

### Artifact Sprawl

Risk:

- outputs become unstructured text blobs

Mitigation:

- model artifacts and step summaries explicitly
- persist typed metadata and storage references

## Delivery Definition

Stage 4 is complete when an operator can:

1. store and validate versioned runbooks from the repository
2. start a response run for an incident
3. execute manual and guarded automated steps
4. approve risky steps through explicit approval records
5. see artifacts, outputs, retries, and compensation history
6. complete or abort a response deterministically
7. create and manage a structured post-incident review with action items
8. inspect the full response lifecycle from incident to review in the product
