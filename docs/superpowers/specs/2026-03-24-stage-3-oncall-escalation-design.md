# Stage 3 On-Call And Escalation Design

Date: 2026-03-24
Status: Draft approved in interactive design review

## Scope

This spec defines Stage 3 of the operator evolution for `cockpit_cli`.

Stage 1 established:

- structured health and incident models
- bounded recovery, cooldown, and quarantine
- centralized guard policy
- deep operational diagnostics

Stage 2 extended that spine with:

- a persisted notification plane
- suppression and routing policy
- expanded health coverage
- stronger operator views in the TUI and local web admin

Stage 3 turns that foundation into a real internal on-call and escalation
system.

The result must remain one coherent operator architecture:

- incidents stay canonical
- notifications stay the transport plane
- Stage 3 adds ownership, on-call resolution, escalation policy, and active
  engagement runtime on top of those existing contracts

This stage is not a detached paging toy and not a second incident system.

## Product Decision

The approved product decision is:

- Stage 3 is an internal, operator-grade escalation and on-call plane
- it includes:
  - schedules
  - rotations
  - overrides
  - escalation chains
  - acknowledgement deadlines
  - repeat paging
- it models first-class:
  - people
  - teams
  - escalation targets
- ownership is distinct from delivery
- the local web admin is the full configuration plane
- the TUI is the live operations plane for active escalations

Stage 3 does not attempt to become a full external incident-management SaaS.

## Goals

- Add deterministic ownership and on-call resolution to incidents
- Route active incidents to the right operator or team at the right time
- Provide explicit escalation lifecycle state with auditability
- Keep notification delivery under the existing Stage 2 transport plane
- Support acknowledgement, reminder, repeat paging, escalation, and handoff
- Preserve one canonical incident model and one persistent operator history
- Keep behavior deterministic, inspectable, and testable

## Non-Goals

- external roster management platforms as a hard dependency
- SMS, voice, or phone-bridge delivery
- calendar sync with Google Calendar, Exchange, or CalDAV
- SLA analytics, shift fairness analytics, or payroll-style reporting
- arbitrary alert-expression DSLs
- retroactive recalculation of historical ownership after policy changes
- live patching every open incident when a schedule edit is saved

## Target Outcome

After Stage 3:

- incidents can be bound to an owning team and resolved to a responsible
  operator
- escalation policy can progress through explicit steps over time
- acknowledgement deadlines and repeat paging are deterministic and bounded
- handoffs and manual interventions are explicit, persisted, and auditable
- operators can manage schedules, rotations, overrides, and policies in the
  web admin
- operators can see active engagements, current owner, next escalation point,
  and perform live actions in the TUI
- all active escalation state is persisted and reconstructable

## Architectural Principles

### One Incident Model

An escalation engagement is linked to an existing incident. It extends the
incident with operational ownership and escalation runtime state. It does not
replace the incident and does not introduce an independent alarm object.

### Ownership Is Not Delivery

People, teams, schedules, and escalation targets define *who should own or
receive operator attention*. Notification channels define *how payloads are
transported*. Stage 3 must keep those concerns separate.

### Deterministic Temporal Resolution

On-call resolution must be a pure, inspectable computation from:

- schedule definition
- rotation definition
- override set
- effective timestamp

Historical runtime decisions must be persisted so later config edits do not
rewrite the past.

### One Runtime Spine

Stage 3 must extend the existing event-driven runtime and persistence layers.
It must not create an ad hoc scheduler hidden in UI code or adapter code.

### Bounded Escalation

Repeat paging, reminders, and step progression must be explicit and bounded.
No flow may retry indefinitely or silently disappear.

## Stage 3 Architecture

The implementation is split into six layers.

### 1. Ownership Model

This layer defines stable operator entities and routing boundaries.

Responsibilities:

- persist operators and teams
- model team membership
- attach ownership bindings to component classes, specific components, watch
  groups, or risk scopes
- provide explicit escalation targets

Primary models:

- `OperatorPerson`
- `OperatorTeam`
- `TeamMembership`
- `OwnershipBinding`
- `EscalationTarget`

### 2. Scheduling And Rotation Layer

This layer resolves who is on call at a particular time.

Responsibilities:

- define schedules
- define repeating rotations
- define temporary overrides
- resolve effective on-call operator(s) for a target team or schedule
- expose a deterministic explanation of how the result was computed

Primary models and services:

- `OnCallSchedule`
- `RotationRule`
- `ScheduleOverride`
- `OnCallResolution`
- `OnCallResolutionService`

### 3. Escalation Policy Layer

This layer defines how an incident engagement progresses.

Responsibilities:

- define escalation policies and ordered steps
- set acknowledgement deadlines
- set repeat-page cadence and limits
- define fallback steps and exhaustion behavior
- distinguish acknowledgement from incident resolution

Primary models and services:

- `EscalationPolicy`
- `EscalationStep`
- `EscalationPolicyService`

### 4. Engagement Runtime

This layer manages active escalation state for incidents.

Responsibilities:

- create an engagement when an incident enters escalation scope
- persist current owner, current step, and next deadlines
- issue reminders and repeat pages
- promote to the next step on deadline expiry
- stop progression on acknowledgement
- close engagement on incident resolution or closure
- support explicit manual handoff and re-page

Primary models and services:

- `IncidentEngagement`
- `EngagementTimelineEntry`
- `EscalationService`
- `EscalationMonitor`

### 5. Delivery Integration

Stage 3 uses the existing Stage 2 notification plane for actual message
transport.

Responsibilities:

- translate engagement actions into structured notification candidates
- link deliveries back to the engagement runtime
- keep delivery failures visible without corrupting incident state

Integration points:

- `NotificationService`
- `NotificationPolicyService`
- `SuppressionService`
- existing delivery adapters

### 6. Operator Surfaces

The web admin remains the configuration plane. The TUI remains the live
operations plane.

Web admin additions:

- people
- teams
- schedules
- rotations
- overrides
- ownership bindings
- escalation policies
- active engagement detail and timeline

TUI additions:

- active engagements
- current owner
- current escalation step
- acknowledgement deadline
- next reminder / next escalation transition
- ack
- handoff
- force re-page

## Core Models

### OperatorPerson

Represents an operator who may participate in on-call rotations or receive
escalation directly.

Fields:

- id
- display name
- handle
- enabled
- timezone
- contact targets
- metadata
- created at
- updated at

### OperatorTeam

Represents an ownership boundary for services or components.

Fields:

- id
- name
- enabled
- description
- default escalation policy id
- created at
- updated at

### TeamMembership

Represents a person-to-team relationship.

Fields:

- id
- team id
- person id
- role
- enabled
- created at
- updated at

### OwnershipBinding

Maps runtime or configuration scopes to the team that owns them.

Fields:

- id
- component kind or specific component id
- subject kind / subject ref
- optional risk-level filter
- team id
- escalation policy override id
- enabled
- created at
- updated at

Examples:

- all `docker_container_watch` incidents belong to `platform-ops`
- datasource `ds_prod_reporting` belongs to `analytics-ops`
- production-like HTTP incidents belong to `api-ops`

### OnCallSchedule

Defines the time domain and base schedule that a team uses.

Fields:

- id
- team id
- name
- timezone
- enabled
- coverage kind
- schedule config payload
- created at
- updated at

### RotationRule

Defines how people rotate through schedule coverage.

Fields:

- id
- schedule id
- name
- enabled
- participant ids
- anchor timestamp
- interval kind
- interval count
- handoff time
- created at
- updated at

### ScheduleOverride

Represents a temporary override to the normal resolution result.

Fields:

- id
- schedule id
- replacement person id
- optional replaced person id
- starts at
- ends at
- reason
- priority
- enabled
- actor
- created at
- updated at

### EscalationTarget

Represents an addressable escalation recipient abstraction.

Kinds:

- person
- team
- fixed notification channel

This target is a policy-facing abstraction and not a replacement for delivery
channels.

### EscalationPolicy

Defines the staged escalation behavior for owned incidents.

Fields:

- id
- name
- enabled
- default ack timeout seconds
- default repeat page seconds
- max repeat pages
- terminal behavior
- created at
- updated at

### EscalationStep

Defines one ordered stage in an escalation policy.

Fields:

- id
- policy id
- order index
- target kind / target ref
- ack timeout seconds
- repeat page seconds
- max repeat pages
- reminder enabled
- stop on ack
- created at
- updated at

### IncidentEngagement

Represents the active escalation runtime attached to an incident.

Fields:

- id
- incident id
- incident component id
- team id
- policy id
- status
- current step index
- current target kind / target ref
- resolved person id
- acknowledged by
- acknowledged at
- handoff count
- repeat page count
- next action at
- ack deadline at
- last page at
- exhausted
- created at
- updated at
- closed at
- payload

### EngagementTimelineEntry

Structured runtime history for an engagement.

Event types include:

- created
- paged
- reminder_sent
- acknowledged
- handed_off
- escalated
- exhausted
- resolved
- closed
- blocked

## Resolution Semantics

### Ownership Resolution

Ownership is resolved in this order:

1. explicit binding for exact component id
2. explicit binding for subject ref
3. binding for component kind
4. binding with matching risk-level filter
5. team default if configured
6. explicit unassigned / blocked outcome

Stage 3 must never guess silently.

### On-Call Resolution

On-call resolution for a team at timestamp `t` is computed from:

- enabled schedule
- enabled rotation rule(s)
- matching active override(s)

If multiple overrides apply, higher priority wins. Equal-priority conflicts are
validation errors, not runtime guesswork.

### Engagement Creation

An engagement is created when:

- an incident enters `open`
- the incident maps to a team or escalation target
- the incident is not already linked to an active primary engagement

Creation persists the initially resolved owner and first step before any page is
attempted.

### Acknowledgement

Acknowledgement means an operator has taken ownership of the escalation flow. It
does not automatically resolve the incident.

Effects:

- active step progression stops
- repeat paging stops
- engagement remains visible as acknowledged until the incident resolves or a
  later manual action changes state

### Handoff

Handoff explicitly changes the active responsible operator or target.

Effects:

- persists the new owner or target
- creates a timeline entry
- may trigger a fresh page via policy
- must be audit-visible and operator-visible

### Escalation Exhaustion

If no further steps remain and the engagement still lacks acknowledgement or
resolution:

- the engagement transitions to exhausted
- the state is visible in diagnostics and TUI surfaces
- no infinite paging loop is allowed

## Events

Stage 3 adds on-call and engagement domain events without replacing Stage 1 or
Stage 2 events.

Examples:

- `OwnershipResolved`
- `OwnershipResolutionFailed`
- `IncidentEngagementCreated`
- `EngagementPaged`
- `EngagementReminderDue`
- `EngagementAcknowledged`
- `EngagementHandedOff`
- `EngagementEscalated`
- `EngagementExhausted`
- `EngagementClosed`

The runtime loop remains event-driven:

- incidents drive engagement creation
- monitor sweeps drive due reminders and escalations
- operator actions drive ack and handoff transitions
- all externally visible transport still routes through notifications

## Persistence Design

SQLite remains the system of record. Stage 3 adds both configuration and runtime
history tables.

### Configuration Tables

- `operator_people`
- `operator_teams`
- `team_memberships`
- `ownership_bindings`
- `oncall_schedules`
- `schedule_rotations`
- `schedule_overrides`
- `escalation_policies`
- `escalation_steps`

### Runtime Tables

- `incident_engagements`
- `engagement_timeline`
- `engagement_delivery_links`

### Persistence Rules

- active engagement state is persisted explicitly
- resolved owner at the time of paging is persisted explicitly
- historical runtime records are never recomputed from future schedule edits
- all manual operator actions are timeline entries
- notification link records allow operators to correlate a page with its
  transport attempts

## Repository Layer

The existing SQLite repository style must be extended with focused repository
classes, not one god-repository.

Expected repository families:

- `OperatorPersonRepository`
- `OperatorTeamRepository`
- `ScheduleRepository`
- `EscalationPolicyRepository`
- `OwnershipBindingRepository`
- `IncidentEngagementRepository`
- `EngagementTimelineRepository`

These repositories must support:

- deterministic list/detail/configuration queries for the web admin
- active runtime queries for due engagement actions
- active-owner and current-step lookups for the TUI
- history and correlation queries for diagnostics

## Runtime Services

### OnCallResolutionService

Pure resolution service.

Responsibilities:

- resolve effective operator(s) for a schedule at time `t`
- apply overrides deterministically
- explain why a given operator was selected
- return explicit blocked or unassigned outcomes when resolution fails

### EscalationPolicyService

Pure policy service.

Responsibilities:

- select current and next step
- compute ack deadlines
- compute repeat-page cadence
- enforce bounded reminder and repeat behavior

### EscalationService

Orchestration service.

Responsibilities:

- create engagements for incidents
- apply acknowledgement and handoff actions
- persist step transitions
- invoke notification creation through the existing notification plane
- close engagements on incident resolution or closure

### EscalationMonitor

Periodic due-action runner.

Responsibilities:

- find due engagement actions
- trigger reminders
- trigger repeat pages
- advance steps after ack deadline expiry
- persist outcomes and publish events

This monitor must be deterministic and free of hidden backoff loops.

## Integration With Existing Systems

### Incidents

Stage 3 reads incident lifecycle from the existing Stage 1 incident service and
repositories. Engagements must link to incident ids rather than copying the
entire incident model.

### Notifications

Stage 3 pages through the existing Stage 2 notification system. A page is not a
special adapter path; it is a structured notification request with engagement
context.

### Suppression

Suppression remains transport-layer behavior from Stage 2. Stage 3 must not
confuse suppression with acknowledgement or escalation completion. Suppressed
pages must remain visible to operators as delivery outcomes.

### Guard Policy

Stage 3 operator actions such as handoff, forced re-page, or override edits may
require audit or confirmation integration, but Stage 3 does not merge
engagement policy with mutating guard policy.

## Web Admin Design

The local web admin gains full configuration and inspection surfaces for Stage
3.

New sections:

- People
- Teams
- Schedules
- Rotations
- Overrides
- Ownership Bindings
- Escalation Policies
- Active Engagements

Each section should support:

- list
- detail
- create / edit
- deterministic validation errors

Active engagement detail should show:

- linked incident
- team ownership
- current target and resolved operator
- current step
- current notification status summary
- ack deadline
- next action timestamp
- timeline

## TUI Design

The TUI remains an operate plane, not a configuration plane.

Expected Stage 3 additions to the existing operator view:

- active engagements summary
- current owner and team
- ack deadline and next action
- exhausted / blocked state visibility
- keyboard-first actions:
  - acknowledge
  - handoff
  - re-page
  - refresh

The TUI must not become a second schedule editor.

## Error Handling

Stage 3 must keep error classes explicit.

### Configuration Errors

- invalid schedule windows
- empty or invalid rotations
- overlapping override conflicts
- escalation step gaps or duplicate order indices
- ownership bindings with missing targets

These should fail validation at save time.

### Runtime Errors

- no resolvable owner
- no deliverable escalation target
- notification delivery failure
- exhausted escalation policy
- operator action against closed engagement

These must produce explicit persisted state and timeline entries.

### Determinism Rules

- no hidden fallback to arbitrary first team member
- no silent dropping when a page cannot be routed
- no infinite repeat paging
- no retroactive rewriting of historical owner resolution

## Testing Strategy

### Unit Tests

- ownership binding selection precedence
- schedule rotation resolution
- override priority and conflict detection
- escalation-step progression
- acknowledgement state transitions
- handoff behavior
- repeat-page bounding
- exhaustion behavior

### Integration Tests

- SQLite repository round-trips for all Stage 3 entities
- incident-to-engagement creation flow
- engagement-to-notification correlation
- monitor sweeps for reminders, repeat pages, and step escalation
- web-admin list/detail/action flows for config and active engagements

### TUI Tests

- active engagement summary rendering
- acknowledgement action wiring
- handoff action wiring
- exhausted / blocked visibility

### Review Criteria

- no second incident model exists
- transport and ownership remain separated
- time-based behavior is deterministic
- all operator-visible changes are persisted
- escalation exhaustion is explicit
- no hidden loops or silent drops exist

## Rollout Strategy

Stage 3 should ship incrementally behind the existing Stage 1/2 spine:

1. models and enums
2. schema and repositories
3. ownership and schedule resolution services
4. escalation policy and engagement runtime
5. notification integration
6. web-admin config surfaces
7. TUI active-engagement surface
8. deterministic verification and review

At each step, existing incident, notification, and diagnostics behavior must
stay backward-compatible.

## Open Boundaries For Later Stages

Stage 3 intentionally leaves room for later growth:

- external calendar sync
- SMS and voice transports
- external incident-management integrations
- fairness analytics and staffing optimization
- richer alert-rule authoring
- organization-wide roster governance

Those should build on the Stage 3 ownership and escalation runtime rather than
replace it.
