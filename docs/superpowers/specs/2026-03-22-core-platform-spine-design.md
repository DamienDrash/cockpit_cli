# Core Platform Spine Design

Date: 2026-03-22
Status: Draft approved for spec review
Project: `cockpit`
Scope: First design slice only

## Summary

This spec defines the first implementation slice of `cockpit` as a startable,
local-first, keyboard-first TUI platform for developer workspaces.

The first slice is not a full developer platform. It is a product-shaped spine
that proves the architecture and interaction model:

- start the app
- open a local workspace
- apply a persisted layout
- mount a single real reference panel
- run a fresh local terminal inside that panel
- save and restore UI and workspace context across restarts

This slice explicitly does not attempt to resume live interactive terminal
processes. Resume is reliable and conservative: restore context, not process
internals.

## Goals

- Provide a startable Textual application with a stable app shell.
- Use one central command path for slash commands, palette actions, keybindings,
  and panel actions.
- Define the core domain models that later local and remote capabilities will
  share.
- Implement session snapshot and resume for UI and workspace state.
- Prove one real runtime path via a local `WorkPanel` with an embedded terminal.
- Persist application data in SQLite and user-editable defaults in YAML/TCSS.
- Keep the architecture remote-ready without implementing SSH in this slice.

## Non-Goals

- No SSH execution or remote session lifecycle.
- No Git, Docker, DB, Curl, Cron, or Ops panels yet.
- No full plugin marketplace or third-party plugin API.
- No aggressive process resurrection or PTY reattachment across restarts.
- No destructive-environment guardrails beyond the local-safe contracts needed
  for this slice.

## Product Boundary

The first slice should feel like a real application, not a prototype script.
The user journey is:

1. Launch `cockpit`
2. Open a local workspace
3. Land in a minimal but functional workspace view
4. See a `WorkPanel` with project context and an embedded terminal
5. Close and reopen the app
6. Return to the same workspace, layout, focus path, and working directory

The application boundary is therefore:

- full shell, navigation, and state backbone
- one reference panel with one real runtime path
- no attempt to cover the entire product surface

## Architecture

The system is organized into five operational layers and one shared support
area:

### UI Layer

Responsibilities:

- Textual application shell
- header, tab bar, status bar
- command palette
- slash command input
- panel hosts and focus management
- recovery and error presentation

Constraints:

- must not contain shell, PTY, persistence, or filesystem logic
- may react to events and invoke application services only through defined
  interfaces

### Application Layer

Responsibilities:

- orchestrate workspace opening
- coordinate session restore and snapshot save
- dispatch commands
- control navigation and focus
- bridge UI, domain, persistence, and runtime services

Primary services:

- `WorkspaceService`
- `SessionService`
- `LayoutService`
- `NavigationController`
- `CommandDispatcher`

### Domain Layer

Responsibilities:

- define stable models and policies
- define command and event types
- define snapshot boundaries
- remain independent from Textual and subprocess details

Primary concepts:

- `Workspace`
- `Session`
- `Layout`
- `PanelState`
- `Command`
- domain events

### Infrastructure Layer

Responsibilities:

- SQLite persistence
- config loading
- filesystem inspection
- local shell launching contract
- future transport boundaries for remote support

Primary adapters:

- `SQLiteStore`
- `ConfigLoader`
- `FilesystemAdapter`
- `LocalShellAdapter`

### Runtime Layer

Responsibilities:

- PTY lifecycle
- local process start/stop
- output streaming
- runtime event publication
- background task supervision

Primary runtime modules:

- `PTYManager`
- `StreamRouter`
- `TaskSupervisor`

### Shared Support

Responsibilities:

- types
- enums
- serialization helpers
- schema versioning helpers
- config and path helpers

## First-Slice Core Modules

### AppShell

Root Textual application.

Owns:

- active session reference
- active workspace reference
- active tab and focused panel references
- command palette
- slash command input
- modal and recovery presentation

It should not know how sessions are persisted or how PTYs are started.

### WorkspaceService

Opens and resolves a workspace.

Responsibilities:

- load workspace metadata
- validate workspace root path
- determine starting layout
- hand off to session and layout services

### SessionService

Owns session lifecycle.

Responsibilities:

- create session
- load session
- write snapshots
- restore session state
- archive or close session cleanly

Key rule:

- it restores UI and workspace context only
- it does not promise live terminal process restoration

### LayoutService

Owns layout materialization and snapshot translation.

Responsibilities:

- construct tab/split/panel graph from persisted data
- apply default layout when no prior snapshot exists
- validate incompatible or corrupt layout snapshots

### CommandDispatcher

Single action path for the application.

Responsibilities:

- accept parsed command objects
- validate context
- invoke one handler
- publish command and result events
- record history and audit metadata

### EventBus

Typed in-process bus used by services, UI, and panels.

Responsibilities:

- publish events
- register subscribers
- support synchronous handlers in this slice
- allow async-capable evolution later without changing event contracts

### PanelHost

Owns panel instantiation and lifecycle bridging.

Responsibilities:

- mount panel widgets
- wire events and command routing
- request panel snapshots
- dispose panels safely

### WorkPanel

Reference panel for the first slice.

Responsibilities:

- present workspace context
- show project path and explorer context
- track selected file or directory context
- host an embedded terminal region
- expose a panel-specific snapshot schema

This is the proof that the spine can host a real panel with real runtime.

### PTYManager

Owns the embedded terminal runtime.

Responsibilities:

- start a local PTY
- set `cwd` and launch environment
- stream output
- resize terminal
- stop and clean up process handles

### SQLiteStore

Primary persistence backend for application data.

Responsibilities:

- store sessions
- store workspaces
- store layouts
- store command history
- store audit metadata

## Domain Models

The exact field set can evolve, but these structures define the planning
contract for the slice.

### Workspace

```python
Workspace(
    id: str,
    name: str,
    root_path: str,
    target: SessionTarget,
    default_layout_id: str | None,
    tags: list[str],
    metadata: dict[str, object],
)
```

Notes:

- In this slice, `target` is always local.
- The model remains remote-ready by using a target abstraction now.

### SessionTarget

```python
SessionTarget(
    kind: Literal["local", "ssh"],
    ref: str | None,
)
```

Notes:

- `ssh` is reserved for future use.
- This keeps the session and workspace contracts stable when remote support
  arrives.

### Session

```python
Session(
    id: str,
    workspace_id: str,
    name: str,
    status: Literal["active", "suspended", "archived"],
    active_tab_id: str | None,
    focused_panel_id: str | None,
    snapshot_ref: str | None,
    created_at: datetime,
    updated_at: datetime,
    last_opened_at: datetime | None,
)
```

### Layout

```python
Layout(
    id: str,
    name: str,
    tabs: list[TabLayout],
    focus_path: list[str],
)
```

```python
TabLayout(
    id: str,
    name: str,
    root_split: SplitNode,
)
```

```python
SplitNode(
    orientation: Literal["horizontal", "vertical"] | None,
    ratio: float | None,
    children: list["SplitNode | PanelRef"],
)
```

```python
PanelRef(
    panel_id: str,
    panel_type: str,
)
```

### PanelState

```python
PanelState(
    panel_id: str,
    panel_type: str,
    config: dict[str, object],
    snapshot: dict[str, object],
    persist_policy: str,
)
```

### Command

```python
Command(
    id: str,
    source: Literal["slash", "palette", "keybinding", "panel_action"],
    name: str,
    args: dict[str, object],
    context: dict[str, object],
    timestamp: datetime,
)
```

## Event Model

Events are split into domain events and runtime/UI events.

### Domain Events

Examples:

- `WorkspaceOpened`
- `SessionCreated`
- `SessionRestored`
- `LayoutApplied`
- `CommandExecuted`
- `SnapshotSaved`

Properties:

- meaningful outside UI widgets
- persistable as audit metadata if needed
- useful for planning and later observability

### Runtime and UI Events

Examples:

- `PanelMounted`
- `PanelFocused`
- `PTYStarted`
- `ProcessOutputReceived`
- `TerminalExited`
- `StatusMessagePublished`

Properties:

- more transient
- tied to app runtime
- should not leak PTY internals into domain models

## Command Flow

All user action sources converge on one path:

```text
Input Source -> Parser -> Command Object -> CommandDispatcher
-> Handler -> EventBus -> Persistence/Audit
```

Supported input sources in the first slice:

- slash command input
- command palette
- keybindings
- panel action triggers

Examples:

- `/workspace open`
- palette action: `Open Workspace`
- keybinding to focus terminal
- panel action to change current directory

All of them must become `Command` objects and pass through the same dispatcher.

## Session and Snapshot Design

The session engine uses three snapshot layers.

### Light Snapshot

Used for frequent updates.

Contains:

- active tab
- focused panel
- current workspace path context
- current `cwd`
- explorer selection
- panel flags
- recent command state

### Structural Snapshot

Used when the layout changes.

Contains:

- open tabs
- split tree
- ratios and sizes
- visible panels
- focus path

### Resume Snapshot

Used on explicit save, suspend, or shutdown.

Contains:

- workspace reference
- layout reference or layout payload
- panel snapshots
- terminal launch configuration
- schema version

Does not contain:

- PTY handles
- process ids
- live terminal buffers
- interactive subprocess internals

## Resume Contract

Resume behavior for the first slice:

1. Load session metadata
2. Resolve workspace
3. Validate workspace root path
4. Apply layout
5. Instantiate panels
6. Restore persistable panel state
7. Recreate fresh local terminal in stored `cwd`
8. Publish `SessionRestored`

If the workspace path is invalid:

- the app must not crash
- the user must see a recovery state
- the session should remain inspectable

If the stored `cwd` is invalid:

- the app should fall back to workspace root
- the status area should show a clear message

## WorkPanel Design

The `WorkPanel` is the only real panel in the first slice.

### Purpose

Provide one reference panel that exercises:

- panel lifecycle
- persistence boundaries
- event subscriptions
- command routing
- local runtime integration

### Composition

The panel includes:

- workspace path context
- lightweight explorer or selection context
- main work region placeholder
- embedded terminal region

This is intentionally a hybrid panel. It proves that a panel can own both
persisted work context and a recreated runtime child.

### Persisted WorkPanel State

Persist:

- last selected path
- current `cwd`
- view mode flags
- panel-specific config

Do not persist:

- PTY handle
- current terminal process tree
- transient terminal output buffer

## Panel Lifecycle

The panel lifecycle contract for the first slice is:

- `mount()`
- `initialize(context)`
- `restore_state(snapshot)`
- `attach_terminal()`
- `snapshot_state()`
- `suspend()`
- `dispose()`

Rules:

- `initialize()` receives workspace context only
- `restore_state()` applies persistable snapshot data only
- `attach_terminal()` creates a fresh PTY after restore
- `snapshot_state()` must return serializable panel state only
- `dispose()` must release subscriptions and runtime handles

## Runtime Design

The runtime is local-only in this slice.

### PTYManager

Must support:

- create PTY
- launch shell
- set `cwd`
- propagate resize events
- stream stdout/stderr-equivalent output
- emit exit events
- stop process cleanly

### StreamRouter

Must support:

- delivering terminal output to the embedded terminal region
- forwarding terminal lifecycle messages to status and audit consumers

### TaskSupervisor

Must support:

- background snapshot writes
- config reload tasks
- lightweight health monitoring

## Persistence Design

### Storage Strategy

- SQLite for app data
- YAML for user-editable defaults
- TCSS for Textual theme definitions

### SQLite Tables

Initial planning schema:

#### `workspaces`

- `id`
- `name`
- `root_path`
- `target_kind`
- `target_ref`
- `default_layout_id`
- `tags_json`
- `metadata_json`

#### `sessions`

- `id`
- `workspace_id`
- `name`
- `status`
- `active_tab_id`
- `focused_panel_id`
- `snapshot_json`
- `schema_version`
- `created_at`
- `updated_at`
- `last_opened_at`

#### `layouts`

- `id`
- `name`
- `layout_json`
- `schema_version`

#### `command_history`

- `id`
- `session_id`
- `source`
- `command_name`
- `args_json`
- `executed_at`
- `status`

#### `audit_log`

- `id`
- `session_id`
- `event_type`
- `payload_json`
- `created_at`

### User-Editable Config Files

Expected config areas:

- `config/layouts/*.yaml`
- `config/keybindings.yaml`
- `config/commands.yaml`
- `config/themes/*.tcss`

## Error Handling and Recovery

The first slice must behave predictably under failure.

### Failure Modes to Handle

- workspace root path missing
- stored `cwd` invalid
- PTY creation failure
- snapshot write failure
- incompatible snapshot schema

### Required Behavior

- no startup crash loops
- visible recovery UI in `AppShell`
- actionable message with retry or reset path
- corrupted snapshots can be ignored or reset safely
- session remains visible even when terminal startup fails

## Security and Guardrails

This slice is local-first and low-risk, but some guardrails are required now.

Included:

- safe path validation before workspace open
- no silent fallback on invalid session state
- audit metadata for workspace open, session restore, snapshot save, and
  terminal start/exit
- schema versioning for snapshots and layouts

Deferred:

- environment risk coloring for remote targets
- destructive action confirmation flows for Docker, DB, and Cron
- external secret store integration
- remote reconnect or transport health policy

## Testing Strategy

The first slice needs tests for the backbone, not just widgets.

### Unit Tests

- domain model validation
- command parsing
- dispatcher routing
- snapshot serialization and schema version handling
- layout translation

### Integration Tests

- open workspace flow
- save and restore session flow
- invalid workspace recovery flow
- invalid `cwd` recovery flow
- PTY startup failure recovery flow

### UI and End-to-End Tests

- app starts to shell successfully
- workspace can be opened from the primary entry path
- `WorkPanel` mounts and terminal region initializes
- close and reopen returns to same workspace and layout

## Repository Structure

Planned structure:

```text
cockpit/
├── pyproject.toml
├── README.md
├── config/
│   ├── layouts/
│   ├── themes/
│   ├── keybindings.yaml
│   └── commands.yaml
├── docs/
│   └── superpowers/
│       └── specs/
├── src/
│   └── cockpit/
│       ├── app.py
│       ├── bootstrap.py
│       ├── domain/
│       ├── application/
│       ├── infrastructure/
│       ├── runtime/
│       ├── ui/
│       └── shared/
└── tests/
    ├── unit/
    ├── integration/
    └── e2e/
```

## Acceptance Criteria for This Spec

This spec is satisfied when an implementation plan can target a first slice that:

- starts a Textual app shell
- opens a local workspace
- renders a basic layout with one `WorkPanel`
- starts a fresh terminal inside that panel in the correct `cwd`
- writes and restores session snapshots for UI and workspace state
- recovers visibly and safely from invalid workspace, invalid `cwd`, snapshot,
  and PTY startup failures
- uses one command dispatcher path for all action sources

## Planning Notes

The implementation plan derived from this spec should prioritize:

1. domain models and schemas
2. command system and event bus
3. persistence contracts
4. layout and session services
5. local PTY runtime
6. Textual shell and `WorkPanel`

That ordering is intentional. The first slice should not start by polishing UI
before the command, snapshot, and runtime contracts are stable.
