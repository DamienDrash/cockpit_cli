# cockpit

Keyboard-first TUI platform for developer workspaces.

`cockpit` is a Textual-based terminal application for opening local or remote
developer workspaces, restoring them across restarts, and operating common
developer surfaces from one command and event model. It is built around
persisted sessions, structured panels, guarded mutating actions, and a
local-first architecture that also supports SSH-backed workspaces.

## Current Feature Set

- Persistent workspaces and sessions backed by SQLite
- Resume of the last workspace on restart
- Local and SSH-backed `Work` panel with embedded PTY terminal
- `Git`, `Docker`, `Cron`, `DB`, `Curl`, and `Logs` panels
- Command palette, slash commands, and keyboard bindings sharing one dispatcher
- Guard rails for mutating Docker, Cron, DB, and HTTP actions
- Connection profile aliases for remote workspaces
- Bash and Zsh completion output from the CLI wrapper

## Tech Stack

- **Language**: Python 3.11+
- **TUI**: Textual
- **Config**: YAML and TCSS
- **Persistence**: SQLite
- **Packaging**: Hatchling
- **Runtime**: local PTY plus SSH-backed shell launch

## Repository Layout

```text
config/
  commands.yaml
  keybindings.yaml
  layouts/
  themes/
docs/
  superpowers/
src/cockpit/
  application/
  domain/
  infrastructure/
  runtime/
  shared/
  ui/
tests/
```

## Prerequisites

- Python 3.11 or newer
- `ssh` for remote workspaces
- `docker` for Docker panel operations
- `crontab` for Cron panel operations
- `git` for Git panel inspection

Optional but recommended:

- a virtual environment
- a working SSH agent or SSH config for remote targets

## Installation

Clone the repository and install it in editable mode:

```bash
git clone git@github.com:DamienDrash/cockpit_cli.git
cd cockpit_cli
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Getting Started

Launch the app in the current directory:

```bash
cockpit open .
```

Resume the most recent workspace:

```bash
cockpit resume
```

Open a configured remote workspace profile:

```bash
cockpit open --connection prod /srv/app
```

List configured connection aliases:

```bash
cockpit connections
```

Print a shell completion script:

```bash
cockpit completion bash
cockpit completion zsh
```

## Connection Profiles

Connection profiles are optional and live in `config/connections.yaml`.

Example:

```yaml
connections:
  prod:
    target: deploy@example.com
    default_path: /srv/app
    description: Production deployment target
  stage:
    target: stage@example.com
    default_path: /srv/app
```

You can then open them through either form:

```bash
cockpit open --connection prod /srv/app
cockpit open @prod
cockpit open @prod:/srv/app/releases/current
```

The second and third forms use the same path syntax the slash command layer
understands, so CLI and in-app commands stay aligned.

## Plugin System

External plugin modules can register additional panels and commands through
`config/plugins.yaml`.

Example:

```yaml
plugins:
  - module: cockpit.plugins.notes_plugin
    enabled: true
```

The module must expose `register_plugin(context)`. Inside that hook a plugin may
register:

- additional `PanelSpec` entries
- additional command handlers

The example file [plugins.example.yaml](/home/damien/Dokumente/cockpit/config/plugins.example.yaml)
shows the expected shape, and [notes_plugin.py](/home/damien/Dokumente/cockpit/src/cockpit/plugins/notes_plugin.py)
demonstrates the registration contract.

## Core Commands

Slash commands, palette commands, and keybindings all route through the same
dispatcher.

Common commands:

```text
/workspace open .
/workspace open @prod:/srv/app
/workspace reopen_last
/session restore
/tab focus git
/layout apply_default
/terminal restart
/docker restart
/docker stop
/docker remove
/cron enable
/cron disable
/db run_query "SELECT name FROM sqlite_master"
/curl send GET https://example.com
```

## Keybindings

Default bindings from `config/keybindings.yaml`:

- `Ctrl+K` opens the command palette
- `Ctrl+1` to `Ctrl+7` switch tabs
- `Ctrl+T` focuses the work terminal
- `Ctrl+R` restarts the work terminal
- `F8` restarts the selected Docker container
- `F9` stops the selected Docker container
- `F10` removes the selected Docker container

## Panels

### Work

- opens local or SSH-backed workspaces
- mounts the embedded PTY terminal
- persists cwd, browser path, and selected file

### Git

- inspects the current repository
- shows branch summary and changed files

### Docker

- lists local or remote containers
- supports guarded restart, stop, and remove actions

### Cron

- lists local or remote crontab entries
- supports guarded enable and disable operations for the selected job

### DB

- discovers SQLite databases in the workspace
- runs local queries
- supports remote SQLite queries over SSH through remote Python execution

### Curl

- sends quick HTTP requests
- keeps draft state and recent response history in the session snapshot

### Logs

- shows recent command and runtime activity recorded in SQLite

## Persistence Model

Application state is stored in `.cockpit/cockpit.db`.

Persisted data includes:

- workspaces
- layouts
- sessions
- snapshots
- command history
- audit log entries

The `.cockpit/` directory is intentionally ignored by Git.

## Remote Execution Model

Remote workspaces use SSH in two modes:

- non-interactive inspection via `ssh ... sh -lc ...`
- interactive shell panels via `ssh -tt`

This allows the same workspace/session model to operate across local and remote
targets without changing the app shell.

## Testing

Run the standard suite:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py' -v
```

Run UI and E2E tests with the Textual dependency environment:

```bash
PYTHONPATH=src:/tmp/cockpit-deps python -m unittest \
  tests.e2e.test_embedded_terminal_widget \
  tests.e2e.test_app_resume_flow -v
```

Bytecode caches and runtime state are ignored, so test runs should not dirty the
repository anymore.

## Development Notes

- The project is intentionally layered into `application`, `domain`,
  `infrastructure`, `runtime`, and `ui`.
- New commands should be added once in the dispatcher path and then exposed via
  slash, palette, or keybindings as needed.
- Mutating actions should use confirmation flows rather than bypassing the guard
  model.
- Panels should snapshot only stable UI state, not fragile process internals.

## Known Boundaries

The project is well beyond a skeleton, but it is still opinionated and not
fully generalized in every area.

Current limits include:

- no third-party plugin marketplace
- no full terminal emulation stack
- no universal database backend abstraction beyond the SQLite-focused path
- no arbitrary layout editor UI yet

## License

No license file is currently included in the repository.
