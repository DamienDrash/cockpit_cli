# cockpit

Keyboard-first developer workspace cockpit for Linux.

`cockpit` combines a Textual TUI, a local web admin plane, persisted sessions,
guarded mutating actions, and a plugin-capable datasource platform. The app is
Linux-first and optimized for local development, SSH-backed environments, and
operator workflows that need one command/event model across terminal, Git,
Docker, Cron, DB, HTTP, and layout management.

## Core Capabilities

- persisted workspaces and sessions backed by SQLite
- local and SSH-backed workspaces with resume across restarts
- Textual TUI with `Work`, `Git`, `Docker`, `Cron`, `DB`, `Curl`, and `Logs`
- editable split layouts with persisted variants
- command palette, slash commands, and keybindings through one dispatcher
- guarded mutating flows for Docker, Cron, DB, and HTTP actions
- local web admin for datasource profiles, plugin installs, layouts, and diagnostics
- managed secret references with optional keyring-backed values and keyring rotation
- plugin install/update/pin/remove with repo or package requirements
- plugin compatibility, permission allowlists, and on-disk integrity verification before runtime activation
- broad datasource support through SQLAlchemy dialects plus non-SQL adapters
- terminal scrollback, search, keyboard or mouse-assisted selection, export, and clipboard copy

## Supported Datasource Families

Built-in datasource profiles support these backends:

- `sqlite`
- `postgres` / `postgresql`
- `mysql`
- `mariadb`
- `mssql`
- `duckdb`
- `bigquery`
- `snowflake`
- `mongodb`
- `redis`
- `chromadb`

Relational and analytics backends run through SQLAlchemy with external dialects
where appropriate. Non-SQL backends use dedicated adapters. Additional
datasources can be supplied by plugins.

## Tech Stack

- Python 3.11+
- Textual
- SQLite
- YAML + TCSS
- SQLAlchemy
- optional Ibis and backend-specific drivers

## Repository Layout

```text
config/
  commands.yaml
  connections.example.yaml
  datasources.example.yaml
  keybindings.yaml
  layouts/
  plugins.example.yaml
  themes/
docs/
  superpowers/
packaging/
  arch/
src/cockpit/
tests/
```

## Installation

### Core install

```bash
git clone git@github.com:DamienDrash/cockpit_cli.git
cd cockpit_cli
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Full datasource install

```bash
pip install -e '.[all-datasources]'
```

Or install only the extras you need, for example:

```bash
pip install -e '.[postgres,mysql,duckdb,mongo,redis]'
```

Enable keyring-backed secret resolution:

```bash
pip install -e '.[secrets]'
```

## Quick Start

Open the current directory:

```bash
cockpit open .
```

Resume the last session:

```bash
cockpit resume
```

List connection aliases:

```bash
cockpit connections
```

List configured datasource profiles:

```bash
cockpit datasources
```

Run the local web admin:

```bash
cockpit admin --open-browser
```

## TUI Commands

Common commands:

```text
/workspace open .
/workspace open @prod:/srv/app
/workspace reopen_last
/session restore
/tab focus db
/layout apply_default
/layout toggle_orientation
/layout grow
/layout shrink
/terminal focus
/terminal restart
/terminal search "error"
/terminal search_next
/terminal search_prev
/terminal export .cockpit/terminal-buffer.txt
/terminal copy
/docker restart
/docker stop
/docker remove
/cron enable
/cron disable
/db run_query "SELECT 1"
/curl send GET https://example.com
```

## Web Admin

The local web admin exposes:

- datasource profile creation and deletion
- datasource execution for quick operator queries and mutations
- managed secret references for env/file/keyring providers
- plugin install/update/pin/enable/remove
- layout cloning and split edits
- diagnostics for commands, panels, datasources, secrets, plugins, tunnels, and tool availability

It runs locally only and reuses the same application services as the TUI.

## Connection Profiles

Connection aliases live in `config/connections.yaml`. Start from
[connections.example.yaml](/home/damien/Dokumente/cockpit/config/connections.example.yaml).

Example:

```yaml
connections:
  prod:
    target: deploy@example.com
    default_path: /srv/app
    description: Production target
```

Then open through either form:

```bash
cockpit open --connection prod /srv/app
cockpit open @prod:/srv/app/current
```

## Datasource Profiles

Datasource profiles can be managed in the web admin or through
`config/datasources.yaml`. Start from
[datasources.example.yaml](/home/damien/Dokumente/cockpit/config/datasources.example.yaml).

Each profile captures:

- backend
- connection URL
- optional secret reference mappings for `${PLACEHOLDER}` interpolation
- optional driver
- risk level
- local or SSH target
- SSH tunneling for tunnel-safe remote SQL and NoSQL backends
- database name
- capabilities

Example secret-backed datasource snippet:

```yaml
profiles:
  - id: analytics-postgres
    name: Analytics Postgres
    backend: postgres
    connection_url: postgresql+psycopg://${DB_USER}:${DB_PASS}@db.internal:5432/analytics
    target_kind: ssh
    target_ref: deploy@example.com
    secret_refs:
      DB_USER: env:ANALYTICS_DB_USER
      DB_PASS:
        provider: keyring
        service: cockpit
        username: analytics-password
```

## Plugin System

Two plugin paths exist:

1. Static config loading from `config/plugins.yaml`
2. Managed installs through the web admin using pip-compatible requirements

Managed plugin installs support:

- package names
- pinned versions
- local paths
- git requirements
- trusted source prefix enforcement
- permission allowlists before runtime activation
- compatibility checks against the running cockpit version
- install-time and runtime integrity hashes

Plugins can contribute:

- panels
- commands
- datasource families
- admin pages

See [plugins.example.yaml](/home/damien/Dokumente/cockpit/config/plugins.example.yaml)
and [notes_plugin.py](/home/damien/Dokumente/cockpit/src/cockpit/plugins/notes_plugin.py).

## Packaging

Release artifacts included in the repo:

- `sdist`
- `wheel`
- Arch/CachyOS `PKGBUILD` in [packaging/arch/PKGBUILD](/home/damien/Dokumente/cockpit/packaging/arch/PKGBUILD)
- tag-driven GitHub release workflow in [.github/workflows/release.yml](/home/damien/Dokumente/cockpit/.github/workflows/release.yml)
- release checksum manifest generation (`SHA256SUMS.txt`)

## Development

Run tests:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py' -v
```

Run UI/E2E tests with the dependency environment:

```bash
PYTHONPATH=src:/tmp/cockpit-deps python -m unittest \
  tests.e2e.test_embedded_terminal_widget \
  tests.e2e.test_app_resume_flow -v
```

CI lives in [.github/workflows/ci.yml](/home/damien/Dokumente/cockpit/.github/workflows/ci.yml).
It compiles the code, runs the unittest suite, builds `sdist` plus `wheel`, and runs a live service matrix against PostgreSQL, MySQL, Redis, and MongoDB.
Tagged pushes additionally publish release artifacts through [.github/workflows/release.yml](/home/damien/Dokumente/cockpit/.github/workflows/release.yml).

## Operator Notes

Terminal selection flow:

- `Ctrl+Space` starts or clears a terminal line selection
- `Shift+Up` and `Shift+Down` expand the active selection
- `Ctrl+Shift+C` copies the selection
- `Ctrl+Alt+C` copies the full terminal buffer
- mouse wheel scrolls through scrollback
- clicking and dragging inside the embedded terminal expands the current line selection

Managed secrets:

- create them in the web admin under `Secrets`
- reference them inside datasource `secret_refs` as `stored:secret-name`
- keyring-backed entries can store the actual value directly if the optional `keyring` extra is installed
- keyring-backed entries can be rotated in place from the web admin without changing datasource references

Plugin trust policy:

- `config/plugins.yaml` can define `trusted_sources` and `allowed_permissions`
- plugins requesting permissions outside the configured allowlist stay installed but do not activate at runtime

Tunnel operations:

- remote datasource tunnels show reconnect counts and last-failure diagnostics in the web admin
- dead tunnels can be reconnected directly from the diagnostics page

Contribution and release notes:

- [CONTRIBUTING.md](/home/damien/Dokumente/cockpit/CONTRIBUTING.md)
- [CHANGELOG.md](/home/damien/Dokumente/cockpit/CHANGELOG.md)

## Linux Scope

This project is currently Linux-first. The repository includes first-class
packaging for Arch-like systems, including CachyOS.

## License

MIT. See [LICENSE](/home/damien/Dokumente/cockpit/LICENSE).
