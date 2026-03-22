# Core Platform Spine Implementation Plan

Date: 2026-03-22
Status: Ready for implementation
Input spec: [2026-03-22-core-platform-spine-design.md](../specs/2026-03-22-core-platform-spine-design.md)
Project: `cockpit`

## Objective

Implement the first vertical slice of `cockpit` as a startable, local-first
Textual application with:

- app shell
- workspace-first entry
- one central command path
- SQLite-backed session and layout persistence
- one real `WorkPanel`
- one embedded local terminal runtime
- conservative UI/workspace resume across restarts

This plan does not include SSH, feature panels, or live process resurrection.

## Delivery Definition

The slice is complete when a user can:

1. start `cockpit`
2. open a local workspace
3. land in a basic workspace layout
4. see a `WorkPanel` with project context and embedded terminal
5. close and reopen the app
6. return to the same workspace, layout, focus path, and `cwd`

## Implementation Strategy

Build inside-out, not outside-in.

Order:

1. shared types and configuration paths
2. domain models and schema contracts
3. event bus and command dispatcher
4. persistence layer
5. application services
6. local runtime and PTY support
7. UI shell and panel host
8. `WorkPanel`
9. integration and recovery flows

This order is strict enough to keep the UI from outrunning the architecture.

## Phase 1: Bootstrap the Project Skeleton

### Goal

Create the repository structure and Python project baseline required for the
slice.

### Deliverables

- `pyproject.toml`
- package/module layout under `src/cockpit/`
- base test directories
- config directories for layouts and themes
- application bootstrap entrypoint

### Files to create

```text
pyproject.toml
src/cockpit/__init__.py
src/cockpit/app.py
src/cockpit/bootstrap.py
src/cockpit/shared/
src/cockpit/domain/
src/cockpit/application/
src/cockpit/infrastructure/
src/cockpit/runtime/
src/cockpit/ui/
tests/unit/
tests/integration/
tests/e2e/
config/layouts/
config/themes/
config/keybindings.yaml
config/commands.yaml
```

### Notes

- Choose Textual and SQLite dependencies now.
- Keep configuration small and declarative.
- Do not create placeholder feature panels beyond what this slice needs.

### Exit criteria

- `python -m cockpit` or equivalent entrypoint starts a minimal app process
- imports and package boundaries are clean

## Phase 2: Shared Contracts and Domain Models

### Goal

Define the stable models that the rest of the slice depends on.

### Deliverables

- shared types
- enums
- serialization helpers
- schema version constants
- domain models for workspace, session, layout, panel state, command, events

### Target files

```text
src/cockpit/shared/types.py
src/cockpit/shared/enums.py
src/cockpit/shared/config.py
src/cockpit/shared/utils.py
src/cockpit/domain/models/workspace.py
src/cockpit/domain/models/session.py
src/cockpit/domain/models/layout.py
src/cockpit/domain/models/panel_state.py
src/cockpit/domain/commands/command.py
src/cockpit/domain/events/base.py
src/cockpit/domain/events/domain_events.py
src/cockpit/domain/events/runtime_events.py
```

### Design rules

- Keep models independent from Textual and subprocess implementations.
- Make snapshot-carrying structures explicitly serializable.
- Include schema versioning in persisted contracts from the beginning.

### Exit criteria

- unit tests cover model validation and serialization
- no UI module imports inside domain modules

## Phase 3: Event Bus and Command System

### Goal

Create one action path for all interaction sources.

### Deliverables

- typed in-process event bus
- command parser scaffolding
- command dispatcher
- handler registry
- command history/audit metadata contract

### Target files

```text
src/cockpit/application/dispatch/event_bus.py
src/cockpit/application/dispatch/command_dispatcher.py
src/cockpit/application/dispatch/command_parser.py
src/cockpit/application/handlers/base.py
src/cockpit/application/handlers/workspace_handlers.py
src/cockpit/application/handlers/session_handlers.py
```

### Required commands in this slice

- workspace open
- workspace reopen last
- session restore
- layout apply default
- terminal focus
- terminal restart

### Exit criteria

- slash/palette/keybinding actions can all become one `Command`
- handlers publish events through the same bus
- tests prove dispatcher routing and invalid-context handling

## Phase 4: Persistence Layer

### Goal

Implement SQLite-backed storage and config loading.

### Deliverables

- SQLite schema initialization
- repositories or store methods for workspaces, sessions, layouts, command
  history, audit metadata
- config loader for YAML/TCSS
- snapshot read/write support with schema version checks

### Target files

```text
src/cockpit/infrastructure/persistence/sqlite_store.py
src/cockpit/infrastructure/persistence/schema.py
src/cockpit/infrastructure/persistence/migrations.py
src/cockpit/infrastructure/persistence/repositories.py
src/cockpit/infrastructure/persistence/snapshot_codec.py
src/cockpit/infrastructure/config/config_loader.py
```

### Important decisions

- Keep migrations minimal but real.
- Store snapshot payloads as JSON in SQLite for this slice.
- Treat invalid schema versions as recoverable, not fatal.

### Exit criteria

- sessions and layouts can be inserted, loaded, updated
- snapshot save/load is covered by tests
- corrupt snapshot path produces controlled recovery result

## Phase 5: Application Services

### Goal

Orchestrate workspace open, layout apply, and session restore.

### Deliverables

- `WorkspaceService`
- `SessionService`
- `LayoutService`
- `NavigationController`

### Target files

```text
src/cockpit/application/services/workspace_service.py
src/cockpit/application/services/session_service.py
src/cockpit/application/services/layout_service.py
src/cockpit/application/services/navigation_controller.py
```

### Responsibilities to implement now

- resolve workspace metadata
- validate workspace root path
- create default session when none exists
- restore prior session snapshot when valid
- fall back to workspace root on invalid `cwd`
- publish recovery and restore events

### Exit criteria

- service layer can drive a full open-workspace flow without UI widgets
- integration tests cover happy path and recovery path

## Phase 6: Local Runtime and Terminal Backbone

### Goal

Implement the local runtime contract for the embedded terminal.

### Deliverables

- local shell adapter
- PTY manager
- stream router
- task supervisor

### Target files

```text
src/cockpit/infrastructure/shell/local_shell_adapter.py
src/cockpit/runtime/pty_manager.py
src/cockpit/runtime/stream_router.py
src/cockpit/runtime/task_supervisor.py
```

### Runtime requirements

- launch shell in requested `cwd`
- capture output incrementally
- emit start, output, and exit events
- stop process cleanly on panel disposal or app shutdown
- allow terminal restart via command

### Exit criteria

- runtime can start and stop a local shell under test
- PTY startup failures become explicit runtime events
- runtime layer has no Textual widget dependency

## Phase 7: UI Shell

### Goal

Build the Textual application shell around the service backbone.

### Deliverables

- root app
- header
- status bar
- tab bar
- command palette scaffold
- slash command input
- recovery state presentation

### Target files

```text
src/cockpit/ui/screens/app_shell.py
src/cockpit/ui/widgets/header.py
src/cockpit/ui/widgets/status_bar.py
src/cockpit/ui/widgets/tab_bar.py
src/cockpit/ui/widgets/command_palette.py
src/cockpit/ui/widgets/slash_input.py
src/cockpit/ui/theme/default.tcss
```

### UI rules

- UI subscribes to events and renders state transitions
- UI does not reach directly into SQLite or PTY internals
- recovery messages must be visible and actionable

### Exit criteria

- app shell starts and renders
- command input can trigger dispatcher commands
- status bar reflects lifecycle events

## Phase 8: Panel Host and WorkPanel

### Goal

Create the reference panel and prove the spine can host a real panel with
persisted state plus runtime.

### Deliverables

- generic panel host
- panel lifecycle contract
- `WorkPanel`
- embedded terminal widget region

### Target files

```text
src/cockpit/ui/panels/panel_host.py
src/cockpit/ui/panels/base_panel.py
src/cockpit/ui/panels/work_panel.py
src/cockpit/ui/widgets/file_context.py
src/cockpit/ui/widgets/embedded_terminal.py
```

### `WorkPanel` responsibilities

- display workspace path context
- track selected path / explorer context
- restore persisted `cwd` and selection state
- create embedded terminal through application/runtime boundary
- snapshot persistable panel state only

### Exit criteria

- `WorkPanel` mounts inside the layout
- embedded terminal starts in expected `cwd`
- focus can move into the terminal region
- panel snapshot survives restart

## Phase 9: Session Snapshot and Resume Integration

### Goal

Make close/reopen behavior trustworthy.

### Deliverables

- light snapshot writes on state changes
- structural snapshot writes on layout changes
- resume snapshot writes on shutdown/suspend
- restore path on startup/open

### Implementation notes

- snapshot writes should be centralized, not hidden inside widgets
- the terminal region must be recreated, not restored from stale runtime state
- invalid snapshots must degrade into reset/recovery behavior

### Exit criteria

- close and reopen returns to same workspace, layout, focus, and `cwd`
- no attempt is made to recover live interactive subprocess state
- user sees recovery UI if path or snapshot is invalid

## Phase 10: Tests and Hardening

### Goal

Stabilize the slice to the point that it can act as the backbone for later
panels.

### Required tests

#### Unit

- model serialization
- command parsing
- event bus publish/subscribe
- dispatcher routing
- snapshot schema version validation

#### Integration

- open workspace flow
- restore prior session flow
- invalid workspace path recovery
- invalid `cwd` recovery
- PTY startup failure recovery

#### End-to-end

- launch app
- open workspace
- see `WorkPanel`
- restart app
- resume workspace and layout

### Hardening items

- startup path cleanup
- graceful shutdown ordering
- clear audit metadata writes
- stable status messaging for recoverable failures

### Exit criteria

- critical flows covered by automated tests
- no known crash loop on invalid persisted state

## Proposed Implementation Order by File Area

This is the recommended working order inside the codebase:

1. `shared/`
2. `domain/`
3. `application/dispatch/`
4. `infrastructure/persistence/`
5. `application/services/`
6. `infrastructure/shell/` and `runtime/`
7. `ui/screens/` and `ui/widgets/`
8. `ui/panels/`
9. `tests/integration/`
10. `tests/e2e/`

## Risks to Watch

### Risk 1: UI outruns architecture

If the shell is built before commands, events, and snapshots are stable, the
slice will look convincing but remain brittle.

Mitigation:

- do not start with Textual polish
- require service-level integration tests before panel polish

### Risk 2: Terminal runtime leaks into domain contracts

If PTY or subprocess details leak into session or panel models, remote-ready
evolution will become expensive.

Mitigation:

- runtime state remains operational, not persistable domain state

### Risk 3: Resume over-promises

If implementation attempts best-effort process resurrection, failures will be
hard to reason about.

Mitigation:

- restore context only
- recreate terminal fresh
- show recovery states explicitly

## Definition of Done

The implementation plan is complete when the build work can be executed in
small, testable increments and the final result satisfies all of these:

- one startable Textual app
- one workspace-first happy path
- one real `WorkPanel`
- one real local embedded terminal runtime
- one command system for all action sources
- SQLite-backed session and layout persistence
- conservative, reliable UI/workspace resume
- visible recovery states for invalid path, invalid snapshot, and PTY failure

## Immediate Next Execution Step

Start implementation with Phase 1 through Phase 3 together:

- project bootstrap
- domain/shared contracts
- event bus and command dispatcher

Do not start by building the full Textual shell first.
