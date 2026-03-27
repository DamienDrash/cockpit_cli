# Changelog

## 0.1.44

- **Semantic Shell Highlighting**: Added real-time syntax highlighting for slash commands (`/cmd`, `--flags`, `@targets`).
- **Intelligent Terminal Buffers**: Implemented `SemanticOutputHighlighter` to flag errors in neon-red and highlight URLs/paths automatically.
- **Kontextsensitive Action-Bar**: Introduced a dedicated F-key bar that adapts its shortcuts to the active panel.
- **Git-Deep-Integration**: Revamped `GitPanel` with live branch monitoring, dirty state indicators, and ahead/behind status.
- **Resource Management**: Integrated real-time CPU and Memory sparklines in the status bar for immediate performance monitoring.
- **Environment Badges**: Added auto-detection for Python `.venv`, conda, Node.js, and Kubernetes contexts in the header.
- **Risk-Alert Borders**: Implemented dynamic border coloring based on risk levels, including a pulsing red animation for high-risk (PROD) environments.

## 0.1.43

- **Phase 3 Modular Monolith Restructuring**: Complete transition to DDD and Hexagonal architecture.
- **Top-level context packages**: Consolidated logic into `core`, `workspace`, `ops`, `datasources`, `notifications`, `plugins`, and `admin`.
- **Import Migration**: Updated all internal imports to reflect the new package structure.
- **Repository Standardization**: Unified repository query naming conventions (e.g., `get_*` to `find_*`).
- **Data Integrity**: Added `payload_json` to all `ops` repositories to ensure full model persistence and fix SQL `IntegrityError`s.
- **Schema Alignment**: Synchronized repository implementations with `schema.py` table and column names.
- **Panel Isolation**: Implemented base panel state management and error boundary defaults.
- **Test Hardening**: Fixed timing and dependency issues in unit and integration test suites.

## 0.1.5

- added Cyberpunk-inspired splash screen and system boot animation using `rich`
- refactored CLI command output (`connections`, `datasources`) with DevEx principles
- integrated semantic colors and "Next Steps" guidance for better CLI UX

## 0.1.4

- fixed `PanelStateChanged` event contract to prevent runtime crashes during UI state updates
- updated BigQuery dependency from `pybigquery` to `sqlalchemy-bigquery`
- split `all-datasources` into `pure` and `native` variants to clarify installation requirements
- added `bin/cockpit-cli-dev` wrapper for local development
- narrowed Python support range to 3.11-3.13 for improved reliability
- added automated smoke tests to CI pipeline

## 0.1.3

- validated automated PyPI release publishing via active Trusted Publisher setup
- documented recovery steps for PyPI projects that were created before a successful first upload

## 0.1.2

- broadened datasource platform with SQLAlchemy-backed profiles and non-SQL adapters
- added local web admin for datasource, plugin, layout, and diagnostics management
- added plugin install/update/pin/remove management
- added terminal search and export commands
- added Linux packaging metadata, CI workflow, and repository governance files
- hardened release supply-chain with SBOMs, Sigstore bundles, GitHub provenance, and PyPI Trusted Publishing

## 0.1.0

- initial core platform spine
- session persistence and resume
- Textual TUI with work, git, docker, cron, db, curl, and logs panels
