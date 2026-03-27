# Phase 3: Module Restructuring (The Big One)

**Goal**: Transform the codebase into a true modular monolith following DDD and Hexagonal principles.

## Tasks

### 1. Structure Creation
Create the following top-level packages in `src/cockpit/`:
- `core/`: Shared platform spine.
- `workspace/`: Session, layout, and navigation logic.
- `ops/`: Incident, escalation, and response orchestration (DDD-heavy).
- `datasources/`: DB adapters, secrets, and SSH tunnels.
- `notifications/`: Channels and delivery policies.

### 2. File Migration
Move files according to the mapping defined in the main `implementation_plan.md`.
> [!IMPORTANT]
> Use `git mv` to preserve commit history.

### 3. Large File Decomposition
- **`ops_repositories.py` (148KB)**: Split into separate files per aggregate (e.g., `incident_repos.py`, `escalation_repos.py`).
- **`web_admin_service.py` (61KB)**: Split into a thin facade and context-specific handler modules.

### 4. Integration
- Update all internal imports project-wide.
- Update `bootstrap/wire_*.py` modules to reflect new package paths.
- Ensure all tests are updated to import from the new locations.

## Verification Criteria
- [ ] Full test suite passes.
- [ ] `python -m compileall src tests` is clean.
- [ ] The TUI boots and all tabs are functional.
- [ ] Web admin remains accessible.
