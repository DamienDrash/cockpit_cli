# Terminal And Layout Endgame Design

Date: 2026-03-23

## Scope

This spec defines the final endgame pass for the remaining `Terminal/Layout`
gold-standard gaps in Cockpit.

The scope is intentionally narrow:

- full terminal-stack hardening for demanding fullscreen terminal programs
- a true visual layout editor in the local web admin
- no second domain model
- no live mutation of already running TUI sessions from the web editor

This spec does not cover unrelated remaining platform work such as plugin
sandboxing, external secret stores, or supply-chain signing beyond what is
needed to support the terminal/layout slice.

## Approved Decisions

- Cockpit remains Linux-first.
- The visual layout editor lives only in the local web admin.
- Layout edits may be saved and applied on the next reload or explicit layout
  apply flow; live patching of running TUI sessions is not required.
- The terminal path must support demanding fullscreen terminal applications such
  as `vim`, `less`, `htop`, and similar tools.
- Cockpit should use an existing open-source terminal parser/emulator core when
  that better fits the requirement than extending the in-house minimal parser.
- The terminal end-state should use vendored `libvterm` with a Cockpit-owned
  Python binding layer.
- A dedicated frontend app may be introduced for the layout editor.

## Goal State

Cockpit keeps one product model:

- TUI as the primary operator surface
- local web admin as the visual setup and control plane

The final state for this slice is:

- the TUI terminal is powered by a real terminal emulation engine instead of the
  current lightweight parser
- fullscreen TUIs behave correctly enough to be a first-class workflow
- the web admin exposes a visual layout canvas editor with direct split and
  panel manipulation
- both surfaces still read and write the same persisted layout model

## Chosen Architecture

### 1. Terminal Architecture

Cockpit moves from the current simplified `TerminalBuffer` approach to a layered
terminal stack:

1. `PTYRuntime`
2. `TerminalEngine`
3. `EmbeddedTerminal`

`PTYRuntime` remains responsible for process lifecycle, PTY IO, resize, and
session supervision.

`TerminalEngine` becomes the emulation core. It is backed by vendored
`libvterm`, wrapped through a small Cockpit-owned `cffi` layer. The rest of the
application must not call `libvterm` directly.

`EmbeddedTerminal` becomes a renderer and interaction bridge. It translates
Textual keyboard and mouse events into engine input, renders screen snapshots,
and handles selection, copy, paste, and search UX.

### 2. Layout Architecture

The local web admin gains a dedicated frontend app for layout editing. The
recommended implementation is:

- TypeScript
- React
- Vite

The frontend app is responsible for:

- rendering the layout canvas
- drag-and-drop operations
- split-node insertion and removal
- panel movement and replacement
- ratio adjustment
- validation feedback

The Python backend remains responsible for:

- loading and saving layout definitions
- validating panel references
- persisting layout variants
- exposing panel metadata and editor APIs

No second persisted layout format is introduced.

## Terminal Design

### Engine Boundary

The Python application should not leak low-level terminal implementation details
across the codebase. Introduce explicit engine-facing contracts:

- `TerminalEngineSnapshot`
- `TerminalCell`
- `TerminalCursorState`
- `TerminalSelection`
- `TerminalSearchMatch`
- `TerminalInputEvent`

These objects become the boundary between the `libvterm` binding and the UI.

### libvterm Integration

Cockpit vendors a pinned `libvterm` source tree under a dedicated third-party
location inside the repository.

Build model:

- compile vendored `libvterm` during Cockpit packaging/build
- expose a tiny `cffi` binding module with only the functions Cockpit needs
- keep the binding layer small and tested independently

The vendored path is the primary build strategy. Optional future system-linking
can exist as a packaging optimization, but not as the main compatibility path.

### Expected Terminal Behaviors

The end-state terminal must support:

- alternate screen
- cursor addressing
- scrolling regions as far as `libvterm` provides them
- screen clearing and line clearing
- color and attribute rendering where practical in Textual
- robust resize handling
- copy and paste workflows
- mouse scrollback
- free selection beyond line-only selection
- search over visible and scrollback content

Behavioral goal:

- Cockpit should be comfortable for long-lived shell work
- demanding fullscreen TUIs should be viable, not merely partially legible

### Embedded Terminal UX

The new widget should support:

- keyboard input passthrough
- selection start / extend / clear
- mouse-driven region selection
- copy selected text
- paste clipboard text into the PTY
- search with next / previous match
- exporting the buffer when appropriate

The current line-prefix selection rendering is a transitional behavior. The end
state should render true highlighted regions from the engine snapshot.

## Layout Editor Design

### Editor UX Model

The editor is a real canvas-style visual tool in the web admin, not just a
preview plus forms.

Required editor interactions:

- add split around selected node
- toggle orientation
- drag divider to change ratio
- drag panel nodes to reorder or reparent
- replace a panel node with another panel type
- remove a panel node
- clone an existing layout variant
- reset unsaved editor changes

The editor only writes saved layout variants. Running TUI sessions are not live
repatched.

### Editor Data Model

The frontend may use a richer temporary editor state, but persisted output must
round-trip to the existing Python layout model:

- `Layout`
- `TabLayout`
- `SplitNode`
- `PanelRef`

That means:

- no browser-only persisted schema
- no JSON format divergence between frontend and backend
- validation must happen before save

### Backend APIs

The web admin backend should expose layout editor endpoints for:

- fetch all layouts
- fetch one layout with resolved panel metadata
- save a full layout document
- clone a layout
- validate a layout draft
- list available panel types and capabilities

The editor should prefer whole-document saves over incremental mutation RPCs.
That keeps the canvas logic in the frontend and the persistence logic in the
backend.

## Component Changes

### New Python Modules

- `src/cockpit/terminal/engine/`
- `src/cockpit/terminal/bindings/`
- `src/cockpit/infrastructure/web/layout_editor/` for static asset serving and
  API integration

Representative files:

- `libvterm_build.py`
- `libvterm_ffi.py`
- `engine.py`
- `snapshot.py`
- `selection.py`
- `paste.py`

### Reworked Existing Modules

- `src/cockpit/ui/widgets/embedded_terminal.py`
- `src/cockpit/ui/widgets/terminal_buffer.py`
- `src/cockpit/ui/panels/work_panel.py`
- `src/cockpit/application/services/layout_service.py`
- `src/cockpit/infrastructure/web/admin_server.py`

### New Frontend App

Add a dedicated layout editor frontend subtree, for example:

```text
web/layout-editor/
  package.json
  vite.config.ts
  src/
    main.tsx
    App.tsx
    components/
    state/
    api/
```

The Python web admin serves the built static assets and the layout API.

## Data Flow

### Terminal Flow

```text
PTY bytes
  -> libvterm binding
  -> TerminalEngineSnapshot
  -> EmbeddedTerminal render state
  -> Textual widget output
```

Input flow:

```text
keyboard/mouse/paste
  -> EmbeddedTerminal
  -> TerminalInputEvent
  -> libvterm input translation or PTY write
```

### Layout Flow

```text
LayoutRepository
  -> LayoutService
  -> Web admin layout API
  -> Layout editor frontend
  -> validated layout document
  -> LayoutService.save_layout()
```

Runtime application flow:

```text
saved layout
  -> next workspace open / apply / reload
  -> PanelHost materialization
```

## Error Handling

### Terminal

- If the `libvterm` binding fails to initialize, Cockpit must fail clearly and
  surface a precise diagnostic.
- If terminal snapshot rendering fails, the PTY session must remain recoverable.
- Unsupported escape features should degrade visibly, not silently corrupt the
  screen state.

### Layout Editor

- Invalid drafts should never be persisted.
- Unknown panel types must be rejected with actionable validation messages.
- Corrupt saved layouts should fall back to the last valid saved layout or the
  default layout, with an explicit operator-visible warning.

## Testing Strategy

### Terminal Tests

- unit tests for the `cffi` boundary wrapper
- golden fixture tests for terminal sequences and expected screen snapshots
- selection and paste tests
- resize and alternate-screen tests
- E2E tests against representative fullscreen TUIs where headless execution is
  realistic

### Layout Editor Tests

- frontend component tests
- drag-and-drop interaction tests
- whole-document save and validation tests
- backend integration tests for layout persistence and reload behavior

### Packaging Tests

- build tests ensuring vendored `libvterm` compiles
- CI smoke checks for the frontend build
- Arch/CachyOS packaging checks updated for the new native dependency path

## Rollout Plan

1. Introduce vendored `libvterm` and the binding layer.
2. Replace the current minimal terminal parser with the new engine-backed
   snapshot path.
3. Add paste and true region selection support.
4. Introduce the dedicated layout editor frontend and whole-document save API.
5. Replace the current form-first layout editor page with the canvas editor.
6. Expand CI, packaging, and release docs for the native and frontend build
   steps.

## Definition Of Done

This slice is done when:

- Cockpit can reliably run demanding fullscreen terminal TUIs in the embedded
  terminal
- the web admin exposes a genuine visual layout canvas editor
- saved layouts round-trip through the shared Python layout model
- no live TUI patching is required for layout edits
- CI covers the native terminal build and frontend build
- documentation reflects the new terminal and layout architecture
