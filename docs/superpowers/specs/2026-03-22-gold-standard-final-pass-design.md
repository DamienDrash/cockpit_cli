# Gold Standard Final Pass Design

Date: 2026-03-22

## Scope

This spec covers the final pass required to close the remaining gaps between the current Cockpit product and the agreed "gold standard" target for this project.

The target is Linux-first, with CachyOS / Arch-style packaging support, and a TUI-first product model augmented by a small local web admin surface for complex control-plane tasks.

## Approved Decisions

- Linux is the only Tier-1 target for this final pass.
- The database platform should prioritize breadth.
- SQL backends should use SQLAlchemy as the relational core, including external dialects where appropriate.
- Where a backend supports safe mutation flows, Cockpit should expose them with explicit guard rails, audit logging, and risk-aware confirmations.
- Plugin/addon support should include repo-based installation, updates, and version pinning inside Cockpit itself.
- The product remains TUI-first, with a local web admin surface for plugin management, datasource management, layout editing, and diagnostics.
- The final pass should be delivered as one coordinated end-state, but implemented in controlled slices.

## End-State Product Model

Cockpit remains a single product with one command and event spine, one persistence layer, and two presentation surfaces:

- TUI for daily operational work
- Local web admin for visually complex setup and control tasks

Both surfaces must use the same application services, guard policy, audit model, and persistence layer. No second business logic path should be introduced in the web surface.

## Final Pass Slices

### 1. Foundation and Release Spine

This slice completes repository and release maturity:

- Linux-first packaging
- wheel and sdist builds
- Arch/CachyOS `PKGBUILD`
- CI workflows for test, build, and smoke checks
- license file
- release and contribution documentation
- diagnostics support required by the web admin and plugin manager

### 2. Database Platform

Introduce a unified datasource layer.

The platform will support:

- relational SQL backends through SQLAlchemy and external dialects
- analytical backends through Ibis where useful
- specialized adapters for non-SQL systems

Initial builtin targets for the final pass:

- SQLite
- PostgreSQL
- MySQL / MariaDB
- MSSQL
- DuckDB
- BigQuery
- Snowflake
- MongoDB
- Redis
- ChromaDB

Cockpit should provide a shared capability model instead of hardcoding UI logic per backend.

### 3. Plugin Ecosystem

The current plugin loader becomes a package-aware plugin platform with:

- plugin manifests
- compatibility checks
- repo-based install and update
- version pinning
- enable / disable / remove operations
- audit logging for plugin lifecycle events

Plugins may contribute:

- panels
- commands
- datasource adapters
- web admin pages
- migrations

### 4. Layout and Local Web Admin

The TUI stays as the operational surface. A local web admin server provides setup-heavy and visual workflows:

- datasource profile management
- plugin marketplace / install / update
- layout editor
- diagnostics and health information

The layout system should move beyond the current constrained split editing path and support:

- richer split tree editing
- add / remove / rebalance panel nodes
- persistence of edited layouts
- using the same layout model from both TUI and web admin

### 5. Terminal Hardening

The terminal stack should become significantly more capable on Linux:

- better ANSI handling
- stronger cursor and clear semantics
- search and scrollback improvements
- copy / selection workflows
- improved multi-session behavior
- stronger long-running session handling

This remains an embedded terminal optimized for the Cockpit experience, not a goal to become a standalone terminal emulator product.

## Core Architecture

### Control Core

All orchestration stays in application services and command handlers.

The final pass adds or expands these service responsibilities:

- `WorkspaceService`
- `SessionService`
- `LayoutService`
- `ConnectionService`
- `DataSourceService`
- `PluginService`
- `ReleaseService`
- `WebAdminService`

### Capability Model

Every datasource and plugin should expose capabilities rather than forcing the UI to infer behavior from type names.

Representative capability flags:

- `can_query`
- `can_mutate`
- `can_stream`
- `can_explain`
- `supports_schema_browser`
- `supports_transactions`
- `supports_vectors`
- `supports_keys`

TUI and web admin should drive actions from these capabilities.

### Adapter Spine

Three backend families:

- `SQLAdapter`
- `AnalyticalAdapter`
- `SpecializedAdapter`

Shared adapter contract:

- `healthcheck`
- `inspect`
- `run`
- `mutate`
- `capabilities`
- `serialize_profile`

### Presentation Split

- TUI for keyboard-first operator workflows
- Local web admin for setup and visual editing workflows

Both use the same commands, services, guards, audit trail, and state storage.

## Data Source Design

### Profiles

Each backend connection is represented as a `DataSourceProfile`, not just a URI.

The profile contains:

- id
- display name
- backend kind
- dialect / driver
- target / host / database metadata
- secret references
- risk level
- capability payload
- user-defined labels / tags

### SQL Strategy

Use SQLAlchemy as the main relational integration layer, with external dialects where appropriate. SQLAlchemy should be the default path for:

- SQLite
- PostgreSQL
- MySQL / MariaDB
- MSSQL
- DuckDB
- BigQuery
- Snowflake

Ibis may be layered on top where it materially improves analytical or portable workflows, but SQLAlchemy remains the primary relational contract.

### Non-SQL Strategy

Use dedicated adapter implementations for:

- MongoDB
- Redis
- ChromaDB

These adapters should expose Cockpit capabilities in the same way SQL adapters do, even when the underlying API is not SQL-shaped.

## Plugin Platform Design

### Plugin Manifest

Every plugin should declare:

- name
- version
- compatibility range
- Python module entrypoint
- optional dependencies
- provided panels
- provided commands
- provided datasource adapters
- provided web admin pages
- migrations

### Installation Model

Cockpit should support plugin repositories defined in config and install plugins into a managed local directory or virtualenv-aware location.

Operations:

- search
- install
- update
- pin
- unpin
- disable
- remove

All plugin lifecycle operations must be auditable.

## Layout Design

The current layout system already persists split trees. The final pass extends that model to support interactive editing:

- split orientation changes
- split ratio changes
- add sibling panel
- remove panel from split
- replace panel type in node
- save layout variant

The TUI may offer keyboard-driven structural editing. The web admin offers a visual editor backed by the same layout payloads.

## Web Admin Design

The local web admin is a control-plane companion, not a second full client.

Required pages:

- home / diagnostics
- datasource profiles
- plugin manager
- layout editor
- release / environment diagnostics

The server should stay local-only by default.

The web layer should call the same command and service layer as the TUI and must not invent parallel mutation logic.

## Guard Rails and Audit

Mutating flows must remain explicit and risk-aware.

Rules:

- production-risk targets require confirmation
- plugin installation and removal are audited
- datasource writes are audited
- destructive backend actions are audited
- secrets are referenced, never stored in snapshots

## Persistence and Migration

The state database needs new entities for:

- datasource profiles
- plugin repository definitions
- installed plugins and pinned versions
- web admin state
- richer layout metadata
- terminal preferences / search history

Schema migration support must remain forward-only and controlled.

## Testing Strategy

### Unit

- datasource adapters
- plugin manifest validation
- capability resolution
- guard policy
- layout editing transforms
- terminal buffer logic

### Integration

- service flows for datasource creation and execution
- plugin lifecycle operations
- migration round-trips
- release / packaging smoke helpers

### E2E TUI

- open / resume
- datasource operations
- plugin operations
- layout editing
- terminal interactions

### E2E Web

- plugin install / update / pin
- datasource profile management
- layout editor persistence
- diagnostics visibility

## Definition of Done

The final pass is complete only when:

- the repo has release maturity for Linux-first distribution
- the datasource platform supports the approved breadth with the shared capability model
- plugin installation and version pinning work inside Cockpit
- the local web admin is implemented and useful for the agreed control-plane tasks
- layout editing is richer than the current constrained split edit path
- terminal hardening is materially improved and covered by tests

