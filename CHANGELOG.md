# Changelog

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
